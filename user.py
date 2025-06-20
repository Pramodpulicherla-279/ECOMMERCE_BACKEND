from fastapi import APIRouter, HTTPException, Depends, status
from fastapi.security import OAuth2PasswordBearer
from jose import JWTError, jwt
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

# Security configurations
SECRET_KEY = os.getenv("SECRET_KEY", "your-very-secure-secret-key")
ALGORITHM = "HS256"
ACCESS_TOKEN_EXPIRE_MINUTES = 30 * 24 * 60  # 30 days in minutes

# Set up logging
logging.basicConfig(level=logging.DEBUG)
logger = logging.getLogger(__name__)

user_router = APIRouter()
oauth2_scheme = OAuth2PasswordBearer(tokenUrl="token")

class Token(BaseModel):
    token: str  # Changed from access_token to token
    token_type: str
    expires_in: int
    user: dict  # Add this field to match your response

class TokenData(BaseModel):
    user_id: str

def create_access_token(user_id: str) -> str:
    expires = datetime.utcnow() + timedelta(minutes=ACCESS_TOKEN_EXPIRE_MINUTES)
    payload = {
        "sub": str(user_id),
        "exp": expires
    }
    return jwt.encode(payload, SECRET_KEY, algorithm=ALGORITHM)

async def get_current_user(token: str = Depends(oauth2_scheme)):
    credentials_exception = HTTPException(
        status_code=status.HTTP_401_UNAUTHORIZED,
        detail="Could not validate credentials",
        headers={"WWW-Authenticate": "Bearer"},
    )
    try:
        payload = jwt.decode(token, SECRET_KEY, algorithms=[ALGORITHM])
        user_id: str = payload.get("sub")
        if user_id is None:
            raise credentials_exception
        
        # Verify token against database
        db = get_db1()
        cursor = db.cursor(dictionary=True)
        cursor.execute(
            "SELECT * FROM users WHERE id = %s AND token = %s AND token_expiry > %s",
            (user_id, token, datetime.utcnow())
        )
        user = cursor.fetchone()
        if not user:
            raise credentials_exception
            
        return user
    except JWTError as e:
        raise credentials_exception

def store_token_in_db(user_id: int, token: str):
    db = get_db1()
    cursor = db.cursor()
    try:
        expiry = datetime.utcnow() + timedelta(minutes=ACCESS_TOKEN_EXPIRE_MINUTES)
        cursor.execute(
            "UPDATE users SET token = %s, token_expiry = %s WHERE id = %s",
            (token, expiry, user_id)
        )
        db.commit()
    except Exception as e:
        db.rollback()
        raise e
    finally:
        cursor.close()

def invalidate_token(user_id: int):
    db = get_db1()
    cursor = db.cursor()
    try:
        cursor.execute(
            "UPDATE users SET token = NULL, token_expiry = NULL WHERE id = %s",
            (user_id,)
        )
        db.commit()
    except Exception as e:
        db.rollback()
        raise e
    finally:
        cursor.close()

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
    
    # Check if required fields are present based on registration method
    if user.email and not user.name:
        raise HTTPException(status_code=400, detail="Name is required for email registration")
    if user.mobile_number and not user.name:
        raise HTTPException(status_code=400, detail="Name is required for mobile registration")

    db = get_db1()
    if db is None:
        raise HTTPException(status_code=500, detail="Database connection failed")
    
    cursor = db.cursor(dictionary=True)
    
    try:
        # Check for existing user
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
                user.email if user.email else None,
                format_mobile_number(user.mobile_number) if user.mobile_number else None,
                hashed_password,
                datetime.now(),
                True  # Mark as verified since OTP was already verified
            )
        )
        db.commit()
        user_id = cursor.lastrowid

        # Generate and store token for auto-login
        token = create_access_token(str(user_id))
        store_token_in_db(user_id, token)
        
        return {
            "message": "Registration successful",
            "user_id": user_id,
            "name": user.name,
            "email": user.email,
            "mobile_number": user.mobile_number,
            "token": token,
            "token_type": "bearer",
            "expires_in": ACCESS_TOKEN_EXPIRE_MINUTES * 60
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
        
@user_router.post("/login", response_model=Token)
async def login_user(login_data: UserLogin):
    db = get_db1()
    if db is None:
        raise HTTPException(status_code=500, detail="Database connection failed")
    
    cursor = db.cursor(dictionary=True)
    
    try:
        # Find user by email or mobile - INCLUDE PASSWORD FIELD
        query = "SELECT id, name, email, mobile_number, password FROM users WHERE "
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
        
        # Debug log to check what fields we got from DB
        logger.debug(f"User data from DB: {user}")
        
        # Verify password - now password field should exist
        if not verify_password(login_data.password, user['password']):
            raise HTTPException(status_code=401, detail="Invalid credentials")
        
        # Generate token
        token = create_access_token(str(user['id']))
        store_token_in_db(user['id'], token)
        
        # Return response - don't include password in the response!
        return {
            "token": token,
            "token_type": "bearer",
            "expires_in": ACCESS_TOKEN_EXPIRE_MINUTES * 60,
            "user": {
                "id": user['id'],
                "name": user['name'],
                "email": user['email'],
                "mobile_number": user['mobile_number']
            }
        }
    except Exception as e:
        logger.error(f"Login error: {str(e)}", exc_info=True)
        raise HTTPException(status_code=500, detail="Login failed")
    finally:
        cursor.close()

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
        # Generate and store token
        token = create_access_token(str(user['id']))
        store_token_in_db(user['id'], token)

        cursor.execute(
            "UPDATE users SET otp_code = NULL, otp_created_at = NULL WHERE id = %s",
            (user['id'],)
        )
        db.commit()
        
        return {
            "message": "Login successful",
            "access_token": token,
            "token_type": "bearer",
            "expires_in": ACCESS_TOKEN_EXPIRE_MINUTES * 60,
            "user_id": user['id'],
            "user_name": user['name'],
            "email": user['email'],
            "mobile_number": user['mobile_number']
        }
    except Exception as e:
        db.rollback()
        logger.error(f"Failed to login with OTP: {str(e)}")
        raise HTTPException(status_code=500, detail="Failed to login with OTP")
    finally:
        cursor.close()
    
@user_router.post("/logout")
async def logout(current_user: dict = Depends(get_current_user)):
    try:
        invalidate_token(current_user['id'])
        return {"message": "Successfully logged out"}
    except Exception as e:
        logger.error(f"Logout error: {str(e)}")
        raise HTTPException(status_code=500, detail="Logout failed")
    
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