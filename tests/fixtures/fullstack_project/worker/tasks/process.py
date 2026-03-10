from shared.models import Order
from shared.utils import format_result


def run_task(order_id: int) -> None:
    order = Order(id=order_id, description="task")
    result = format_result(order)
    print(result)


if __name__ == "__main__":
    run_task(1)
