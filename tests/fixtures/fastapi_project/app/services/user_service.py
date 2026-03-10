import requests


def fetch_auth_user(user_id: int) -> dict:
    """Call external auth service to verify user."""
    response = requests.get(f"http://auth-service/api/users/{user_id}")
    return response.json()


def notify_user(user_id: int, message: str) -> None:
    """Post notification to notification service."""
    requests.post("http://notification-service/notify", json={"user_id": user_id, "msg": message})
