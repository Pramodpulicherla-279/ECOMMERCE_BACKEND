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

class CartItemUpdate(BaseModel):
    quantity: int

@router.post("/cart")
async def add_to_cart(item: CartItem):
    # Check if the product exists in the products table
    product_query = "SELECT * FROM products WHERE id = %s"
    product_result = execute_query(product_query, (item.id,))
    if not product_result:
        raise HTTPException(status_code=404, detail="Product not found")
    
    # Check if the product already exists in the user's cart
    check_query = "SELECT * FROM cart WHERE user_id = %s AND id = %s"
    existing_item = execute_query(check_query, (item.user_id, item.id))
    
    if existing_item:
        # If item exists, update the quantity
        update_query = """
            UPDATE cart 
            SET quantity = quantity + %s
            WHERE user_id = %s AND id = %s
        """
        update_params = (item.quantity, item.user_id, item.id)
        execute_query(update_query, update_params)
        return {"message": "Item quantity updated in cart"}
    else:
        # If item doesn't exist, insert new record
        insert_query = """
            INSERT INTO cart (user_id, id, quantity)
            VALUES (%s, %s, %s)
        """
        insert_params = (item.user_id, item.id, item.quantity)
        execute_query(insert_query, insert_params)
        return {"message": "Item added to cart"}
    
@router.get("/cart/{user_id}")
async def get_cart(user_id: int):
    query = "SELECT * FROM cart WHERE user_id = %s"
    result = execute_query(query, (user_id,))
    if not result:
        return []
    return result

@router.delete("/cart/{user_id}/{product_id}")
async def remove_from_cart(user_id: int, product_id: int):
    # Check if item exists in cart
    check_query = "SELECT * FROM cart WHERE user_id = %s AND id = %s"
    check_result = execute_query(check_query, (user_id, product_id))
    if not check_result:
        raise HTTPException(status_code=404, detail="Item not found in cart")
    
    # Delete the item from cart
    delete_query = "DELETE FROM cart WHERE user_id = %s AND id = %s"
    execute_query(delete_query, (user_id, product_id))
    return {"message": "Item removed from cart"}

@router.put("/cart/{user_id}/{product_id}")
async def update_cart_item(
    user_id: int, 
    product_id: int, 
    item_update: CartItemUpdate  # Use the new model
):
    # Check if item exists in cart
    check_query = "SELECT * FROM cart WHERE user_id = %s AND id = %s"
    check_result = execute_query(check_query, (user_id, product_id))
    if not check_result:
        raise HTTPException(status_code=404, detail="Item not found in cart")
    
    # Update the quantity
    update_query = """
        UPDATE cart 
        SET quantity = %s
        WHERE user_id = %s AND id = %s
    """
    update_params = (item_update.quantity, user_id, product_id)
    execute_query(update_query, update_params)
    return {"message": "Item quantity updated"}