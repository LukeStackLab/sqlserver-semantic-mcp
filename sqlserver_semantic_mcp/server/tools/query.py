from mcp.types import Tool

from ..app import get_context, register_tool


_DETAIL_PROP = {
    "type": "string", "enum": ["brief", "standard", "full"], "default": "brief",
}
_BUDGET_PROP = {
    "type": "string", "enum": ["tiny", "low", "medium", "high"],
}
_RESPONSE_MODE_PROP = {
    "type": "string", "enum": ["summary", "rows", "sample", "count_only"],
    "description": "summary=columns+count; rows=full page; "
                   "sample=columns+first N; count_only=row_count only.",
}
_AFFECTED_POLICY_PROP = {
    "type": "string", "enum": ["strict", "report"],
    "description": "strict = roll back if affected rows exceed cap; "
                   "report = execute and report exceeded_cap.",
}


def register() -> None:
    register_tool(
        Tool(
            name="validate_query",
            description=(
                "Analyze a SQL query and report intent + whether policy allows "
                "it. Use this when you want to test a query without executing."
            ),
            inputSchema={
                "type": "object",
                "properties": {"query": {"type": "string"}},
                "required": ["query"],
            },
        ),
        _validate,
    )
    register_tool(
        Tool(
            name="run_safe_query",
            description=(
                "Execute SQL after policy validation. Result rows are truncated "
                "to max_rows_returned. Prefer plan_or_execute_query for the "
                "shortest safe path when SQL is already known."
            ),
            inputSchema={
                "type": "object",
                "properties": {
                    "query": {"type": "string"},
                    "max_rows": {"type": "integer", "minimum": 1},
                },
                "required": ["query"],
            },
        ),
        _run_safe,
    )
    register_tool(
        Tool(
            name="plan_or_execute_query",
            description=(
                "v0.5 main entry for SQL-ready agents. mode=auto validates then "
                "executes if safe; mode=validate_only stops after validation; "
                "mode=dry_run returns preview without side effects. Do not use "
                "this for schema discovery — use discover_relevant_tables first "
                "when the target tables are unknown."
            ),
            inputSchema={
                "type": "object",
                "properties": {
                    "query":                _required_query(),
                    "mode": {
                        "type": "string",
                        "enum": ["auto", "validate_only", "dry_run",
                                 "execute_if_safe"],
                        "default": "auto",
                    },
                    "max_rows":             {"type": "integer", "minimum": 1},
                    "return_mode":          _RESPONSE_MODE_PROP,
                    "detail":               _DETAIL_PROP,
                    "token_budget_hint":    _BUDGET_PROP,
                    "affected_rows_policy": _AFFECTED_POLICY_PROP,
                },
                "required": ["query"],
            },
        ),
        _plan_or_execute,
    )
    register_tool(
        Tool(
            name="preview_safe_query",
            description=(
                "Return a minimal plan — operation, affected tables, policy "
                "outcome, applied row caps — without executing."
            ),
            inputSchema={
                "type": "object",
                "properties": {
                    "query":    _required_query(),
                    "max_rows": {"type": "integer", "minimum": 1},
                },
                "required": ["query"],
            },
        ),
        _preview,
    )
    register_tool(
        Tool(
            name="estimate_execution_risk",
            description=(
                "Estimate payload / policy / qualification risks for a SQL "
                "string without executing it."
            ),
            inputSchema={
                "type": "object",
                "properties": {"query": {"type": "string"}},
                "required": ["query"],
            },
        ),
        _estimate_risk,
    )


def _required_query() -> dict:
    return {"type": "string", "description": "SQL to execute / validate."}


async def _validate(args: dict) -> dict:
    return get_context().query.validate(args["query"])


async def _run_safe(args: dict) -> dict:
    return get_context().query.run_safe_query(
        args["query"], max_rows=args.get("max_rows"),
    )


async def _plan_or_execute(args: dict) -> dict:
    ctx = get_context()
    return ctx.workflow.plan_or_execute_query(
        args["query"],
        mode=args.get("mode", "auto"),
        max_rows=args.get("max_rows"),
        return_mode=args.get("return_mode"),
        detail=args.get("detail", "brief"),
        token_budget_hint=args.get("token_budget_hint"),
        affected_rows_policy=args.get("affected_rows_policy"),
    )


async def _preview(args: dict) -> dict:
    return get_context().workflow.preview_safe_query(
        args["query"], max_rows=args.get("max_rows"),
    )


async def _estimate_risk(args: dict) -> dict:
    return get_context().workflow.estimate_execution_risk(args["query"])
