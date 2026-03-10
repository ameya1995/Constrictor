from pydantic import BaseModel


class OrderCreate(BaseModel):
    user_id: int
    product: str
    quantity: int


class OrderResponse(BaseModel):
    id: int
    user_id: int
    product: str
    quantity: int
