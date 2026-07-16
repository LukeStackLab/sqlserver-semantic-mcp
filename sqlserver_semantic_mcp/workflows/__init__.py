"""Agent-oriented workflow layer.

Sits between ``server/tools`` and ``services``. Responsible for
route decision, handoff contracts, context bundling, and the
direct-execution fast path.
"""
from .contracts import ToolEnvelope, RouteDecision, Route
from .router import route_query
from .query_flow import plan_or_execute_query
from .discovery_flow import discover_relevant_tables
from .bundle import bundle_context_for_next_step
from .facade import WorkflowFacade

__all__ = [
    "ToolEnvelope",
    "RouteDecision",
    "Route",
    "route_query",
    "plan_or_execute_query",
    "discover_relevant_tables",
    "bundle_context_for_next_step",
    "WorkflowFacade",
]
