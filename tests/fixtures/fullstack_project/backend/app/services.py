from shared.models import Order
from shared.utils import format_result


def get_order(order_id: int) -> dict:
    order = Order(id=order_id, description="example")
    return format_result(order)
