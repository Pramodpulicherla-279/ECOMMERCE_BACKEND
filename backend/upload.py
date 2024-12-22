from fastapi import APIRouter, Depends, HTTPException, Query , Form, Body
from sqlalchemy.orm import Session
from sqlalchemy import text
from models import Product, SessionLocal
from typing import List

router = APIRouter()

def get_db():
    db = SessionLocal()
    try:
        yield db
    finally:
        db.close()

@router.get("/products/{product_id}")
async def get_product(product_id: int, db: Session = Depends(get_db)):
    product = db.query(Product).filter(Product.id == product_id).first()
    if not product:
        raise HTTPException(status_code=404, detail="Product not found")
    return product

# @router.get("/products")
# async def get_products(category: str = None, db: Session = Depends(get_db)):
#     if category:
#         products = db.query(Product).filter(Product.category == category).all()
#     else:
#         products = db.query(Product).all()
#     return products

# @router.get("/products-by-keywords")
# async def get_products_by_keywords(keywords: str, db: Session = Depends(get_db)):
#     keyword_list = keywords.split(',')
#     keyword_conditions = " OR ".join([f"keywords LIKE :keyword{i}" for i in range(len(keyword_list))])
#     sql = f"""
#         SELECT id, name, description, price, stock, category, imageUrls, mainImageUrl, demanded, oldProductId, newProductId, keywords
#         FROM products
#         WHERE {keyword_conditions}
#     """
#     params = {f"keyword{i}": f"%{keyword.strip()}%" for i, keyword in enumerate(keyword_list)}
#     result = db.execute(text(sql), params).mappings().all()
    
#     if not result:
#         raise HTTPException(status_code=404, detail="No products found with the given keywords")
    
#     # Convert result to a list of dictionaries
#     products = [dict(row) for row in result]
#     print(products)
#     return products

@router.get("/products")
async def get_products(category: str = None, keywords: str = None, db: Session = Depends(get_db)):
    if keywords:
        keyword_list = keywords.split(',')
        keyword_conditions = " OR ".join([f"keywords LIKE :keyword{i}" for i in range(len(keyword_list))])
        sql = f"""
            SELECT id, name, description, price, stock, category, imageUrls, mainImageUrl, demanded, oldProductId, newProductId, keywords
            FROM products
            WHERE {keyword_conditions}
        """
        params = {f"keyword{i}": f"%{keyword.strip()}%" for i, keyword in enumerate(keyword_list)}
        result = db.execute(text(sql), params).mappings().all()
        
        if not result:
            raise HTTPException(status_code=404, detail="No products found with the given keywords")
        
        products = [dict(row) for row in result]
    elif category:
        products = db.query(Product).filter(Product.category == category).all()
    else:
        products = db.query(Product).all()
    return products

@router.get("/demanded-products")
async def get_demanded_products(db: Session = Depends(get_db)):
    products = db.query(Product).filter(Product.demanded == True).all()
    return products

@router.post("/upload")
async def upload_product_data(
    name: str = Form(...),
    description: str = Form(...),
    price: float = Form(...),
    stock: int = Form(...),
    category: str = Form(...),
    imageUrls: List[str] = Form(...),  # Use List[str] to receive multiple values
    mainImageUrl: str = Form(...),
    demanded: bool = Form(...),
    keywords: str = Form(...),  # Add keywords parameter
    db: Session = Depends(get_db)
):
    db_product = Product(
        name=name,
        description=description,
        price=price,
        stock=stock,
        category=category,
        imageUrls=imageUrls,
        mainImageUrl=mainImageUrl,
        demanded=demanded,
        keywords=keywords  # Save keywords to the database
    )
    db.add(db_product)
    db.commit()

    return {"message": "Product data uploaded successfully"}

@router.post("/replace-demanded-product")
async def replace_demanded_product(
    oldProductId: int = Body(...),
    newProductId: int = Body(...),
    db: Session = Depends(get_db)
):
    old_product = db.query(Product).filter(Product.id == oldProductId).first()
    new_product = db.query(Product).filter(Product.id == newProductId).first()

    if not old_product or not new_product:
        raise HTTPException(status_code=404, detail="Product not found")

    old_product.demanded = False
    new_product.demanded = True

    db.commit()

    return {"message": "Product replacement successful"}