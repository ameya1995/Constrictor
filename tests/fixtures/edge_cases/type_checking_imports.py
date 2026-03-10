"""Module with TYPE_CHECKING guard for conditional imports."""
from __future__ import annotations

from typing import TYPE_CHECKING

if TYPE_CHECKING:
    from os import PathLike
    from typing import Optional


def process(path: PathLike) -> Optional[str]:
    return str(path)
