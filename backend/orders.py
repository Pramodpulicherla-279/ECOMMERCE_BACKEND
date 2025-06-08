from fastapi import APIRouter, HTTPException, Depends
from pydantic import BaseModel
from typing import List
from db import execute_query, get_db1
import razorpay
from payments import razorpay_client  # Import the Razorpay client
import os
import json
from dotenv import load_dotenv

load_dotenv()

router = APIRouter()

# Table creation (keep existing)
def create_orders_table():
    query = """
    CREATE TABLE IF NOT EXISTS orders (
        order_id INT AUTO_INCREMENT PRIMARY KEY,
        user_id INT NOT NULL,
        order_date TIMESTAMP DEFAULT CURRENT_TIMESTAMP,
        total_amount DECIMAL(10, 2) NOT NULL,
        status VARCHAR(20) DEFAULT 'Processing',
        razorpay_order_id VARCHAR(255) NULL
    );
    """
    execute_query(query)

def create_order_items_table():
    query = """
    CREATE TABLE IF NOT EXISTS order_items (
        order_id INT NOT NULL,
        product_id INT NOT NULL,
        quantity INT NOT NULL,
        PRIMARY KEY (order_id, product_id),
        FOREIGN KEY (order_id) REFERENCES orders(order_id),
        FOREIGN KEY (product_id) REFERENCES products(id)
    );
    """
    execute_query(query)

create_orders_table()
create_order_items_table()

# Pydantic models
class OrderItem(BaseModel):
    product_id: int
    quantity: int

class CreateOrderRequest(BaseModel):
    user_id: int
    items: List[OrderItem]

class RazorpayPaymentConfirmation(BaseModel):
    order_id: int
    razorpay_payment_id: str
    razorpay_order_id: str
    razorpay_signature: str

@router.post("/orders", response_model=dict)
async def create_order(order: CreateOrderRequest):
    connection = None
    cursor = None
    try:
        # Validate input items
        if not order.items:
            raise HTTPException(status_code=400, detail="No items in order")
        
        # Get product prices from database
        product_ids = tuple(item.product_id for item in order.items)
        placeholders = ','.join(['%s'] * len(product_ids))
        price_query = f"""
            SELECT id, price, name 
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
                status_code=404, 
                detail=f"Products not found or unavailable: {', '.join(missing)}"
            )
        
        # Create price mapping and calculate total
        price_map = {p['id']: float(p['price']) for p in products}
        total_amount = round(sum(
            price_map[item.product_id] * item.quantity 
            for item in order.items
        ), 2)

        # Validate total amount
        if total_amount <= 0:
            raise HTTPException(
                status_code=400, 
                detail="Invalid order total amount"
            )

        # Get database connection
        connection = get_db1()
        if not connection:
            raise HTTPException(
                status_code=500, 
                detail="Database connection error"
            )
            
        cursor = connection.cursor(dictionary=True)
        
        # Start transaction
        connection.start_transaction()
        
        # Insert into orders table
        cursor.execute(
            """
            INSERT INTO orders 
            (user_id, total_amount, status) 
            VALUES (%s, %s, %s)
            """,
            (order.user_id, total_amount, 'Created')
        )
        order_id = cursor.lastrowid

        # Insert order items
        order_items = []
        for item in order.items:
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
                'price': price_map[item.product_id]
            })

        # Create Razorpay order
        razorpay_order = razorpay_client.order.create({
            'amount': int(total_amount * 100),  # Convert to paise
            'currency': 'INR',
            'receipt': f"order_{order_id}",
            'payment_capture': 1,
            'notes': {
                'order_id': str(order_id),
                'user_id': str(order.user_id)
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
        
        # Commit transaction
        connection.commit()
        
        return {
            "status": "success",
            "order_id": order_id,
            "razorpay_order_id": razorpay_order['id'],
            "amount": total_amount,
            "currency": "INR",
            "items": order_items,
            "message": "Order created successfully"
        }

    except razorpay.errors.BadRequestError as e:
        if connection:
            connection.rollback()
        raise HTTPException(
            status_code=400,
            detail=f"Razorpay error: {str(e)}"
        )
    except Exception as e:
        if connection:
            connection.rollback()
        raise HTTPException(
            status_code=500,
            detail=f"Order creation failed: {str(e)}"
        )
    finally:
        if cursor:
            cursor.close()
        if connection and connection.is_connected():
            connection.close()

@router.get("/orders")
async def get_user_orders(user_id: int):
    # Get all orders for the user
    orders_query = """
    SELECT * FROM orders WHERE user_id = %s ORDER BY order_date DESC
    """
    orders = execute_query(orders_query, (user_id,))
    if not orders:
        return []

    # For each order, get its items and product details
    for order in orders:
        items_query = """
        SELECT oi.product_id, oi.quantity, p.name, p.price, p.mainImageUrl
        FROM order_items oi
        JOIN products p ON oi.product_id = p.id
        WHERE oi.order_id = %s
        """
        items = execute_query(items_query, (order['order_id'],))
        order['items'] = items
    return orders


@router.post("/orders/confirm-razorpay-payment")
async def confirm_razorpay_payment(confirmation: RazorpayPaymentConfirmation):
    connection = None
    cursor = None
    try:
        # 1. Verify payment signature
        params_dict = {
            'razorpay_order_id': confirmation.razorpay_order_id,
            'razorpay_payment_id': confirmation.razorpay_payment_id,
            'razorpay_signature': confirmation.razorpay_signature
        }
        razorpay_client.utility.verify_payment_signature(params_dict)

        # 2. Get database connection
        connection = get_db1()
        if not connection:
            raise HTTPException(status_code=500, detail="Database connection error")
        cursor = connection.cursor(dictionary=True)

        # 3. Verify and fetch order details
        cursor.execute(
            """SELECT o.*, 
                  (SELECT JSON_ARRAYAGG(
                      JSON_OBJECT(
                        'product_id', oi.product_id,
                        'quantity', oi.quantity,
                        'name', p.name,
                        'price', p.price,
                        'image', p.mainImageUrl
                      )
                  ) 
                  FROM order_items oi
                  JOIN products p ON oi.product_id = p.id
                  WHERE oi.order_id = o.order_id
                  ) AS items
               FROM orders o 
               WHERE order_id = %s AND razorpay_order_id = %s""",
            (confirmation.order_id, confirmation.razorpay_order_id)
        )
        order = cursor.fetchone()

        if not order:
            raise HTTPException(status_code=404, detail="Order not found or Razorpay order ID mismatch")

        # 4. Update order status
        cursor.execute(
            """UPDATE orders 
               SET status = 'Paid', 
                   razorpay_payment_id = %s,
                   payment_date = CURRENT_TIMESTAMP
               WHERE order_id = %s""",
            (confirmation.razorpay_payment_id, confirmation.order_id)
        )

        connection.commit()

        # Convert JSON string to dict if needed
        if isinstance(order['items'], str):
            order['items'] = json.loads(order['items'])

        return {
            "status": "success",
            "message": "Payment confirmed and order updated",
            "order": order
        }

    except razorpay.errors.SignatureVerificationError as e:
        if connection:
            connection.rollback()
        raise HTTPException(status_code=400, detail="Invalid payment signature")
    except Exception as e:
        if connection:
            connection.rollback()
        raise HTTPException(status_code=500, detail=str(e))
    finally:
        if cursor:
            cursor.close()
        if connection:
            connection.close()