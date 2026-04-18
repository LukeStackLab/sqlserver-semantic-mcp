import pytest


@pytest.fixture
def env(monkeypatch, tmp_path):
    monkeypatch.setenv("SEMANTIC_MCP_MSSQL_SERVER", "x")
    monkeypatch.setenv("SEMANTIC_MCP_MSSQL_DATABASE", "testdb")
    monkeypatch.setenv("SEMANTIC_MCP_MSSQL_USER", "u")
    monkeypatch.setenv("SEMANTIC_MCP_MSSQL_PASSWORD", "p")
    monkeypatch.setenv("SEMANTIC_MCP_CACHE_PATH", str(tmp_path / "t.db"))
    from sqlserver_semantic_mcp.config import reset_config
    reset_config()


@pytest.mark.asyncio
async def test_list_resources_is_constant_size(env):
    from sqlserver_semantic_mcp.server.resources import schema as mod

    resources = await mod.list_resources()

    assert len(resources) == 2
    uris = [str(r.uri) for r in resources]
    assert "semantic://schema/tables" in uris
    assert "semantic://summary/database" in uris


@pytest.mark.asyncio
async def test_list_resource_templates_returns_two_patterns(env):
    from sqlserver_semantic_mcp.server.resources import schema as mod

    templates = await mod.list_resource_templates()

    assert len(templates) == 2
    patterns = [t.uriTemplate for t in templates]
    assert "semantic://schema/tables/{qualified}" in patterns
    assert "semantic://analysis/classification/{qualified}" in patterns
