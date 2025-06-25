# main.py
from fastapi import FastAPI
from fastapi.middleware.cors import CORSMiddleware
from upload import router as upload_router
from cart import router as cart_router
from favorites import router as favorites_router
from orders import router as orders_router
from user_addresses import router as user_addresses_router  # Import your user addresses router
import uvicorn
from payments import router as payments_router  # Import your payments router
from user import user_router
from agent.agent import router as agent_router
from fastapi import Request
import logging


app = FastAPI(docs_url="/docs")

origins = [
    "*",  # Allow all origins
]

@app.middleware("http")
async def log_errors(request: Request, call_next):
    try:
        return await call_next(request)
    except Exception as e:
        logging.error(f"Error in {request.url}: {str(e)}", exc_info=True)
        raise
    
app.add_middleware(
    CORSMiddleware,
    allow_origins=origins,
    allow_credentials=True,
    allow_methods=["*"],
    allow_headers=["*"],
)


@app.get("/")
def read_root():
    return {"Hello": "World"}

# Include your routers here
app.include_router(upload_router)
app.include_router(cart_router)
app.include_router(favorites_router)
app.include_router(orders_router)
app.include_router(payments_router, prefix="/api")
app.include_router(user_router)
app.include_router(user_addresses_router)  # Include user addresses router
app.include_router(agent_router)



if __name__ == "__main__":
    uvicorn.run(app, host="127.0.0.1", port=8001)
