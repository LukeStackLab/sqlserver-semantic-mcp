def test_registrations_load(monkeypatch):
    monkeypatch.setenv("SEMANTIC_MCP_MSSQL_SERVER", "x")
    monkeypatch.setenv("SEMANTIC_MCP_MSSQL_DATABASE", "x")
    monkeypatch.setenv("SEMANTIC_MCP_MSSQL_USER", "u")
    monkeypatch.setenv("SEMANTIC_MCP_MSSQL_PASSWORD", "p")
    from sqlserver_semantic_mcp.config import reset_config
    reset_config()
    from sqlserver_semantic_mcp.server.app import _TOOL_REGISTRY
    from sqlserver_semantic_mcp.server.tools import register_all
    _TOOL_REGISTRY.clear()
    register_all()
    expected = [
        # metadata
        "get_tables", "describe_table", "get_columns",
        # relationship
        "get_table_relationships", "find_join_path", "get_dependency_chain",
        # object
        "describe_view", "describe_procedure", "trace_object_dependencies",
        # semantic
        "classify_table", "analyze_columns", "detect_lookup_tables",
        # policy
        "get_execution_policy", "validate_sql_against_policy", "refresh_policy",
        # query
        "validate_query", "run_safe_query",
        # cache
        "refresh_schema_cache",
    ]
    for name in expected:
        assert name in _TOOL_REGISTRY, f"tool not registered: {name}"
    assert len(_TOOL_REGISTRY) >= len(expected)


def test_duplicate_tool_registration_raises(monkeypatch):
    monkeypatch.setenv("SEMANTIC_MCP_MSSQL_SERVER", "x")
    monkeypatch.setenv("SEMANTIC_MCP_MSSQL_DATABASE", "x")
    monkeypatch.setenv("SEMANTIC_MCP_MSSQL_USER", "u")
    monkeypatch.setenv("SEMANTIC_MCP_MSSQL_PASSWORD", "p")
    from sqlserver_semantic_mcp.config import reset_config
    reset_config()
    from mcp.types import Tool
    from sqlserver_semantic_mcp.server.app import _TOOL_REGISTRY, register_tool

    async def handler(args):
        return {"ok": True}

    _TOOL_REGISTRY.clear()
    register_tool(
        Tool(name="dup", description="x", inputSchema={"type": "object"}),
        handler,
    )
    import pytest
    with pytest.raises(ValueError, match="Duplicate tool registration: dup"):
        register_tool(
            Tool(name="dup", description="x", inputSchema={"type": "object"}),
            handler,
        )
