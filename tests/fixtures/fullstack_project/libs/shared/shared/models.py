from sqlalchemy import Column, Integer, String
from sqlalchemy.orm import declarative_base

Base = declarative_base()


class Order(Base):
    __tablename__ = "orders"

    id = Column(Integer, primary_key=True)
    description = Column(String)
