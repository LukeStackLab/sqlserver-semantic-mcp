"""Direct-execution fast path for SQL-ready agents."""
from __future__ import annotations

from typing import Optional

from ..config import Config, get_config
from ..services.policy_service import PolicyService
from ..services.query_service import QueryService
from .contracts import ToolEnvelope
from .router import route_query


def plan_or_execute_query(
    query: str,
    *,
    policy: PolicyService,
    query_service: QueryService,
    mode: str = "auto",
    max_rows: Optional[int] = None,
    return_mode: Optional[str] = None,
    detail: str = "brief",
    token_budget_hint: Optional[str] = None,
    affected_rows_policy: Optional[str] = None,
    cfg: Optional[Config] = None,
) -> dict:
    """Single entry point for agents holding ready-to-run SQL.

    mode:
      * ``auto``           — execute if safe, otherwise return plan
      * ``validate_only``  — validate and stop
      * ``dry_run``        — return preview (validation + shape, no side effects)
      * ``execute_if_safe``— same as ``auto`` (kept as alias for clarity)
    """
    cfg = cfg or get_config()
    database = cfg.mssql_database

    # Explicit sub-modes short-circuit routing.
    if mode == "validate_only":
        payload = query_service.validate_query(query, database=database)
        return ToolEnvelope(
            kind="plan_or_execute_query",
            detail=detail,
            confidence=payload["intent"]["confidence"],
            next_action=payload["next_action"],
            recommended_tool=(
                "plan_or_execute_query" if payload["allowed"] else "validate_query"
            ),
            data={"path": "direct_validate", "executed": False, **payload},
        ).to_dict()

    if mode == "dry_run":
        preview = query_service.preview_query(
            query, max_rows=max_rows, database=database,
        )
        return ToolEnvelope(
            kind="plan_or_execute_query",
            detail=detail,
            next_action=preview["next_action"],
            recommended_tool=(
                "plan_or_execute_query" if preview["allowed"] else "validate_query"
            ),
            data={"path": "dry_run", "executed": False, **preview},
        ).to_dict()

    decision = route_query(query, policy=policy, database=database)

    if decision.route == "direct_execute" and cfg.direct_execute_enabled:
        result = query_service.execute_query(
            query,
            max_rows=max_rows,
            response_mode=return_mode,
            token_budget_hint=token_budget_hint,
            affected_rows_policy=affected_rows_policy,
            database=database,
        )
        return ToolEnvelope(
            kind="plan_or_execute_query",
            detail=detail,
            confidence=decision.confidence,
            next_action=result.get("next_action", "done"),
            recommended_tool=None,
            data={
                "path": "direct_execute",
                **result,
                "route": decision.to_dict(),
            },
        ).to_dict()

    if decision.route == "direct_validate":
        # Policy denied — don't execute even under mode=auto.
        payload = query_service.validate_query(query, database=database)
        return ToolEnvelope(
            kind="plan_or_execute_query",
            detail=detail,
            confidence=decision.confidence,
            next_action=payload["next_action"],
            recommended_tool="validate_query",
            data={
                "path": "direct_validate",
                "executed": False,
                **payload,
                "route": decision.to_dict(),
            },
        ).to_dict()

    # discovery / policy_only
    return ToolEnvelope(
        kind="plan_or_execute_query",
        detail=detail,
        confidence=decision.confidence,
        next_action="discover",
        recommended_tool=decision.recommended_tools[0]
        if decision.recommended_tools else "discover_relevant_tables",
        data={
            "path": decision.route,
            "executed": False,
            "reason": decision.reason,
            "route": decision.to_dict(),
        },
    ).to_dict()
