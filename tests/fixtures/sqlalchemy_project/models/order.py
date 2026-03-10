from sqlalchemy import Column, ForeignKey, Integer, String
from sqlalchemy.orm import relationship

from models.base import Base


class Order(Base):
    __tablename__ = "orders"

    id = Column(Integer, primary_key=True)
    user_id = Column(Integer, ForeignKey("users.id"), nullable=False)
    product = Column(String(200), nullable=False)
    quantity = Column(Integer, default=1)

    user = relationship("User", back_populates="orders")
