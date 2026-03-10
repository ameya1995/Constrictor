class User:
    def __init__(self, name: str, email: str) -> None:
        self.name = name
        self.email = email

    def __repr__(self) -> str:
        return f"User(name={self.name!r}, email={self.email!r})"
