from fastapi import FastAPI
from app.routes import router

app = FastAPI(title="Fullstack API")
app.include_router(router)
