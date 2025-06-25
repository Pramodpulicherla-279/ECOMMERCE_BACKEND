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

router = APIRouter()
oauth2_scheme = OAuth2PasswordBearer(tokenUrl="token")

class Token(BaseModel):
    token: str  # Changed from access_token to token
    token_type: str
    expires_in: int
    agent: dict  # Add this field to match your response

class TokenData(BaseModel):
    agent_id: str

def create_access_token(agent_id: str) -> str:
    expires = datetime.utcnow() + timedelta(minutes=ACCESS_TOKEN_EXPIRE_MINUTES)
    payload = {
        "sub": str(agent_id),
        "exp": expires
    }
    return jwt.encode(payload, SECRET_KEY, algorithm=ALGORITHM)

async def get_current_agent(token: str = Depends(oauth2_scheme)):
    credentials_exception = HTTPException(
        status_code=status.HTTP_401_UNAUTHORIZED,
        detail="Could not validate credentials",
        headers={"WWW-Authenticate": "Bearer"},
    )
    try:
        payload = jwt.decode(token, SECRET_KEY, algorithms=[ALGORITHM])
        agent_id: str = payload.get("sub")
        if agent_id is None:
            raise credentials_exception
        
        # Verify token against database
        db = get_db1()
        cursor = db.cursor(dictionary=True)
        cursor.execute(
            "SELECT * FROM agent WHERE id = %s AND token = %s AND token_expiry > %s",
            (agent_id, token, datetime.utcnow())
        )
        agent = cursor.fetchone()
        if not agent:
            raise credentials_exception
            
        return agent
    except JWTError as e:
        raise credentials_exception
    
def store_token_in_db(agent_id: int, token: str):
    db = get_db1()
    cursor = db.cursor()
    try:
        expiry = datetime.utcnow() + timedelta(minutes=ACCESS_TOKEN_EXPIRE_MINUTES)
        cursor.execute(
            "UPDATE agent SET token = %s, token_expiry = %s WHERE id = %s",
            (token, expiry, agent_id)
        )
        db.commit()
    except Exception as e:
        db.rollback()
        raise e
    finally:
        cursor.close()

def invalidate_token(agent_id: int):
    db = get_db1()
    cursor = db.cursor()
    try:
        cursor.execute(
            "UPDATE agent SET token = NULL, token_expiry = NULL WHERE id = %s",
            (agent_id,)
        )
        db.commit()
    except Exception as e:
        db.rollback()
        raise e
    finally:
        cursor.close()

class AgentRegistration(BaseModel):
    name: str
    email: Optional[str] = None
    mobile_number: Optional[str] = None
    password: str
    confirmPassword: str

class AgentLogin(BaseModel):
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

