from fastapi import APIRouter, HTTPException, Depends
from pydantic import BaseModel
import random
import string
import mysql.connector
from datetime import datetime, timedelta
import logging
from typing import Optional
import bcrypt


# Router
router = APIRouter()

# Set up logging
logging.basicConfig(level=logging.DEBUG)
logger = logging.getLogger(__name__)

# Database connection function (you'll need to implement this)
def get_db():
    try:
        db = mysql.connector.connect(
            host="your_host",
            user="your_user",
            password="your_password",
            database="your_database"
        )
        return db
    except Exception as e:
        logger.error(f"Database connection failed: {str(e)}")
        return None

# Pydantic models
class UserRegistration(BaseModel):
    user_name: str
    email: Optional[str] = None
    mobile_number: Optional[str] = None
    password: str
    confirmPassword: str

class UserLogin(BaseModel):
    email: Optional[str] = None
    mobile_number: Optional[str] = None
    password: str

class SendOTPRequest(BaseModel):
    email: Optional[str] = None
    mobile_number: Optional[str] = None

class VerifyOTPRequest(BaseModel):
    email: Optional[str] = None
    mobile_number: Optional[str] = None
    otp: str

class OTPLoginRequest(BaseModel):
    email: Optional[str] = None
    mobile_number: Optional[str] = None
    otp: str



# Helper functions
def generate_otp():
    return ''.join(random.choices(string.digits, k=4))

def hash_password(password: str):
    return bcrypt.hashpw(password.encode('utf-8'), bcrypt.gensalt()).decode('utf-8')

def verify_password(plain_password: str, hashed_password: str):
    return bcrypt.checkpw(plain_password.encode('utf-8'), hashed_password.encode('utf-8'))

def format_mobile_number(mobile_number: str):
    if not mobile_number.startswith("+91"):
        return f"+91{mobile_number}"
    return mobile_number

# Endpoints
@router.post("/register")
async def register_user(user: UserRegistration):
    # Validate input
    if not user.email and not user.mobile_number:
        raise HTTPException(status_code=400, detail="Either email or mobile number is required")
    
    if user.password != user.confirmPassword:
        raise HTTPException(status_code=400, detail="Passwords do not match")
    
    # Check if user already exists
    db = get_db()
    if db is None:
        raise HTTPException(status_code=500, detail="Database connection failed")
    
    cursor = db.cursor(dictionary=True)
    
    if user.email:
        cursor.execute("SELECT * FROM users WHERE email = %s", (user.email,))
        if cursor.fetchone():
            raise HTTPException(status_code=400, detail="Email already registered")
    
    if user.mobile_number:
        formatted_mobile = format_mobile_number(user.mobile_number)
        cursor.execute("SELECT * FROM users WHERE mobile_number = %s", (formatted_mobile,))
        if cursor.fetchone():
            raise HTTPException(status_code=400, detail="Mobile number already registered")
    
    # Hash password
    hashed_password = hash_password(user.password)
    
    # Create user
    try:
        cursor.execute(
            """INSERT INTO users 
            (name, email, mobile_number, password, created_at) 
            VALUES (%s, %s, %s, %s, %s)""",
            (
                user.user_name,
                user.email,
                format_mobile_number(user.mobile_number) if user.mobile_number else None,
                hashed_password,
                datetime.now()
            )
        )
        db.commit()
        user_id = cursor.lastrowid
        
        # Generate and store OTP
        otp = generate_otp()
        otp_expiry = datetime.now() + timedelta(minutes=5)
        
        cursor.execute(
            "UPDATE users SET otp_code = %s, otp_created_at = %s WHERE id = %s",
            (otp, otp_expiry, user_id)
        )
        db.commit()
        
        # In a real application, you would send the OTP via email/SMS here
        logger.debug(f"OTP for user {user_id}: {otp}")
        
        return {
            "message": "Registration successful. Please verify your account with the OTP.",
            "user_id": user_id,
            "verification_method": "email" if user.email else "mobile"
        }
    except Exception as e:
        db.rollback()
        logger.error(f"Registration failed: {str(e)}")
        raise HTTPException(status_code=500, detail="Registration failed")

@router.post("/login")
async def login_user(login_data: UserLogin):
    db = get_db()
    if db is None:
        raise HTTPException(status_code=500, detail="Database connection failed")
    
    cursor = db.cursor(dictionary=True)
    
    # Find user by email or mobile
    if login_data.email:
        cursor.execute("SELECT * FROM users WHERE email = %s", (login_data.email,))
    elif login_data.mobile_number:
        formatted_mobile = format_mobile_number(login_data.mobile_number)
        cursor.execute("SELECT * FROM users WHERE mobile_number = %s", (formatted_mobile,))
    else:
        raise HTTPException(status_code=400, detail="Either email or mobile number is required")
    
    user = cursor.fetchone()
    if not user:
        raise HTTPException(status_code=401, detail="Invalid credentials")
    
    # Verify password
    if not verify_password(login_data.password, user['password']):
        raise HTTPException(status_code=401, detail="Invalid credentials")
    
    # Check if account is verified (you might want to skip this if you don't require OTP verification)
    if user['otp_code'] is not None:
        raise HTTPException(status_code=403, detail="Account not verified. Please verify with OTP first.")
    
    return {
        "message": "Login successful",
        "user_id": user['id'],
        "user_name": user['name'],
        "email": user['email'],
        "mobile_number": user['mobile_number']
    }

