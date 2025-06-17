from fastapi import APIRouter, HTTPException, Depends, Header, status
from pydantic import BaseModel
from typing import List, Optional
from db import execute_query, get_db1
import razorpay
from payments import razorpay_client
import os
import json
from dotenv import load_dotenv
from fastapi.security import OAuth2PasswordBearer
from jose import JWTError, jwt
from datetime import datetime, timedelta
import logging

# Configure logging
logging.basicConfig(level=logging.INFO)
logger = logging.getLogger(__name__)

load_dotenv()

router = APIRouter()

# Security configurations
SECRET_KEY = os.getenv("SECRET_KEY", "your-secret-key-here")
ALGORITHM = "HS256"
ACCESS_TOKEN_EXPIRE_MINUTES = 30

oauth2_scheme = OAuth2PasswordBearer(tokenUrl="token")

# Table creation functions
def create_orders_table():
    query = """
    CREATE TABLE IF NOT EXISTS orders (
        order_id INT AUTO_INCREMENT PRIMARY KEY,
        user_id INT NOT NULL,
        order_date TIMESTAMP DEFAULT CURRENT_TIMESTAMP,
        payment_date TIMESTAMP NULL,
        total_amount DECIMAL(10, 2) NOT NULL,
        status VARCHAR(20) DEFAULT 'Processing',
        razorpay_order_id VARCHAR(255) NULL,
        razorpay_payment_id VARCHAR(255) NULL,
        shipping_address_id INT NULL,
        FOREIGN KEY (user_id) REFERENCES users(id)
    );
    """
    execute_query(query)

def create_order_items_table():
    query = """
    CREATE TABLE IF NOT EXISTS order_items (
        order_id INT NOT NULL,
        product_id INT NOT NULL,
        quantity INT NOT NULL,
        price_at_purchase DECIMAL(10, 2) NOT NULL,
        PRIMARY KEY (order_id, product_id),
        FOREIGN KEY (order_id) REFERENCES orders(order_id),
        FOREIGN KEY (product_id) REFERENCES products(id)
    );
    """
    execute_query(query)

# Create tables on startup
create_orders_table()
create_order_items_table()

# Pydantic models
class OrderItem(BaseModel):
    product_id: int
    quantity: int

class CreateOrderRequest(BaseModel):
    items: List[OrderItem]
    shipping_address_id: Optional[int] = None

class RazorpayPaymentConfirmation(BaseModel):
    order_id: int
    razorpay_payment_id: str
    razorpay_order_id: str
    razorpay_signature: str

class OrderResponse(BaseModel):
    status: str
    order_id: int
    razorpay_order_id: str
    amount: float
    currency: str
    items: List[dict]
    message: str

class PublicCreateOrderRequest(BaseModel):
    user_id: int
    items: List[OrderItem]
    shipping_address_id: Optional[int] = None

# Authentication functions
async def get_current_user(token: str = Depends(oauth2_scheme)):
    credentials_exception = HTTPException(
        status_code=status.HTTP_401_UNAUTHORIZED,
        detail="Could not validate credentials",
        headers={"WWW-Authenticate": "Bearer"},
    )
    try:
        payload = jwt.decode(token, SECRET_KEY, algorithms=[ALGORITHM])
        user_id: int = int(payload.get("sub"))
        if user_id is None:
            raise credentials_exception
    except (JWTError, ValueError) as e:
        logger.error(f"JWT Error: {str(e)}")
        raise credentials_exception
    
    # Verify user exists in database
    user = execute_query("SELECT id FROM users WHERE id = %s", (user_id,))
    if not user:
        raise credentials_exception
    
    return {"id": user_id}

