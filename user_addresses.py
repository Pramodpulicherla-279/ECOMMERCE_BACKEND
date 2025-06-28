from fastapi import APIRouter, HTTPException, Depends, status, Query
from pydantic import BaseModel
from typing import Optional, List
from db import get_db1

router = APIRouter()

class UserAddresses(BaseModel):
    id: int  
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

class CreateAddress(BaseModel):
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

class SetDefaultAddressRequest(BaseModel):
    address_id: int

@router.post("/user/addresses", response_model=CreateAddress)
async def add_user_address(address: CreateAddress):
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
    
@router.put("/addresses/set-default")
async def set_default_address(payload: SetDefaultAddressRequest):
    """
    Set a specific address as default using only address_id.
    """
    db = get_db1()
    if db is None:
        raise HTTPException(status_code=500, detail="Database connection failed")
    cursor = db.cursor(dictionary=True)
    try:
        # Get user_id for the address
        cursor.execute("SELECT user_id FROM user_addresses WHERE id=%s", (payload.address_id,))
        result = cursor.fetchone()
        if not result:
            raise HTTPException(status_code=404, detail="Address not found")
        user_id = result['user_id']

        # Unset all previous defaults for this user
        cursor.execute("UPDATE user_addresses SET is_default=0 WHERE user_id=%s", (user_id,))
        # Set the selected address as default
        cursor.execute("UPDATE user_addresses SET is_default=1 WHERE id=%s", (payload.address_id,))
        db.commit()
        return {"success": True}
    except Exception as e:
        db.rollback()
        raise HTTPException(status_code=500, detail=f"Error setting default address: {str(e)}")
    
@router.delete("/user/addresses/{address_id}")
async def delete_user_address(address_id: int):
    """
    Delete a user address by its ID.
    """
    db = get_db1()
    if db is None:
        raise HTTPException(status_code=500, detail="Database connection failed")
    cursor = db.cursor(dictionary=True)
    try:
        cursor.execute("SELECT * FROM user_addresses WHERE id=%s", (address_id,))
        address = cursor.fetchone()
        if not address:
            raise HTTPException(status_code=404, detail="Address not found")
        cursor.execute("DELETE FROM user_addresses WHERE id=%s", (address_id,))
        db.commit()
        return {"success": True, "message": "Address deleted"}
    except Exception as e:
        db.rollback()
        raise HTTPException(status_code=500, detail=f"Error deleting address: {str(e)}")

@router.put("/user/addresses/{address_id}", response_model=UserAddresses)
async def update_user_address(address_id: int, address: CreateAddress):
    """
    Update a user address by its ID.
    """
    db = get_db1()
    if db is None:
        raise HTTPException(status_code=500, detail="Database connection failed")
    cursor = db.cursor(dictionary=True)
    try:
        cursor.execute("SELECT * FROM user_addresses WHERE id=%s", (address_id,))
        existing = cursor.fetchone()
        if not existing:
            raise HTTPException(status_code=404, detail="Address not found")
        # If is_default is True, unset previous defaults for this user
        if address.is_default:
            cursor.execute(
                "UPDATE user_addresses SET is_default=0 WHERE user_id=%s", (address.user_id,)
            )
        cursor.execute("""
            UPDATE user_addresses SET
                full_name=%s,
                mobile_number=%s,
                pincode=%s,
                line1=%s,
                landmark=%s,
                city=%s,
                state=%s,
                country=%s,
                is_default=%s,
                lat=%s,
                lon=%s
            WHERE id=%s
        """, (
            address.full_name, address.mobile_number, address.pincode,
            address.line1, address.landmark, address.city, address.state,
            address.country, int(address.is_default), address.lat, address.lon,
            address_id
        ))
        db.commit()
        cursor.execute("SELECT * FROM user_addresses WHERE id=%s", (address_id,))
        updated = cursor.fetchone()
        return updated
    except Exception as e:
        db.rollback()
        raise HTTPException(status_code=500, detail=f"Error updating address: {str(e)}")
    
@router.get("/addresses/{address_id}", response_model=UserAddresses)
async def get_address(address_id: int):
    """
    Get a specific address by its ID.
    """
    db = get_db1()
    if db is None:
        raise HTTPException(status_code=500, detail="Database connection failed")
    
    cursor = db.cursor(dictionary=True)
    try:
        cursor.execute("SELECT * FROM user_addresses WHERE id = %s", (address_id,))
        address = cursor.fetchone()
        if not address:
            raise HTTPException(status_code=404, detail="Address not found")
        return address
    except Exception as e:
        raise HTTPException(status_code=500, detail=f"Error fetching address: {str(e)}")