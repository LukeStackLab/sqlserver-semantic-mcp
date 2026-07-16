"""Recommendation + risk-estimation helpers."""
from __future__ import annotations

from typing import Optional

from ..config import Config, get_config
from ..services.policy_service import PolicyService
from .contracts import ToolEnvelope
from .router import route_query


def suggest_next_tool(
    *,
    policy: PolicyService,
    cfg: Optional[Config] = None,
    query: Optional[str] = None,
    goal: Optional[str] = None,
    have_candidates: bool = False,
    have_join_path: bool = False,
    have_object: Optional[str] = None,
) -> dict:
    """Look at the agent's current state and recommend the next call.

    This does not invoke any DB tools — it only applies routing logic.
    """
    cfg = cfg or get_config()
    rationale: list[str] = []

    if query:
        decision = route_query(query, policy=policy, database=cfg.mssql_database)
        rationale.append(
            f"query routed to '{decision.route}' ({decision.reason})"
        )
        return ToolEnvelope(
            kind="suggest_next_tool",
            detail="brief",
            confidence=decision.confidence,
            next_action=decision.route,
            recommended_tool=(decision.recommended_tools[0]
                              if decision.recommended_tools else None),
            data={
                "recommended_tools": list(decision.recommended_tools),
                "route": decision.to_dict(),
                "rationale": rationale,
            },
        ).to_dict()

    recommended: list[str] = []
    next_action: str
    if have_object:
        recommended = ["describe_object", "bundle_context_for_next_step"]
        next_action = "trace_impact"
        rationale.append("object context available — trace its dependencies")
    elif have_join_path:
        recommended = ["plan_or_execute_query"]
        next_action = "execute"
        rationale.append("join path ready — draft SQL and execute via fast path")
    elif have_candidates:
        recommended = ["describe_table", "find_join_path"]
        next_action = "inspect_or_join"
        rationale.append("candidates narrowed — inspect and compute join path")
    elif goal:
        recommended = ["discover_relevant_tables", "get_tables"]
        next_action = "discover"
        rationale.append("no candidates yet — start from discovery")
    else:
        recommended = ["get_tables", "get_execution_policy"]
        next_action = "orient"
        rationale.append("no query, goal, or candidates — orient first")

    return ToolEnvelope(
        kind="suggest_next_tool",
        detail="brief",
        next_action=next_action,
        recommended_tool=recommended[0] if recommended else None,
        data={
            "recommended_tools": recommended,
            "rationale": rationale,
        },
    ).to_dict()
