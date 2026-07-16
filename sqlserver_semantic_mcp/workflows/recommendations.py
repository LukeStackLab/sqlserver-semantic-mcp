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
        recommended = ["plan_or_execute_query", "preview_safe_query"]
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


def estimate_execution_risk(
    query: str,
    *,
    policy: PolicyService,
    cfg: Optional[Config] = None,
) -> dict:
    cfg = cfg or get_config()
    intent = policy.analyze(query)
    constraints = policy.current_policy().constraints

    risks: list[dict] = []
    level = "low"

    def bump(new_level: str) -> None:
        nonlocal level
        order = {"low": 0, "medium": 1, "high": 2, "critical": 3}
        if order[new_level] > order[level]:
            level = new_level

    if intent.risk_level.value in ("critical", "high"):
        bump(intent.risk_level.value)
        risks.append({
            "kind": "policy_risk",
            "detail": f"operation {intent.primary_operation.value} is "
                      f"{intent.risk_level.value}-risk",
        })

    if intent.is_multi_statement and not constraints.allow_multi_statement:
        bump("high")
        risks.append({
            "kind": "policy_risk",
            "detail": "multi-statement query is disallowed",
        })

    if intent.has_unqualified_tables:
        bump("medium")
        risks.append({
            "kind": "schema_qualification_risk",
            "detail": "query references unqualified tables",
        })

    if intent.contains_dynamic_sql:
        bump("high")
        risks.append({
            "kind": "dynamic_sql_risk",
            "detail": "query executes dynamic SQL; analyzer cannot inspect it",
        })

    if intent.primary_operation.value == "SELECT" \
            and not intent.has_top_clause \
            and not intent.has_where_clause:
        bump("medium")
        risks.append({
            "kind": "payload_risk",
            "detail": "SELECT without TOP or WHERE may return large payloads",
        })

    validation = policy.validate(query, database=cfg.mssql_database)
    allowed = validation["allowed"]

    return ToolEnvelope(
        kind="estimate_execution_risk",
        detail="brief",
        confidence=intent.confidence,
        next_action="execute" if allowed and level in ("low", "medium") else "revise_query",
        recommended_tool=(
            "plan_or_execute_query" if allowed else "validate_query"
        ),
        data={
            "operation": intent.primary_operation.value,
            "tables": intent.affected_tables,
            "risk_level": level,
            "risks": risks,
            "allowed_by_policy": allowed,
            "policy_reason": validation["reason"],
            "max_rows_returned": constraints.max_rows_returned,
            "max_rows_affected": constraints.max_rows_affected,
        },
    ).to_dict()
