from fastapi import APIRouter

router = APIRouter()


@router.get("/api/orders")
def list_orders():
    return []


@router.post("/api/orders")
def create_order():
    return {}
