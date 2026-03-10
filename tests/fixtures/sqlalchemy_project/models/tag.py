from sqlalchemy import Column, ForeignKey, Integer, String, Table
from sqlalchemy.orm import relationship

from models.base import Base

order_tags = Table(
    "order_tags",
    Base.metadata,
    Column("order_id", Integer, ForeignKey("orders.id")),
    Column("tag_id", Integer, ForeignKey("tags.id")),
)


class Tag(Base):
    __tablename__ = "tags"

    id = Column(Integer, primary_key=True)
    label = Column(String(50), nullable=False)
