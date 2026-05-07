"""Single workflow entry point exposed to ``server.app.Context``."""
from __future__ import annotations

from typing import Optional

from ..config import Config, get_config
from ..services.policy_service import PolicyService
from ..services.query_service import QueryService
from .bundle import bundle_context_for_next_step
from .discovery_flow import discover_relevant_tables
from .query_flow import plan_or_execute_query
from .recommendations import estimate_execution_risk, suggest_next_tool
from .router import route_query


class WorkflowFacade:
    """Thin wrapper so tool modules reach workflow helpers via one object."""

    def __init__(
        self,
        cfg: Config,
        policy: PolicyService,
        query: QueryService,
    ) -> None:
        self.cfg = cfg
        self.policy = policy
        self.query = query

    # ---- synchronous helpers ------------------------------------------------

    def route_query(self, query: Optional[str]) -> dict:
        return route_query(
            query, policy=self.policy, database=self.cfg.mssql_database,
        ).to_dict()

    def plan_or_execute_query(
        self,
        query: str,
        *,
        mode: str = "auto",
        max_rows: Optional[int] = None,
        return_mode: Optional[str] = None,
        detail: str = "brief",
        token_budget_hint: Optional[str] = None,
        affected_rows_policy: Optional[str] = None,
    ) -> dict:
        return plan_or_execute_query(
            query,
            policy=self.policy,
            query_service=self.query,
            mode=mode,
            max_rows=max_rows,
            return_mode=return_mode,
            detail=detail,
            token_budget_hint=token_budget_hint,
            affected_rows_policy=affected_rows_policy,
            cfg=self.cfg,
        )

    def preview_safe_query(
        self,
        query: str,
        *,
        max_rows: Optional[int] = None,
    ) -> dict:
        preview = self.query.preview_query(
            query, max_rows=max_rows, database=self.cfg.mssql_database,
        )
        return {
            "kind": "preview_safe_query",
            "detail": "brief",
            "next_action": preview["next_action"],
            "recommended_tool": (
                "plan_or_execute_query" if preview["allowed"]
                else "validate_query"
            ),
            "data": preview,
        }

    def suggest_next_tool(self, **kwargs) -> dict:
        return suggest_next_tool(policy=self.policy, cfg=self.cfg, **kwargs)

    def estimate_execution_risk(self, query: str) -> dict:
        return estimate_execution_risk(
            query, policy=self.policy, cfg=self.cfg,
        )

    # ---- async helpers ------------------------------------------------------

    async def discover_relevant_tables(
        self,
        goal: str,
        *,
        schemas: Optional[list[str]] = None,
        keyword: Optional[str] = None,
        limit: int = 10,
        classify: bool = False,
    ) -> dict:
        return await discover_relevant_tables(
            goal,
            schemas=schemas,
            keyword=keyword,
            limit=limit,
            classify=classify,
            cfg=self.cfg,
        )

    async def bundle_context_for_next_step(
        self,
        items: list[dict],
        *,
        goal: str = "joining",
        detail: str = "brief",
    ) -> dict:
        return await bundle_context_for_next_step(
            items, goal=goal, detail=detail, cfg=self.cfg,
        )