@router.post("/agentregister")
async def register_agent(agent: AgentRegistration):
    # Validate input
    if not agent.email and not agent.mobile_number:
        raise HTTPException(status_code=400, detail="Either email or mobile number is required")
    
    if agent.password != agent.confirmPassword:
        raise HTTPException(status_code=400, detail="Passwords do not match")
    
    # Check if required fields are present based on registration method
    if agent.email and not agent.name:
        raise HTTPException(status_code=400, detail="Name is required for email registration")
    if agent.mobile_number and not agent.name:
        raise HTTPException(status_code=400, detail="Name is required for mobile registration")

    db = get_db1()
    if db is None:
        raise HTTPException(status_code=500, detail="Database connection failed")
    
    cursor = db.cursor(dictionary=True)
    
    try:
        # Check for existing agent
        if agent.email:
            cursor.execute("SELECT * FROM agent WHERE email = %s", (agent.email,))
            if cursor.fetchone():
                raise HTTPException(status_code=400, detail="Email already registered")
        
        if agent.mobile_number:
            formatted_mobile = format_mobile_number(agent.mobile_number)
            cursor.execute("SELECT * FROM agent WHERE mobile_number = %s", (formatted_mobile,))
            if cursor.fetchone():
                raise HTTPException(status_code=400, detail="Mobile number already registered")
        
        # Hash password
        hashed_password = hash_password(agent.password)
        
        # Create agent
        cursor.execute(
            """INSERT INTO agent 
            (name, email, mobile_number, password, created_at, is_verified) 
            VALUES (%s, %s, %s, %s, %s, %s)""",
            (
                agent.name,
                agent.email if agent.email else None,
                format_mobile_number(agent.mobile_number) if agent.mobile_number else None,
                hashed_password,
                datetime.now(),
                True  # Mark as verified since OTP was already verified
            )
        )
        db.commit()
        agent_id = cursor.lastrowid

        # Generate and store token for auto-login
        token = create_access_token(str(agent_id))
        store_token_in_db(agent_id, token)
        
        return {
            "message": "Registration successful",
            "agent_id": agent_id,
            "name": agent.name,
            "email": agent.email,
            "mobile_number": agent.mobile_number,
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


@router.post("/agentlogin", response_model=Token)
async def login_agent(login_data: AgentLogin):
    db = get_db1()
    if db is None:
        raise HTTPException(status_code=500, detail="Database connection failed")
    
    cursor = db.cursor(dictionary=True)
    
    try:
        # Find agent by email or mobile - INCLUDE PASSWORD FIELD
        query = "SELECT id, name, email, mobile_number, password FROM ageent WHERE "
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
        agent = cursor.fetchone()
        
        if not agent:
            raise HTTPException(status_code=401, detail="Invalid credentials")
        
        # Debug log to check what fields we got from DB
        logger.debug(f"Agent data from DB: {agent}")
        
        # Verify password - now password field should exist
        if not verify_password(login_data.password, agent['password']):
            raise HTTPException(status_code=401, detail="Invalid credentials")
        
        # Generate token
        token = create_access_token(str(agent['id']))
        store_token_in_db(agent['id'], token)
        
        # Return response - don't include password in the response!
        return {
            "token": token,
            "token_type": "bearer",
            "expires_in": ACCESS_TOKEN_EXPIRE_MINUTES * 60,
            "agent": {
                "id": agent['id'],
                "name": agent['name'],
                "email": agent['email'],
                "mobile_number": agent['mobile_number']
            }
        }
    except Exception as e:
        logger.error(f"Login error: {str(e)}", exc_info=True)
        raise HTTPException(status_code=500, detail="Login failed")
    finally:
        cursor.close()

@router.post("/agent-send-otp")
async def send_otp(otp_request: SendOTPRequest):
    db = get_db1()
    if db is None:
        raise HTTPException(status_code=500, detail="Database connection failed")
    
    cursor = db.cursor(dictionary=True)
    
    # Generate OTP
    otp = HARDCODED_OTP  # Use hardcoded OTP for testing
    otp_expiry = datetime.now() + timedelta(minutes=5)
    
    try:
        # For new registration, we don't need to check if agent exists
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
    
@router.post("/agent-verify-otp")
async def verify_otp(verify_request: VerifyOTPRequest):
    # For new registrations, we just verify the OTP matches our hardcoded value
    if verify_request.otp != HARDCODED_OTP:
        raise HTTPException(status_code=401, detail="Invalid OTP")
    
    return {
        "message": "OTP verified successfully",
        "verified": True
    }
    
@router.post("/agent-otp-login")
async def otp_login(login_request: OTPLoginRequest):
    db = get_db1()
    if db is None:
        raise HTTPException(status_code=500, detail="Database connection failed")
    
    cursor = db.cursor(dictionary=True)
    
    # Find agent by email or mobile
    if login_request.email:
        cursor.execute("SELECT * FROM agent WHERE email = %s", (login_request.email,))
    elif login_request.mobile_number:
        formatted_mobile = format_mobile_number(login_request.mobile_number)
        cursor.execute("SELECT * FROM agent WHERE mobile_number = %s", (formatted_mobile,))
    else:
        raise HTTPException(status_code=400, detail="Either email or mobile number is required")
    
    agent = cursor.fetchone()
    if not agent:
        raise HTTPException(status_code=404, detail="Agent not found")
    
    # Check OTP
    if not agent['otp_code'] or agent['otp_code'] != login_request.otp:
        raise HTTPException(status_code=401, detail="Invalid OTP")
    
    # Check if OTP is expired
    if agent['otp_created_at'] and agent['otp_created_at'] < datetime.now():
        raise HTTPException(status_code=401, detail="OTP expired")
    
    # Clear OTP after successful verification
    try:
        # Generate and store token
        token = create_access_token(str(agent['id']))
        store_token_in_db(agent['id'], token)

        cursor.execute(
            "UPDATE agent SET otp_code = NULL, otp_created_at = NULL WHERE id = %s",
            (agent['id'],)
        )
        db.commit()
        
        return {
            "message": "Login successful",
            "access_token": token,
            "token_type": "bearer",
            "expires_in": ACCESS_TOKEN_EXPIRE_MINUTES * 60,
            "agent_id": agent['id'],
            "agent_name": agent['name'],
            "email": agent['email'],
            "mobile_number": agent['mobile_number']
        }
    except Exception as e:
        db.rollback()
        logger.error(f"Failed to login with OTP: {str(e)}")
        raise HTTPException(status_code=500, detail="Failed to login with OTP")
    finally:
        cursor.close()
    
@router.post("/logout")
async def logout(current_agent: dict = Depends(get_current_agent)):
    try:
        invalidate_token(current_agent['id'])
        return {"message": "Successfully logged out"}
    except Exception as e:
        logger.error(f"Logout error: {str(e)}")
        raise HTTPException(status_code=500, detail="Logout failed")