@router.post("/send-otp")
async def send_otp(otp_request: SendOTPRequest):
    db = get_db()
    if db is None:
        raise HTTPException(status_code=500, detail="Database connection failed")
    
    cursor = db.cursor(dictionary=True)
    
    # Find user by email or mobile
    if otp_request.email:
        cursor.execute("SELECT * FROM users WHERE email = %s", (otp_request.email,))
    elif otp_request.mobile_number:
        formatted_mobile = format_mobile_number(otp_request.mobile_number)
        cursor.execute("SELECT * FROM users WHERE mobile_number = %s", (formatted_mobile,))
    else:
        raise HTTPException(status_code=400, detail="Either email or mobile number is required")
    
    user = cursor.fetchone()
    if not user:
        raise HTTPException(status_code=404, detail="User not found")
    
    # Generate OTP
    otp = generate_otp()
    otp_expiry = datetime.now() + timedelta(minutes=5)
    
    try:
        cursor.execute(
            "UPDATE users SET otp_code = %s, otp_created_at = %s WHERE id = %s",
            (otp, otp_expiry, user['id'])
        )
        db.commit()
        
        # In a real application, you would send the OTP via email/SMS here
        logger.debug(f"OTP for user {user['id']}: {otp}")
        
        return {
            "message": "OTP sent successfully",
            "user_id": user['id'],
            "verification_method": "email" if otp_request.email else "mobile"
        }
    except Exception as e:
        db.rollback()
        logger.error(f"Failed to send OTP: {str(e)}")
        raise HTTPException(status_code=500, detail="Failed to send OTP")

@router.post("/verify-otp")
async def verify_otp(verify_request: VerifyOTPRequest):
    db = get_db()
    if db is None:
        raise HTTPException(status_code=500, detail="Database connection failed")
    
    cursor = db.cursor(dictionary=True)
    
    # Find user by email or mobile
    if verify_request.email:
        cursor.execute("SELECT * FROM users WHERE email = %s", (verify_request.email,))
    elif verify_request.mobile_number:
        formatted_mobile = format_mobile_number(verify_request.mobile_number)
        cursor.execute("SELECT * FROM users WHERE mobile_number = %s", (formatted_mobile,))
    else:
        raise HTTPException(status_code=400, detail="Either email or mobile number is required")
    
    user = cursor.fetchone()
    if not user:
        raise HTTPException(status_code=404, detail="User not found")
    
    # Check OTP
    if not user['otp_code'] or user['otp_code'] != verify_request.otp:
        raise HTTPException(status_code=401, detail="Invalid OTP")
    
    # Check if OTP is expired
    if user['otp_created_at'] and user['otp_created_at'] < datetime.now():
        raise HTTPException(status_code=401, detail="OTP expired")
    
    # Clear OTP after successful verification
    try:
        cursor.execute(
            "UPDATE users SET otp_code = NULL, otp_created_at = NULL WHERE id = %s",
            (user['id'],)
        )
        db.commit()
        
        return {
            "message": "OTP verified successfully",
            "user_id": user['id'],
            "verified": True
        }
    except Exception as e:
        db.rollback()
        logger.error(f"Failed to verify OTP: {str(e)}")
        raise HTTPException(status_code=500, detail="Failed to verify OTP")

@router.post("/otp-login")
async def otp_login(login_request: OTPLoginRequest):
    db = get_db()
    if db is None:
        raise HTTPException(status_code=500, detail="Database connection failed")
    
    cursor = db.cursor(dictionary=True)
    
    # Find user by email or mobile
    if login_request.email:
        cursor.execute("SELECT * FROM users WHERE email = %s", (login_request.email,))
    elif login_request.mobile_number:
        formatted_mobile = format_mobile_number(login_request.mobile_number)
        cursor.execute("SELECT * FROM users WHERE mobile_number = %s", (formatted_mobile,))
    else:
        raise HTTPException(status_code=400, detail="Either email or mobile number is required")
    
    user = cursor.fetchone()
    if not user:
        raise HTTPException(status_code=404, detail="User not found")
    
    # Check OTP
    if not user['otp_code'] or user['otp_code'] != login_request.otp:
        raise HTTPException(status_code=401, detail="Invalid OTP")
    
    # Check if OTP is expired
    if user['otp_created_at'] and user['otp_created_at'] < datetime.now():
        raise HTTPException(status_code=401, detail="OTP expired")
    
    # Clear OTP after successful verification
    try:
        cursor.execute(
            "UPDATE users SET otp_code = NULL, otp_created_at = NULL WHERE id = %s",
            (user['id'],)
        )
        db.commit()
        
        return {
            "message": "Login successful",
            "user_id": user['id'],
            "user_name": user['name'],
            "email": user['email'],
            "mobile_number": user['mobile_number']
        }
    except Exception as e:
        db.rollback()
        logger.error(f"Failed to login with OTP: {str(e)}")
        raise HTTPException(status_code=500, detail="Failed to login with OTP")