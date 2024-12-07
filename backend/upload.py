from fastapi import APIRouter, Depends, Form, HTTPException
from sqlalchemy.orm import Session
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

@router.get("/products")
async def get_products(category: str = None, db: Session = Depends(get_db)):
    if category:
        products = db.query(Product).filter(Product.category == category).all()
    else:
        products = db.query(Product).all()
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
    db: Session = Depends(get_db)
):
    db_product = Product(
        name=name,
        description=description,
        price=price,
        stock=stock,
        category=category,
        imageUrls=imageUrls,
        mainImageUrl= mainImageUrl
    )
    db.add(db_product)
    db.commit()
    return {"message": "Product data uploaded successfully"}