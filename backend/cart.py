from fastapi import APIRouter, HTTPException
from pydantic import BaseModel
from db import execute_query

router = APIRouter()

# Add this function to create the cart table
def create_cart_table():
    create_table_query = """
    CREATE TABLE IF NOT EXISTS cart (
        user_id INT NOT NULL,
        id INT NOT NULL,
        quantity INT NOT NULL,
        PRIMARY KEY (user_id, id)
    );
    """
    execute_query(create_table_query)

# Call the function to create the cart table
create_cart_table()

class CartItem(BaseModel):
    user_id: int
    id: int
    quantity: int

@router.post("/cart")
async def add_to_cart(item: CartItem):
    # Check if the product exists in the products table
    product_query = "SELECT * FROM products WHERE id = %s"
    product_result = execute_query(product_query, (item.id,))
    if not product_result:
        raise HTTPException(status_code=404, detail="Product not found")
    
    # Insert the item into the cart table
    query = """
        INSERT INTO cart (user_id, id, quantity)
        VALUES (%s, %s, %s)
    """
    params = (item.user_id, item.id, item.quantity)
    execute_query(query, params)
    return {"message": "Item added to cart"}

@router.get("/cart/{user_id}")
async def get_cart(user_id: int):
    query = "SELECT * FROM cart WHERE user_id = %s"
    result = execute_query(query, (user_id,))
    if not result:
        raise HTTPException(status_code=404, detail="Cart is empty")
    return result