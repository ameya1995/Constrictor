from sqlalchemy import Column, Integer, String
from sqlalchemy.orm import relationship

from models.base import Base


class User(Base):
    __tablename__ = "users"

    id = Column(Integer, primary_key=True)
    name = Column(String(100), nullable=False)
    email = Column(String(255), unique=True, nullable=False)

    orders = relationship("Order", back_populates="user")
