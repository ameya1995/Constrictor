from fastapi import APIRouter, Depends

from app.dependencies import get_db
from app.models.order import OrderCreate, OrderResponse

router = APIRouter(prefix="/orders", tags=["orders"])


@router.get("/orders/{order_id}")
def get_order(order_id: int, db=Depends(get_db)) -> OrderResponse:
    return OrderResponse(id=order_id, user_id=1, product="widget", quantity=1)


@router.post("/orders")
def create_order(body: OrderCreate, db=Depends(get_db)) -> OrderResponse:
    return OrderResponse(id=99, user_id=body.user_id, product=body.product, quantity=body.quantity)


@router.delete("/orders/{order_id}")
def delete_order(order_id: int, db=Depends(get_db)) -> dict:
    return {"deleted": order_id}
