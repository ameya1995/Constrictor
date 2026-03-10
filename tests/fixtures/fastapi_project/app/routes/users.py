from typing import Annotated

from fastapi import APIRouter, Depends

from app.dependencies import get_current_user, get_db
from app.models.user import UserCreate, UserResponse

router = APIRouter(prefix="/users", tags=["users"])


@router.get("/users")
def list_users(db=Depends(get_db)) -> list[UserResponse]:
    return []


@router.post("/users")
def create_user(body: UserCreate, db=Depends(get_db)) -> UserResponse:
    return UserResponse(id=1, name=body.name, email=body.email)


@router.get("/users/{user_id}")
def get_user(user_id: int, current_user=Depends(get_current_user)) -> UserResponse:
    return UserResponse(id=user_id, name="Alice", email="alice@example.com")