# Order endpoints
@router.post("/orders/public", response_model=OrderResponse)
async def create_order_public(
    order_request: PublicCreateOrderRequest
):
    connection = None
    cursor = None
    user_id = order_request.user_id

    try:
        logger.info(f"Creating PUBLIC order for user {user_id}")

        # Validate input items
        if not order_request.items:
            raise HTTPException(
                status_code=status.HTTP_400_BAD_REQUEST,
                detail="No items in order"
            )

        # Get product prices and availability
        product_ids = tuple(item.product_id for item in order_request.items)
        placeholders = ','.join(['%s'] * len(product_ids))
        price_query = f"""
            SELECT id, price, name, stock 
            FROM products 
            WHERE id IN ({placeholders}) 
            AND status = 'active'
        """
        products = execute_query(price_query, product_ids)

        # Verify all products exist and are available
        if len(products) != len(product_ids):
            found_ids = {p['id'] for p in products}
            missing = [str(id) for id in product_ids if id not in found_ids]
            raise HTTPException(
                status_code=status.HTTP_404_NOT_FOUND,
                detail=f"Products not found or unavailable: {', '.join(missing)}"
            )

        # Check stock availability
        for item in order_request.items:
            product = next(p for p in products if p['id'] == item.product_id)
            if product['stock'] < item.quantity:
                raise HTTPException(
                    status_code=status.HTTP_400_BAD_REQUEST,
                    detail=f"Not enough stock for product {product['id']}"
                )

        # Calculate total amount
        price_map = {p['id']: float(p['price']) for p in products}
        total_amount = round(sum(
            price_map[item.product_id] * item.quantity 
            for item in order_request.items
        ), 2)

        if total_amount <= 0:
            raise HTTPException(
                status_code=status.HTTP_400_BAD_REQUEST,
                detail="Invalid order total amount"
            )

        # Get database connection
        connection = get_db1()
        if not connection:
            raise HTTPException(
                status_code=status.HTTP_500_INTERNAL_SERVER_ERROR,
                detail="Database connection error"
            )

        cursor = connection.cursor(dictionary=True)
        connection.start_transaction()

        # Get the next user_order_number for this user
        cursor.execute(
            "SELECT COALESCE(MAX(user_order_number), 0) + 1 AS next_order_num "
            "FROM orders WHERE user_id = %s",
            (user_id,)
        )
        next_order_num = cursor.fetchone()['next_order_num']

        # Insert into orders table with user_order_number
        cursor.execute(
            """
            INSERT INTO orders 
            (user_id, total_amount, status, shipping_address_id, user_order_number) 
            VALUES (%s, %s, %s, %s, %s)
            """,
            (user_id, total_amount, 'Created', order_request.shipping_address_id, next_order_num)
        )
        order_id = cursor.lastrowid

        # Insert order items
        order_items = []
        for item in order_request.items:
            cursor.execute(
                """
                INSERT INTO order_items 
                (order_id, product_id, quantity, price_at_purchase) 
                VALUES (%s, %s, %s, %s)
                """,
                (order_id, item.product_id, item.quantity, price_map[item.product_id])
            )
            order_items.append({
                'product_id': item.product_id,
                'quantity': item.quantity,
                'price': price_map[item.product_id],
                'name': next(p['name'] for p in products if p['id'] == item.product_id)
            })

        # Create Razorpay order
        razorpay_order = razorpay_client.order.create({
            'amount': int(total_amount * 100),  # Convert to paise
            'currency': 'INR',
            'receipt': f"order_{order_id}",
            'payment_capture': 1,
            'notes': {
                'order_id': str(order_id),
                'user_id': str(user_id)
            }
        })

        # Update order with Razorpay ID
        cursor.execute(
            """
            UPDATE orders 
            SET razorpay_order_id = %s 
            WHERE order_id = %s
            """,
            (razorpay_order['id'], order_id)
        )

        connection.commit()

        return {
            "status": "success",
            "order_id": order_id,
            "user_order_number": next_order_num,  # Add this line
            "razorpay_order_id": razorpay_order['id'],
            "amount": total_amount,
            "currency": "INR",
            "items": order_items,
            "message": "Order created successfully"
        }

    except razorpay.errors.BadRequestError as e:
        if connection:
            connection.rollback()
        logger.error(f"Razorpay error: {str(e)}")
        raise HTTPException(
            status_code=status.HTTP_400_BAD_REQUEST,
            detail=f"Payment processing error: {str(e)}"
        )
    except Exception as e:
        if connection:
            connection.rollback()
        logger.error(f"Order creation failed: {str(e)}")
        raise HTTPException(
            status_code=status.HTTP_500_INTERNAL_SERVER_ERROR,
            detail="Order creation failed"
        )
    finally:
        if cursor:
            cursor.close()
        if connection and connection.is_connected():
            connection.close()

def migrate_existing_orders():
    connection = get_db1()
    cursor = connection.cursor(dictionary=True)
    
    try:
        # Get all user IDs with orders
        cursor.execute("SELECT DISTINCT user_id FROM orders")
        users = cursor.fetchall()
        
        for user in users:
            user_id = user['user_id']
            
            # Get all orders for this user ordered by creation date
            cursor.execute(
                "SELECT order_id FROM orders WHERE user_id = %s ORDER BY order_date ASC",
                (user_id,)
            )
            orders = cursor.fetchall()
            
            # Update each order with sequential user_order_number
            for index, order in enumerate(orders, start=1):
                cursor.execute(
                    "UPDATE orders SET user_order_number = %s WHERE order_id = %s",
                    (index, order['order_id'])
                )
        
        connection.commit()
        logger.info("Successfully migrated existing orders")
        
    except Exception as e:
        connection.rollback()
        logger.error(f"Migration failed: {str(e)}")
        raise
    finally:
        if cursor:
            cursor.close()
        if connection and connection.is_connected():
            connection.close()

# Run the migration (call this once)
# migrate_existing_orders()
            
