from typing import Generator


def get_db() -> Generator:
    """Yield a fake database session."""
    try:
        yield {"connected": True}
    finally:
        pass


def get_current_user():
    """Return a fake current user."""
    return {"id": 1, "name": "Alice"}
