from fastapi import FastAPI

from app.routes.orders import router as orders_router
from app.routes.users import router as users_router

app = FastAPI(title="Demo API")

app.include_router(users_router)
app.include_router(orders_router)


@app.get("/health")
def health_check() -> dict:
    return {"status": "ok"}