@router.get("/orders/user/{user_id}", response_model=List[dict])
async def get_orders_by_user_id(user_id: int):
    try:
        # Verify user exists
        user_exists = execute_query("SELECT id FROM users WHERE id = %s", (user_id,))
        if not user_exists:
            raise HTTPException(
                status_code=status.HTTP_404_NOT_FOUND,
                detail="User not found"
            )
        
        # Include user_order_number in the query
        orders_query = """
        SELECT 
            order_id,
            user_id,
            user_order_number,
            order_date,
            payment_date,
            total_amount,
            status,
            razorpay_order_id,
            razorpay_payment_id,
            shipping_address_id
        FROM orders
        WHERE user_id = %s 
        ORDER BY order_date DESC
        """
        orders = execute_query(orders_query, (user_id,)) or []

        # Get items for each order
        for order in orders:
            items_query = """
            SELECT 
                oi.product_id, 
                oi.quantity, 
                oi.price_at_purchase as price,
                p.name, 
                p.mainImageUrl
            FROM order_items oi
            JOIN products p ON oi.product_id = p.id
            WHERE oi.order_id = %s
            """
            order['items'] = execute_query(items_query, (order['order_id'],)) or []
        
        return orders
        
    except Exception as e:
        logger.error(f"Error fetching orders: {str(e)}", exc_info=True)
        raise HTTPException(
            status_code=status.HTTP_500_INTERNAL_SERVER_ERROR,
            detail="Error fetching orders"
        )
        
@router.get("/verify-token")
async def verify_token(token: str = Depends(oauth2_scheme)):
    try:
        payload = jwt.decode(token, SECRET_KEY, algorithms=[ALGORITHM])
        user_id: int = int(payload.get("sub"))
        if user_id is None:
            raise HTTPException(
                status_code=status.HTTP_401_UNAUTHORIZED,
                detail="Invalid token"
            )
        
        # Verify user exists
        user = execute_query("SELECT id FROM users WHERE id = %s", (user_id,))
        if not user:
            raise HTTPException(
                status_code=status.HTTP_401_UNAUTHORIZED,
                detail="User not found"
            )
        
        return {"user_id": user_id}
    except JWTError as e:
        raise HTTPException(
            status_code=status.HTTP_401_UNAUTHORIZED,
            detail="Invalid token"
        )
    
@router.post("/orders/confirm-razorpay-payment", response_model=dict)
async def confirm_razorpay_payment(
    confirmation: RazorpayPaymentConfirmation,
    current_user: dict = Depends(get_current_user)
):
    connection = None
    cursor = None
    
    try:
        # Verify payment signature
        razorpay_client.utility.verify_payment_signature({
            'razorpay_order_id': confirmation.razorpay_order_id,
            'razorpay_payment_id': confirmation.razorpay_payment_id,
            'razorpay_signature': confirmation.razorpay_signature
        })
        
        # Get database connection
        connection = get_db1()
        if not connection:
            raise HTTPException(
                status_code=status.HTTP_500_INTERNAL_SERVER_ERROR,
                detail="Database connection error"
            )
            
        cursor = connection.cursor(dictionary=True)
        
        # Verify order belongs to the current user
        cursor.execute(
            "SELECT user_id, user_order_number FROM orders WHERE order_id = %s",
            (confirmation.order_id,)
        )
        order = cursor.fetchone()
        
        if not order or order['user_id'] != current_user['id']:
            raise HTTPException(
                status_code=status.HTTP_404_NOT_FOUND,
                detail="Order not found or access denied"
            )
        
        # Update order status
        cursor.execute(
            """
            SELECT order_id, user_order_number, status 
            FROM orders 
            WHERE order_id = %s
            """,
            (confirmation.order_id,)
        )
        updated_order = cursor.fetchone()

        
        connection.commit()
        
        return {
             "status": "success",
             "message": "Payment confirmed and order updated",
             "order": {
                 "order_id": updated_order['order_id'],
                 "user_order_number": updated_order['user_order_number'],
                 "status": updated_order['status'],
                 "razorpay_payment_id": confirmation.razorpay_payment_id
             }
         }
        
    except razorpay.errors.SignatureVerificationError as e:
        if connection:
            connection.rollback()
        logger.error(f"Payment signature verification failed: {str(e)}")
        raise HTTPException(
            status_code=status.HTTP_400_BAD_REQUEST,
            detail="Invalid payment signature"
        )
    except Exception as e:
        if connection:
            connection.rollback()
        logger.error(f"Payment confirmation failed: {str(e)}")
        raise HTTPException(
            status_code=status.HTTP_500_INTERNAL_SERVER_ERROR,
            detail="Payment confirmation failed"
        )
    finally:
        if cursor:
            cursor.close()
        if connection and connection.is_connected():
            connection.close()