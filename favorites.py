from fastapi import APIRouter, HTTPException
from pydantic import BaseModel
from db import execute_query

router = APIRouter()

class FavoriteItem(BaseModel):
    user_id: int
    product_id: int

@router.post("/favorites")
async def add_to_favorites(item: FavoriteItem):
    query = """
        INSERT INTO favorites (user_id, product_id)
        VALUES (%s, %s)
    """
    params = (item.user_id, item.product_id)
    execute_query(query, params)
    return {"message": "Item added to favorites"}

@router.get("/favorites/{user_id}")
async def get_favorites(user_id: int):
    query = "SELECT * FROM favorites WHERE user_id = %s"
    result = execute_query(query, (user_id,))
    if not result:
        raise HTTPException(status_code=404, detail="No favorites found")
    return result