from fastapi import APIRouter, HTTPException, Query, Form, Body
from typing import List, Optional
from pydantic import BaseModel
from db import execute_query
import json

router = APIRouter()

# SQL query to create the products table
# create_table_query = """
# CREATE TABLE IF NOT EXISTS products (
#     id INT AUTO_INCREMENT PRIMARY KEY,
#     name VARCHAR(255) NOT NULL,
#     description TEXT,
#     price FLOAT NOT NULL,
#     stock INT NOT NULL,
#     category VARCHAR(255),
#     imageUrls JSON,
#     mainImageUrl VARCHAR(255),
#     demanded BOOLEAN,
#     keywords VARCHAR(255)
# )
# """

# # Execute the create table query
# execute_query(create_table_query)

class Product(BaseModel):
    name: str
    description: str
    price: float
    stock: int
    category: str
    imageUrls: List[str]
    mainImageUrl: str
    demanded: bool
    keywords: str

class ReplaceDemandedProduct(BaseModel):
    oldProductId: int
    newProductId: int

@router.get("/products/{product_id}")
async def get_product(product_id: int):
    query = "SELECT * FROM products WHERE id = %s"
    result = execute_query(query, (product_id,))
    if not result:
        raise HTTPException(status_code=404, detail="Product not found")
    product = result[0]
    product['imageUrls'] = json.loads(product['imageUrls'])
    return product

@router.get("/products")
async def get_products(category: Optional[str] = None, keywords: Optional[str] = None):
    if keywords:
        keyword_list = keywords.split(',')
        keyword_conditions = " OR ".join([f"keywords LIKE %s" for _ in keyword_list])
        query = f"SELECT * FROM products WHERE {keyword_conditions}"
        params = tuple(f"%{keyword.strip()}%" for keyword in keyword_list)
        result = execute_query(query, params)
    elif category:
        query = "SELECT * FROM products WHERE category = %s"
        result = execute_query(query, (category,))
    else:
        query = "SELECT * FROM products"
        result = execute_query(query)
    
    if not result:
        raise HTTPException(status_code=404, detail="No products found")
    return result

@router.get("/demanded-products")
async def get_demanded_products():
    query = "SELECT * FROM products WHERE demanded = TRUE"
    result = execute_query(query)
    if not result:
        return []
    for product in result:
        product['imageUrls'] = json.loads(product['imageUrls'])
    return result

@router.post("/upload")
async def upload_product_data(product: Product):
    query = """
        INSERT INTO products (name, description, price, stock, category, imageUrls, mainImageUrl, demanded, keywords)
        VALUES (%s, %s, %s, %s, %s, %s, %s, %s, %s)
    """
    params = (product.name, product.description, product.price, product.stock, product.category, json.dumps(product.imageUrls), product.mainImageUrl, product.demanded, product.keywords)
    execute_query(query, params)
    return {"message": "Product data uploaded successfully"}

@router.post("/replace-demanded-product")
async def replace_demanded_product(replace_data: ReplaceDemandedProduct):
    query1 = "UPDATE products SET demanded = FALSE WHERE id = %s"
    query2 = "UPDATE products SET demanded = TRUE WHERE id = %s"
    execute_query(query1, (replace_data.oldProductId,))
    execute_query(query2, (replace_data.newProductId,))
    return {"message": "Product replacement successful"}