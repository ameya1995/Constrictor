# circular_b imports circular_a
from tests.fixtures.edge_cases import circular_a


def func_b() -> None:
    circular_a.func_a()
