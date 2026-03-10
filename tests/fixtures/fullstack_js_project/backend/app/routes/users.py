from fastapi import APIRouter
from typing import List

router = APIRouter()


@router.get("/api/users")
def list_users():
    return []


@router.post("/api/users")
def create_user():
    return {}


@router.get("/api/users/{user_id}")
def get_user(user_id: int):
    return {}
