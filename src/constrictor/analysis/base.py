from __future__ import annotations

from typing import Protocol

from constrictor.core.models import ScanWarning
from constrictor.core.parser import ParsedModule
from constrictor.graph.builder import GraphBuilder


class GraphContributor(Protocol):
    name: str

    def contribute(
        self,
        parsed_modules: list[ParsedModule],
        builder: GraphBuilder,
        warnings: list[ScanWarning],
    ) -> None: ...

    def post_process(self, builder: GraphBuilder) -> None: ...
