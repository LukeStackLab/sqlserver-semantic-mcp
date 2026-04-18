# sqlserver-semantic-mcp

[![License](https://img.shields.io/badge/license-MIT-blue.svg)](LICENSE)
[![Python](https://img.shields.io/badge/python-3.11%2B-blue.svg)](https://www.python.org/)
[![MCP](https://img.shields.io/badge/MCP-1.0%2B-purple.svg)](https://modelcontextprotocol.io)
[![Version](https://img.shields.io/badge/version-0.2.0-green.svg)](pyproject.toml)
[![繁體中文](https://img.shields.io/badge/lang-繁體中文-red.svg)](README.zh-TW.md)

> **Semantic intelligence layer for SQL Server databases, exposed via MCP.**
> Not a SQL executor — a database understanding engine for AI agents.

AI agents don't need raw `execute_sql`. They need to understand schema structure, relationships, object dependencies, and — most importantly — to operate inside a safety boundary that an operator can define.

`sqlserver-semantic-mcp` provides all of this through 18 MCP tools and 6 MCP resources, backed by a two-tier SQLite cache for speed and a JSON-based policy system for safety.

---

## Features

- **18 MCP tools** across 6 capability groups (metadata, relationship, semantic, object, query, policy)
- **Two-tier SQLite cache** — Structural Cache (warm on startup) + Semantic Cache (lazy + background fill)
- **3-hash schema versioning** — detect when structural / object / comment changes invalidate cached analysis
- **Policy-gated execution** — SELECT/INSERT/UPDATE/DELETE/… permissions, WHERE-clause requirements, row caps, schema/table allowlists
- **Semantic classification** — automatic detection of fact / dimension / lookup / bridge / audit tables
- **Join path discovery** — BFS over the FK graph to find how two tables relate
- **Object inspection** — view / procedure / function definitions with dependency tracing
- **Graceful degradation** — missing or malformed policy file falls back to read-only; unreachable DB doesn't corrupt cache

---

## Architecture

Five-layer architecture with strict one-way dependencies:

```
MCP Interface      (server/)          ← tool / resource registration
      ↓
Application        (services/)        ← 6 services orchestrate cache + policy + DB
      ↓
Policy / Domain    (policy/, domain/) ← models, SQL intent analysis, enforcement
      ↓
Infrastructure     (infrastructure/)  ← pymssql + SQLite + background task
      ↓
SQL Server + SQLite
```

### Cache Model

| Layer | Contents | Strategy | Invalidation |
|---|---|---|---|
| **Structural Cache** | tables, columns, PK/FK, indexes, objects list, comments | warm on startup, SQLite persisted | `structural_hash` / `object_hash` / `comment_hash` mismatch |
| **Semantic Cache** | table classification, column semantics, object definitions, dependencies | lazy + background incremental fill | hash change → rows marked `dirty` → recomputed |

---

## Installation

Requires Python 3.11+.

```bash
pip install -e ".[dev]"
```

This installs:
- `mcp` (MCP SDK)
- `pymssql` (SQL Server driver)
- `pydantic` + `pydantic-settings` (config + model validation)
- `aiosqlite` (async SQLite cache)
- `pytest` + `pytest-asyncio` + `pytest-mock` (test deps)

---

## Configuration

All configuration is via environment variables with the `SEMANTIC_MCP_` prefix. A `.env` file in the working directory is also loaded automatically.

### Required

| Variable | Description |
|---|---|
| `SEMANTIC_MCP_MSSQL_SERVER` | SQL Server host (supports `(localdb)\Instance` and `*.database.windows.net`) |
| `SEMANTIC_MCP_MSSQL_DATABASE` | Target database name |
| `SEMANTIC_MCP_MSSQL_USER` | SQL auth user (not required when `SEMANTIC_MCP_MSSQL_WINDOWS_AUTH=true`) |
| `SEMANTIC_MCP_MSSQL_PASSWORD` | SQL auth password |

### Optional

| Variable | Default | Description |
|---|---|---|
| `SEMANTIC_MCP_MSSQL_PORT` | `1433` | TCP port |
| `SEMANTIC_MCP_MSSQL_WINDOWS_AUTH` | `false` | Use Windows Authentication |
| `SEMANTIC_MCP_MSSQL_ENCRYPT` | `false` | Force TLS (auto-enabled for Azure SQL) |
| `SEMANTIC_MCP_CACHE_PATH` | `./cache/semantic_mcp.db` | SQLite cache file location |
| `SEMANTIC_MCP_CACHE_ENABLED` | `true` | Disable to skip startup warmup |
| `SEMANTIC_MCP_BACKGROUND_BATCH_SIZE` | `5` | Tables processed per background batch |
| `SEMANTIC_MCP_BACKGROUND_INTERVAL_MS` | `500` | Delay between batches |
| `SEMANTIC_MCP_POLICY_FILE` | *(builtin readonly)* | Path to policy JSON |
| `SEMANTIC_MCP_POLICY_PROFILE` | *(file's active_profile)* | Override which profile is active |
| `SEMANTIC_MCP_MAX_ROWS_RETURNED` | `1000` | Override SELECT row cap |
| `SEMANTIC_MCP_MAX_ROWS_AFFECTED` | `100` | Override DML affected-row cap |
| `SEMANTIC_MCP_QUERY_TIMEOUT` | `30` | Query timeout in seconds |

---

## Policy System

If no policy file is provided, a built-in **read-only** profile is used: only `SELECT` is allowed, at most 1000 rows returned, multi-statement queries rejected.

To use a custom policy, create a JSON file (see `config/policy.example.json`) and point `SEMANTIC_MCP_POLICY_FILE` at it:

```json
{
  "active_profile": "read_write_safe",
  "profiles": {
    "readonly":        { "operations": { "select": true } },
    "read_write_safe": {
      "operations": { "select": true, "insert": true, "update": true },
      "constraints": {
        "require_where_for_update": true,
        "max_rows_affected": 100
      }
    },
    "admin": {
      "operations": { "select": true, "insert": true, "update": true, "delete": true },
      "constraints": { "allow_multi_statement": true }
    }
  }
}
```

### Policy fields

**Operations** — 10 flags (select / insert / update / delete / truncate / create / alter / drop / execute / merge)

**Constraints** — `require_where_for_update`, `require_where_for_delete`, `require_top_for_select`, `max_rows_returned`, `max_rows_affected`, `allow_multi_statement`, `query_timeout_seconds`

**Scope** — `allowed_databases`, `allowed_schemas`, `allowed_tables`, `denied_tables`

> **Safety note:** when `allowed_schemas` is set, queries that reference a table without a schema prefix (e.g. `SELECT * FROM Users` instead of `dbo.Users`) are rejected — you cannot bypass schema-level access control with implicit defaults.

### Failure behavior

| Condition | Behavior |
|---|---|
| Policy file path unset | Builtin readonly, log warning |
| Policy file missing | Builtin readonly, log warning |
| Policy file unreadable | Builtin readonly, log error |
| Policy file has invalid JSON | Builtin readonly, log error |
| Policy file fails schema validation | Builtin readonly, log error |
| `active_profile` / override points to a missing profile | Server refuses to start (misconfiguration surfaced) |

---

## MCP Tools

### Metadata (3)

| Tool | Purpose |
|---|---|
| `get_tables` | List all tables (schema + name) |
| `describe_table` | Columns, PK, FKs, indexes, table description |
| `get_columns` | Column list with types + descriptions |

### Relationship (3)

| Tool | Purpose |
|---|---|
| `get_table_relationships` | Inbound + outbound FK edges for a table |
| `find_join_path` | Shortest FK-based join path between two tables (BFS, bidirectional) |
| `get_dependency_chain` | All tables reachable from a given table via FKs |

### Semantic (3)

| Tool | Purpose |
|---|---|
| `classify_table` | Return table type: fact / dimension / lookup / bridge / audit |
| `analyze_columns` | Semantic labels per column (audit_timestamp, audit_user, status, type…) |
| `detect_lookup_tables` | Scan DB and return likely lookup tables (cache-first) |

### Object (3)

| Tool | Purpose |
|---|---|
| `describe_view` | View definition + dependencies |
| `describe_procedure` | Stored procedure definition + dependencies |
| `trace_object_dependencies` | Flat list of objects/tables a view/proc/function depends on |

### Query (2)

| Tool | Purpose |
|---|---|
| `validate_query` | Analyze SQL intent + report whether policy allows it (no execution) |
| `run_safe_query` | Execute SQL after policy validation; results truncated to `max_rows_returned` |

### Policy (3)

| Tool | Purpose |
|---|---|
| `get_execution_policy` | Return the active policy profile |
| `validate_sql_against_policy` | Same as `validate_query` but policy-focused |
| `refresh_policy` | Hot-reload the policy file |

### Cache (1)

| Tool | Purpose |
|---|---|
| `refresh_schema_cache` | Re-fetch structural metadata; semantic rows with changed hashes are marked dirty |

---

## MCP Resources

```
semantic://schema/tables                          — all tables (JSON)
semantic://schema/tables/{schema}.{table}         — single table metadata
semantic://summary/database                       — counts + hashes
semantic://analysis/classification/{schema}.{table}
semantic://analysis/dependencies/{type}/{schema}.{name}   — type ∈ VIEW/PROCEDURE/FUNCTION
```

Resources are auto-listed per table on the `list_resources` call; individual reads target the URIs above.

---

## Running the Server

```bash
python -m sqlserver_semantic_mcp.main
```

The server speaks MCP over stdio. On startup it:

1. Opens (or creates) the SQLite cache
2. Fetches a fresh Structural snapshot from SQL Server and writes it
3. Enqueues all tables for Semantic analysis
4. Launches the background fill task
5. Accepts MCP tool/resource calls

Background fill uses exponential backoff (2ⁿ seconds, capped at 60s) on persistent errors to avoid log spam or CPU burn.

---

## Development

### Running tests

```bash
pytest tests/unit                      # 82 unit tests, no DB required
pytest tests/integration -m integration # requires live SQL Server
```

### Project structure

```
sqlserver_semantic_mcp/
├── config.py                         — env-backed Pydantic settings
├── main.py                           — stdio server + startup + background task
├── domain/
│   ├── enums.py                      — TableType, ObjectType, CacheStatus, RiskLevel, SqlOperation
│   └── models/                       — Column, Table, ForeignKey, Index, Relationship, DbObject
├── policy/
│   ├── models.py                     — PolicyProfile / PolicyOperations / PolicyConstraints / PolicyScope
│   ├── loader.py                     — JSON loading with graceful fallback
│   ├── analyzer.py                   — regex-based SQL intent extraction
│   └── enforcer.py                   — policy decision (allow/reject + reason)
├── infrastructure/
│   ├── connection.py                 — pymssql connection + helpers
│   ├── background.py                 — background semantic fill loop with backoff
│   ├── cache/
│   │   ├── store.py                  — SQLite DDL + init
│   │   ├── structural.py             — hashing + warmup + snapshot persistence
│   │   └── semantic.py               — analysis/definition I/O + pending queue
│   └── queries/                      — SQL Server queries (metadata / comments / objects)
├── services/                         — 6 services (metadata / relationship / semantic / object / policy / query)
└── server/
    ├── app.py                        — MCP Server, tool registry, JSON envelope
    ├── tools/                        — 7 tool modules (one per capability group)
    └── resources/                    — schema / analysis / summary URIs
```

### Testing conventions

- **Unit tests** use in-memory or tmp-dir SQLite and mock pymssql.
- **Integration tests** are marked `@pytest.mark.integration` and skip unless `SEMANTIC_MCP_MSSQL_SERVER` is set.
- Pydantic models are exercised directly; infrastructure layers are tested with mocked connections.

---

## Security Design

- **Default read-only**: if no policy is configured, only `SELECT` is allowed.
- **SQL validation required**: every query passes through the intent analyzer and policy enforcer before reaching `cursor.execute()`.
- **Denied dangerous statements**: `DROP` / `TRUNCATE` are classified as `CRITICAL` risk level; blocked unless explicitly allowed.
- **Schema-aware access control**: `allowed_schemas` rejects implicit-schema queries to prevent schema-default bypass.
- **Policy hardening**: malformed policy files fall back to read-only rather than crashing the server.

---

## Limitations / Future Work

- SQL intent analyzer is regex-based, not a full T-SQL parser — CTE-defined names may appear as tables. Use `validate_sql_against_policy` first when in doubt.
- `STRING_AGG` used in the index query requires SQL Server 2017+. Older versions will need an alternative query.
- `sys.extended_properties` reads require `VIEW DEFINITION` permission; comments on restricted objects won't appear in the cache.
- Background fill is single-worker; on very large schemas the Semantic Cache may take time to converge (use `refresh_schema_cache` to force a structural refresh; semantic classification still fills lazily).

---

## License

Licensed under the MIT License — see `LICENSE` for details.
