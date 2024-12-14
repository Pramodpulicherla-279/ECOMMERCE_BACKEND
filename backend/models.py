from sqlalchemy import Column, Integer, String, Float, JSON, Boolean
from sqlalchemy.ext.declarative import declarative_base
from sqlalchemy.orm import sessionmaker
from sqlalchemy import create_engine
import urllib.parse

Base = declarative_base()

# URL-encode the password
password = urllib.parse.quote_plus('Pramod@23057')
engine = create_engine(f'mysql+mysqlconnector://root:{password}@127.0.0.1/Ecommerce_DB')
SessionLocal = sessionmaker(autocommit=False, autoflush=False, bind=engine)

class Product(Base):
    __tablename__ = "products"
    id = Column(Integer, primary_key=True, index=True)
    name = Column(String, index=True)
    description = Column(String)
    price = Column(Float)
    stock = Column(Integer)
    category = Column(String)
    imageUrls = Column(JSON)  # Use JSON column to store list of URLs
    mainImageUrl = Column(String)
    demanded = Column(Boolean)  # Add the demanded column

Base.metadata.create_all(bind=engine)