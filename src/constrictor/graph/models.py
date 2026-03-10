from __future__ import annotations

from enum import Enum

from pydantic import BaseModel

from constrictor.core.models import Certainty, ScanMetadata, ScanStatistics, ScanWarning


class NodeType(str, Enum):
    MODULE = "MODULE"
    PACKAGE = "PACKAGE"
    CLASS = "CLASS"
    FUNCTION = "FUNCTION"
    METHOD = "METHOD"
    ENDPOINT = "ENDPOINT"
    VARIABLE = "VARIABLE"
    DECORATOR = "DECORATOR"
    SQLALCHEMY_MODEL = "SQLALCHEMY_MODEL"
    TABLE = "TABLE"
    EXTERNAL_MODULE = "EXTERNAL_MODULE"
    EXTERNAL_SERVICE = "EXTERNAL_SERVICE"
    EXTERNAL_ENDPOINT = "EXTERNAL_ENDPOINT"
    SERVICE = "SERVICE"
    COMPONENT = "COMPONENT"
    JS_MODULE = "JS_MODULE"
    JS_FUNCTION = "JS_FUNCTION"
    JS_COMPONENT = "JS_COMPONENT"


class EdgeType(str, Enum):
    IMPORTS = "IMPORTS"
    IMPORTS_FROM = "IMPORTS_FROM"
    CALLS = "CALLS"
    RETURNS = "RETURNS"
    INHERITS = "INHERITS"
    IMPLEMENTS = "IMPLEMENTS"
    CONTAINS = "CONTAINS"
    DECORATES = "DECORATES"
    EXPOSES_ENDPOINT = "EXPOSES_ENDPOINT"
    INJECTS_DEPENDENCY = "INJECTS_DEPENDENCY"
    CALLS_HTTP = "CALLS_HTTP"
    DEFINES_MODEL = "DEFINES_MODEL"
    HAS_COLUMN = "HAS_COLUMN"
    FOREIGN_KEY = "FOREIGN_KEY"
    TYPE_ANNOTATED = "TYPE_ANNOTATED"
    CROSSES_COMPONENT_BOUNDARY = "CROSSES_COMPONENT_BOUNDARY"
    BELONGS_TO_SERVICE = "BELONGS_TO_SERVICE"
    AMBIGUOUS = "AMBIGUOUS"


class GraphNode(BaseModel):
    id: str
    type: NodeType
    name: str
    qualified_name: str
    display_name: str
    file_path: str | None = None
    line_number: int | None = None
    column: int | None = None
    certainty: Certainty = Certainty.EXACT
    metadata: dict[str, str] = {}


class GraphEdge(BaseModel):
    id: str
    source_id: str
    target_id: str
    type: EdgeType
    display_name: str
    file_path: str | None = None
    line_number: int | None = None
    certainty: Certainty = Certainty.EXACT
    metadata: dict[str, str] = {}


class GraphDocument(BaseModel):
    nodes: list[GraphNode] = []
    edges: list[GraphEdge] = []
    scan_metadata: ScanMetadata | None = None
    warnings: list[ScanWarning] = []
    unresolved: list[ScanWarning] = []
    statistics: ScanStatistics = ScanStatistics()


class GraphSubgraph(BaseModel):
    focus_node: GraphNode
    nodes: list[GraphNode] = []
    edges: list[GraphEdge] = []


class GraphPath(BaseModel):
    nodes: list[GraphNode] = []
    edges: list[GraphEdge] = []


class GraphPathResult(BaseModel):
    from_node: GraphNode
    to_node: GraphNode
    paths: list[GraphPath] = []


class AmbiguousReview(BaseModel):
    unresolved_edges: list[GraphEdge] = []
    ambiguous_edges: list[GraphEdge] = []
