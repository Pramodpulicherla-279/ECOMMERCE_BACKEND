# main.py
from fastapi import FastAPI
from fastapi.middleware.cors import CORSMiddleware
from upload import router as upload_router


app = FastAPI(docs_url="/docs")

origins = [
    "*",  # Allow all origins
]

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
