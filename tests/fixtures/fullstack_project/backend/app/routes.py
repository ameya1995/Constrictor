from fastapi import APIRouter
from app.services import get_order

router = APIRouter()


@router.get("/orders/{order_id}")
def read_order(order_id: int):
    return get_order(order_id)


@router.post("/orders")
def create_order(data: dict):
    return {"created": True}
