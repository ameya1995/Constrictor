# circular_a imports circular_b
from tests.fixtures.edge_cases import circular_b


def func_a() -> None:
    circular_b.func_b()
