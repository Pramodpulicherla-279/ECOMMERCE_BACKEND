from fastapi import APIRouter, HTTPException, Depends
from pydantic import BaseModel
import razorpay
import os
from dotenv import load_dotenv
from datetime import datetime
from db import get_db1, execute_query  # Assuming you have a db.py with these utilities

load_dotenv()

router = APIRouter()

# Initialize Razorpay client
if not all([os.getenv("RAZORPAY_KEY_ID"), os.getenv("RAZORPAY_KEY_SECRET")]):
    raise RuntimeError("Missing Razorpay credentials in environment variables")

razorpay_client = razorpay.Client(auth=(
    os.getenv("RAZORPAY_KEY_ID"),
    os.getenv("RAZORPAY_KEY_SECRET")
))

class CreateRazorpayOrderRequest(BaseModel):
    amount: int
    currency: str = "INR"
    receipt: str
    order_id: int  # Add order_id to link with your database

class VerifyPaymentRequest(BaseModel):
    razorpay_order_id: str
    razorpay_payment_id: str
    razorpay_signature: str
    order_id: int  # Add order_id to link with your database

@router.post("/create-razorpay-order")
async def create_razorpay_order(request: CreateRazorpayOrderRequest):
    try:
        is_test_mode = os.getenv("ENVIRONMENT", "production") == "development"
        amount = 100 if is_test_mode else request.amount
        
        order_data = {
            'amount': amount,
            'currency': request.currency,
            'receipt': request.receipt,
            'payment_capture': 1,
            'notes': {
                'order_id': str(request.order_id),
                'original_amount': request.amount,
                'is_test_payment': is_test_mode
            }
        }
        
        order = razorpay_client.order.create(data=order_data)
        
        # Update order in database with Razorpay order ID
        execute_query(
            "UPDATE orders SET razorpay_order_id = %s WHERE order_id = %s",
            (order['id'], request.order_id)
        )
        
        return {
            "id": order["id"],
            "amount": order["amount"],
            "currency": order["currency"],
            "key": os.getenv("RAZORPAY_KEY_ID"),
            "is_test_mode": is_test_mode
        }
    except Exception as e:
        print(f"Razorpay order creation failed: {str(e)}")
        raise HTTPException(
            status_code=500,
            detail=f"Payment processing error: {str(e)}"
        )

@router.post("/verify-payment")
async def verify_payment(request: VerifyPaymentRequest):
    connection = None
    cursor = None
    try:
        # 1. Verify payment signature with Razorpay
        params_dict = {
            'razorpay_order_id': request.razorpay_order_id,
            'razorpay_payment_id': request.razorpay_payment_id,
            'razorpay_signature': request.razorpay_signature
        }
        razorpay_client.utility.verify_payment_signature(params_dict)
        
        # 2. Get database connection
        connection = get_db1()
        cursor = connection.cursor(dictionary=True)
        
        # 3. Verify the order exists and matches Razorpay order ID
        cursor.execute(
            "SELECT * FROM orders WHERE order_id = %s AND razorpay_order_id = %s",
            (request.order_id, request.razorpay_order_id)
        )
        order = cursor.fetchone()
        
        if not order:
            raise HTTPException(status_code=404, detail="Order not found or Razorpay order ID mismatch")
        
        # 4. Check if payment is already processed
        if order['status'] == 'Paid':
            return {"status": "success", "message": "Payment already confirmed"}
        
        # 5. Get payment details from Razorpay
        payment = razorpay_client.payment.fetch(request.razorpay_payment_id)
        
        # 6. Verify payment status is captured
        if payment['status'] != 'captured':
            raise HTTPException(status_code=400, detail="Payment not captured yet")
        
        # 7. Update order status in database
        cursor.execute(
            """UPDATE orders 
               SET status = 'Paid', 
                   razorpay_payment_id = %s,
                   payment_date = %s
               WHERE order_id = %s""",
            (request.razorpay_payment_id, datetime.now(), request.order_id)
        )
        
        # 8. Get order items for response
        cursor.execute(
            """SELECT oi.product_id, oi.quantity, p.name, p.price
               FROM order_items oi
               JOIN products p ON oi.product_id = p.id
               WHERE oi.order_id = %s""",
            (request.order_id,)
        )
        items = cursor.fetchall()
        
        connection.commit()
        
        return {
            "status": "success",
            "message": "Payment verified and order updated",
            "order": {
                "order_id": request.order_id,
                "status": "Paid",
                "payment_id": request.razorpay_payment_id,
                "items": items,
                "amount": order['total_amount']
            }
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