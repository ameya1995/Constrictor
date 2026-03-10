from app.utils import greet
from app.models import User


def run_app() -> None:
    user = User(name="Alice", email="alice@example.com")
    message = greet(user.name)
    print(message)


if __name__ == "__main__":
    run_app()
