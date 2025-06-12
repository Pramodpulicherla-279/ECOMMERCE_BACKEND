from fastapi import APIRouter, HTTPException
from db import get_db1
from pydantic import BaseModel
import random
import string
import mysql.connector
import boto3
import os
from dotenv import load_dotenv
from datetime import datetime, timedelta
import logging
from typing import Optional
import bcrypt

logging.basicConfig(level=logging.DEBUG)

load_dotenv()

# Set up logging
logging.basicConfig(level=logging.DEBUG)
logger = logging.getLogger(__name__)

class UserRegistration(BaseModel):
    name: str
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

user_router = APIRouter()

# Add this constant at the top of your file
HARDCODED_OTP = "1234"  # For testing purposes

def generate_otp():
    return ''.join(random.choices(string.digits, k=4))

def format_mobile_number(mobile_number: str):
    if not mobile_number.startswith("+91"):
        return f"+91{mobile_number}"
    return mobile_number

def verify_password(plain_password: str, hashed_password: str):
    return bcrypt.checkpw(plain_password.encode('utf-8'), hashed_password.encode('utf-8'))


def hash_password(password: str):
    return bcrypt.hashpw(password.encode('utf-8'), bcrypt.gensalt()).decode('utf-8')




@user_router.post("/userregister")
async def register_user(user: UserRegistration):
    # Validate input
    if not user.email and not user.mobile_number:
        raise HTTPException(status_code=400, detail="Either email or mobile number is required")
    
    if user.password != user.confirmPassword:
        raise HTTPException(status_code=400, detail="Passwords do not match")
    
    # Check if user already exists
    db = get_db1()
    if db is None:
        raise HTTPException(status_code=500, detail="Database connection failed")
    
    cursor = db.cursor(dictionary=True)
    
    try:
        # Check for existing user only if the field is provided
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
        cursor.execute(
            """INSERT INTO users 
            (name, email, mobile_number, password, created_at, is_verified) 
            VALUES (%s, %s, %s, %s, %s, %s)""",
            (
                user.name,
                user.email,
                format_mobile_number(user.mobile_number) if user.mobile_number else None,
                hashed_password,
                datetime.now(),
                True  # Mark as verified since OTP was already verified
            )
        )
        db.commit()
        user_id = cursor.lastrowid
        
        return {
            "message": "Registration successful",
            "user_id": user_id,
            "name": user.name,
            "email": user.email,
            "mobile_number": user.mobile_number
        }
    except mysql.connector.Error as err:
        db.rollback()
        logger.error(f"Database error during registration: {str(err)}")
        raise HTTPException(status_code=500, detail="Registration failed due to database error")
    except HTTPException:
        # Re-raise HTTP exceptions we created
        raise
    except Exception as e:
        db.rollback()
        logger.error(f"Unexpected error during registration: {str(e)}")
        raise HTTPException(status_code=500, detail="Registration failed due to unexpected error")
        
@user_router.post("/login")
async def login_user(login_data: UserLogin):
    db = get_db1()
    if db is None:
        raise HTTPException(status_code=500, detail="Database connection failed")
    
    cursor = db.cursor(dictionary=True)
    
    try:
        # Find user by email or mobile
        query = "SELECT * FROM users WHERE "
        params = []
        
        if login_data.email:
            query += "email = %s"
            params.append(login_data.email)
        elif login_data.mobile_number:
            formatted_mobile = format_mobile_number(login_data.mobile_number)
            query += "mobile_number = %s"
            params.append(formatted_mobile)
        else:
            raise HTTPException(status_code=400, detail="Either email or mobile number is required")
        
        cursor.execute(query, params)
        user = cursor.fetchone()
        
        if not user:
            raise HTTPException(status_code=401, detail="Invalid credentials")
        
        if not verify_password(login_data.password, user['password']):
            raise HTTPException(status_code=401, detail="Invalid credentials")
        
        # Return comprehensive user data
        user_data = {
            "id": user['id'],
            "name": user['name'],
            "email": user['email'],
            "mobile_number": user['mobile_number'],
            "created_at": user['created_at'].isoformat() if user['created_at'] else None,
            "is_verified": bool(user['is_verified'])
        }
        
        return {
            "message": "Login successful",
            "user": user_data,
            "token": "your_jwt_token_here"  # Add if using JWT
        }
        
    except Exception as e:
        logger.error(f"Login error: {str(e)}")
        raise HTTPException(status_code=500, detail="Login failed")
        
@user_router.post("/send-otp")
async def send_otp(otp_request: SendOTPRequest):
    db = get_db1()
    if db is None:
        raise HTTPException(status_code=500, detail="Database connection failed")
    
    cursor = db.cursor(dictionary=True)
    
    # Generate OTP
    otp = HARDCODED_OTP  # Use hardcoded OTP for testing
    otp_expiry = datetime.now() + timedelta(minutes=5)
    
    try:
        # For new registration, we don't need to check if user exists
        # Just generate and return OTP
        logger.debug(f"OTP generated: {otp}")
        
        return {
            "message": "OTP sent successfully",
            "otp": otp,  # For testing purposes, return the OTP
            "verification_method": "email" if otp_request.email else "mobile"
        }
    except Exception as e:
        logger.error(f"Failed to send OTP: {str(e)}")
        raise HTTPException(status_code=500, detail="Failed to send OTP")
    
@user_router.post("/verify-otp")
async def verify_otp(verify_request: VerifyOTPRequest):
    # For new registrations, we just verify the OTP matches our hardcoded value
    if verify_request.otp != HARDCODED_OTP:
        raise HTTPException(status_code=401, detail="Invalid OTP")
    
    return {
        "message": "OTP verified successfully",
        "verified": True
    }
    
@user_router.post("/otp-login")
async def otp_login(login_request: OTPLoginRequest):
    db = get_db1()
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
    
@user_router.get("/user/{user_id}")
async def get_user_details(user_id: int):
    db = get_db1()
    if db is None:
        raise HTTPException(status_code=500, detail="Database connection failed")
    cursor = db.cursor(dictionary=True)
    try:
        cursor.execute("SELECT id, name, email, mobile_number, created_at, is_verified FROM users WHERE id = %s", (user_id,))
        user = cursor.fetchone()
        if not user:
            raise HTTPException(status_code=404, detail="User not found")
        user['created_at'] = user['created_at'].isoformat() if user['created_at'] else None
        user['is_verified'] = bool(user['is_verified'])
        return user
    except Exception as e:
        logger.error(f"Error fetching user details: {str(e)}")
        raise HTTPException(status_code=500, detail="Failed to fetch user details")