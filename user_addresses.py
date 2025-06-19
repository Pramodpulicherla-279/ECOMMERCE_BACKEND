from fastapi import APIRouter, HTTPException, Depends, status, Query
from pydantic import BaseModel
from typing import Optional, List
from db import get_db1

router = APIRouter()

class UserAddresses(BaseModel):
    user_id: int
    full_name: str
    mobile_number: Optional[str] = None
    pincode: str
    line1: str
    # line2: Optional[str] = None
    landmark: Optional[str] = None
    city: str
    state: str
    country: str = "India"
    is_default: Optional[bool] = False
    lat: Optional[float] = None
    lon: Optional[float] = None

@router.post("/user/addresses", response_model=UserAddresses)
async def add_user_address(address: UserAddresses):
    """
    Add a new address for the user.
    """
    db = get_db1()
    if db is None:
        raise HTTPException(status_code=500, detail="Database connection failed")
    
    cursor = db.cursor(dictionary=True)

    try:
        # If is_default is True, unset previous defaults for this user
        if address.is_default:
            cursor.execute(
                "UPDATE user_addresses SET is_default=0 WHERE user_id=%s", (address.user_id,)
            )

        cursor.execute("""
            INSERT INTO user_addresses 
            (user_id, full_name, mobile_number, pincode, line1, landmark, city, state, country, is_default, lat, lon)
            VALUES (%s, %s, %s, %s, %s, %s, %s, %s, %s, %s, %s, %s)
        """, (
            address.user_id, address.full_name, address.mobile_number, address.pincode,
            address.line1, address.landmark, address.city, address.state,
            address.country, int(address.is_default), address.lat, address.lon
        ))
        db.commit()

        cursor.execute("SELECT * FROM user_addresses WHERE id = LAST_INSERT_ID()")
        new_address = cursor.fetchone()

        return new_address
    except Exception as e:
        db.rollback()
        raise HTTPException(status_code=500, detail=f"Error adding address: {str(e)}")
    
@router.get("/user/addresses/{user_id}", response_model=List[UserAddresses])
async def get_user_addresses(user_id: int):
    """
    Get all addresses for a user.
    """
    db = get_db1()
    if db is None:
        raise HTTPException(status_code=500, detail="Database connection failed")
    
    cursor = db.cursor(dictionary=True)
    try:
        cursor.execute("SELECT * FROM user_addresses WHERE user_id = %s", (user_id,))
        addresses = cursor.fetchall()
        return addresses
    except Exception as e:
        raise HTTPException(status_code=500, detail=f"Error fetching addresses: {str(e)}")
    
