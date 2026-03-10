from app.utils import greet
from app.models import User


def test_greet() -> None:
    assert greet("World") == "Hello, World!"


def test_user() -> None:
    u = User(name="Bob", email="bob@example.com")
    assert u.name == "Bob"
    assert u.email == "bob@example.com"
