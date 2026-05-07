# sqlserver-semantic-mcp

[![License](https://img.shields.io/badge/license-MIT-blue.svg)](LICENSE)
[![Python](https://img.shields.io/badge/python-3.11%2B-blue.svg)](https://www.python.org/)
[![MCP](https://img.shields.io/badge/MCP-1.0%2B-purple.svg)](https://modelcontextprotocol.io)
[![Version](https://img.shields.io/badge/version-0.5.0-green.svg)](pyproject.toml)
[![繁體中文](https://img.shields.io/badge/lang-繁體中文-red.svg)](README.zh-TW.md)

> **Semantic intelligence layer for SQL Server databases, exposed via MCP.**
> Not a SQL executor — a database understanding engine for AI agents.

AI agents don't need raw `execute_sql`. They need to understand schema structure, relationships, object dependencies, and — most importantly — to operate inside a safety boundary that an operator can define.

`sqlserver-semantic-mcp` provides all of this through 29 MCP tools, 1 concrete MCP resource, and 5 MCP resource templates, backed by a two-tier SQLite cache for speed and a JSON-based policy system for safety.

---

## Quick Start

> **30 seconds to a running server.** Fill in your credentials, start the server, point Claude Desktop at it.

### Step 1 — Install

**Option A — pip editable install (recommended for local dev):**

```bash
git clone https://github.com/lukedev999-boom/sqlserver-semantic-mcp.git
cd sqlserver-semantic-mcp
pip install -e ".[dev]"
```

**Option B — uv:**

```bash
git clone https://github.com/lukedev999-boom/sqlserver-semantic-mcp.git
cd sqlserver-semantic-mcp
uv sync
```

### Step 2 — Configure

Copy the example env file and fill in your SQL Server credentials:

```bash
cp .env.example .env
```

Minimum required settings in `.env`:

```env
SEMANTIC_MCP_MSSQL_SERVER=localhost
SEMANTIC_MCP_MSSQL_DATABASE=YourDatabase
SEMANTIC_MCP_MSSQL_USER=sa
SEMANTIC_MCP_MSSQL_PASSWORD=YourPassword
```

All other settings are optional and documented in the [Configuration](#configuration) section.

### Step 3 — Run

If you installed via pip (Option A), the `sqlserver-semantic-mcp` console script is on your PATH:

```bash
sqlserver-semantic-mcp
```

If you used uv (Option B):

```bash
uv run python -m sqlserver_semantic_mcp.main
```

The server speaks MCP over stdio. You should see startup log lines confirming cache initialisation and tool registration.

### Step 4 — Connect to Claude Desktop

Open your Claude Desktop MCP config file:

- **macOS:** `~/Library/Application Support/Claude/claude_desktop_config.json`
- **Windows:** `%APPDATA%\Claude\claude_desktop_config.json`

**If you installed via pip (the `sqlserver-semantic-mcp` binary is on your PATH):**

```json
{
  "mcpServers": {
    "sqlserver-semantic-mcp": {
      "command": "sqlserver-semantic-mcp",
      "env": {
        "SEMANTIC_MCP_MSSQL_SERVER": "localhost",
        "SEMANTIC_MCP_MSSQL_DATABASE": "YourDatabase",
        "SEMANTIC_MCP_MSSQL_USER": "sa",
        "SEMANTIC_MCP_MSSQL_PASSWORD": "YourPassword"
      }
    }
  }
}
```

**If you are using uv (specify the full project path):**

```json
{
  "mcpServers": {
    "sqlserver-semantic-mcp": {
      "command": "uv",
      "args": [
        "run",
        "--project", "/path/to/sqlserver-semantic-mcp",
        "python", "-m", "sqlserver_semantic_mcp.main"
      ],
      "env": {
        "SEMANTIC_MCP_MSSQL_SERVER": "localhost",
        "SEMANTIC_MCP_MSSQL_DATABASE": "YourDatabase",
        "SEMANTIC_MCP_MSSQL_USER": "sa",
        "SEMANTIC_MCP_MSSQL_PASSWORD": "YourPassword"
      }
    }
  }
}
```

Restart Claude Desktop after saving. The server will appear under MCP integrations.

---

## Features

- **29 MCP tools** across 9 capability groups (metadata, relationship, semantic, object, query, policy, cache, metrics, workflow)
- **Two-tier SQLite cache** — Structural Cache (warm on startup) + Semantic Cache (lazy + background fill)
- **Cache-first startup** — reuse existing structural cache by default and avoid mandatory full warmup on every process start
- **3-hash schema versioning** — detect when structural / object / comment changes invalidate cached analysis
- **Policy-gated execution** — SELECT/INSERT/UPDATE/DELETE/… permissions, WHERE-clause requirements, row caps, schema/table allowlists
- **Semantic classification** — automatic detection of fact / dimension / lookup / bridge / audit tables
- **Join path discovery** — BFS over the FK graph to find how two tables relate
- **Object inspection** — view / procedure / function definitions with dependency tracing plus read/write split
- **Workflow shortcuts** — discovery, risk estimation, context bundling, and direct execution fast-path tools
- **Payload metrics** — built-in measurement for per-tool response size
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

**Editable install with pip** (registers the `sqlserver-semantic-mcp` console script on your PATH):

```bash
pip install -e ".[dev]"
```

**Install with uv:**

```bash
uv sync
# include dev dependencies:
uv sync --dev
```

**Run without installing** (uv project mode):

```bash
uv run python -m sqlserver_semantic_mcp.main
```

Installed dependencies:

| Package | Role |
|---|---|
| `mcp` | MCP SDK (stdio transport) |
| `pymssql` | SQL Server wire driver (wraps FreeTDS) |
| `pydantic` + `pydantic-settings` | Config validation, env var loading |
| `aiosqlite` | Async SQLite for the two-tier cache |

Dev-only dependencies: `pytest`, `pytest-asyncio`, `pytest-mock`.

> **Linux note:** `pymssql` links against FreeTDS. If `pip install` fails with a compiler error, install system headers first — see [Troubleshooting](#troubleshooting).

---

## Configuration

All configuration is via environment variables with the `SEMANTIC_MCP_` prefix. A `.env` file in the working directory is also loaded automatically. Start from `.env.example`.

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
| `SEMANTIC_MCP_STARTUP_MODE` | `cache_first` | `cache_first` reuses existing cache on restart; `full` always refreshes from SQL Server before serving |
| `SEMANTIC_MCP_BACKGROUND_BATCH_SIZE` | `5` | Tables processed per background batch |
| `SEMANTIC_MCP_BACKGROUND_INTERVAL_MS` | `500` | Delay between batches |
| `SEMANTIC_MCP_POLICY_FILE` | *(builtin readonly)* | Path to policy JSON |
| `SEMANTIC_MCP_POLICY_PROFILE` | *(file's active_profile)* | Override which profile is active |
| `SEMANTIC_MCP_MAX_ROWS_RETURNED` | `1000` | Override SELECT row cap |
| `SEMANTIC_MCP_MAX_ROWS_AFFECTED` | `100` | Override DML affected-row cap |
| `SEMANTIC_MCP_QUERY_TIMEOUT` | `30` | Query timeout in seconds |
| `SEMANTIC_MCP_TOOL_PROFILE` | `all` | Comma-separated tool groups: metadata, relationship, semantic, object, query, policy, cache, metrics, workflow |
| `SEMANTIC_MCP_WORKFLOW_TOOLS_ENABLED` | `true` | Disable workflow-layer shortcut tools |
| `SEMANTIC_MCP_METRICS_ENABLED` | `true` | Enable per-tool response size metrics |
| `SEMANTIC_MCP_DEFAULT_DETAIL` | `brief` | Default detail tier for agent-facing tools |
| `SEMANTIC_MCP_DEFAULT_RESPONSE_MODE` | `summary` | Default query execution response shape |
| `SEMANTIC_MCP_DEFAULT_TOKEN_BUDGET_HINT` | `low` | Default sampling budget for query payloads |
| `SEMANTIC_MCP_DIRECT_EXECUTE_ENABLED` | `true` | Allow workflow fast-path direct execution when policy approves |
| `SEMANTIC_MCP_STRICT_ROWS_AFFECTED_CAP` | `true` | Roll back writes that exceed affected-row cap by default |
| `SEMANTIC_MCP_INTENT_ANALYZER` | `regex` | SQL intent analyzer backend (`regex` or `ast`) |

---

## Connection Scenarios

Copy the relevant block into your `.env` file (or into the `env` map in your MCP client config).

### SQL Authentication (default)

The most common setup. SQL Server Authentication must be enabled on the instance.

```env
SEMANTIC_MCP_MSSQL_SERVER=localhost
SEMANTIC_MCP_MSSQL_DATABASE=YourDatabase
SEMANTIC_MCP_MSSQL_USER=sa
SEMANTIC_MCP_MSSQL_PASSWORD=YourPassword
```

### Windows Authentication

Omit `MSSQL_USER` and `MSSQL_PASSWORD`; the process must run under a Windows account that has SQL Server access. Use double-backslash for named instances in `.env` files.

```env
SEMANTIC_MCP_MSSQL_SERVER=MY-PC\\SQLEXPRESS
SEMANTIC_MCP_MSSQL_DATABASE=YourDatabase
SEMANTIC_MCP_MSSQL_WINDOWS_AUTH=true
```

> Windows Authentication is only available on Windows. pymssql does not support it on Linux or macOS — use SQL Authentication on those platforms.

### Azure SQL Database

TLS is automatically enabled when the server name ends in `.database.windows.net`; you do not need to set `MSSQL_ENCRYPT` explicitly.

```env
SEMANTIC_MCP_MSSQL_SERVER=yourserver.database.windows.net
SEMANTIC_MCP_MSSQL_DATABASE=YourDatabase
SEMANTIC_MCP_MSSQL_USER=youradmin@yourserver
SEMANTIC_MCP_MSSQL_PASSWORD=YourPassword
```

### LocalDB (Windows only)

LocalDB communicates over a named pipe — no TCP port is required. Windows Authentication is used by default.

```env
SEMANTIC_MCP_MSSQL_SERVER=(localdb)\MSSQLLocalDB
SEMANTIC_MCP_MSSQL_DATABASE=YourDatabase
SEMANTIC_MCP_MSSQL_WINDOWS_AUTH=true
```

### Custom Policy File

Point `SEMANTIC_MCP_POLICY_FILE` at a JSON policy file you control. Without this setting the server operates in built-in read-only mode.

```env
SEMANTIC_MCP_POLICY_FILE=./config/policy.example.json
SEMANTIC_MCP_POLICY_PROFILE=read_write_safe
```

See [Policy System](#policy-system) for the full policy file format and available profiles.

### Custom Cache Location

Useful when running multiple server instances against different databases, or when the default `./cache/` directory is not writable.

```env
SEMANTIC_MCP_CACHE_PATH=/var/lib/sqlserver-mcp/mydb.db
```

---

## Policy System

**Default security posture:** if no policy file is configured, the server operates in built-in **read-only** mode by default — no configuration needed to enforce it. In this mode: only `SELECT` statements are permitted, results are capped at 1000 rows, multi-statement queries are rejected, and every query still passes through the policy enforcer before reaching `cursor.execute()`. No unrestricted SQL execution path exists.

To enable writes or change any constraint, create a policy JSON file and point `SEMANTIC_MCP_POLICY_FILE` at it (see `config/policy.example.json`):

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

### Profile quick reference

| Profile | SELECT | INSERT | UPDATE | DELETE | WHERE required | Row cap |
|---|---|---|---|---|---|---|
| `readonly` (builtin default) | Yes | No | No | No | N/A | 1000 returned |
| `read_write_safe` | Yes | Yes | Yes | No | UPDATE requires WHERE | 100 affected |
| `admin` | Yes | Yes | Yes | Yes | No | 10 000 affected |

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

Current tool groups:

- `metadata` (3): `get_tables`, `describe_table`, `get_columns`
- `relationship` (3): `get_table_relationships`, `find_join_path`, `get_dependency_chain`
- `semantic` (3): `classify_table`, `analyze_columns`, `detect_lookup_tables`
- `object` (3): `describe_view`, `describe_procedure`, `trace_object_dependencies`
- `query` (5): `validate_query`, `run_safe_query`, `plan_or_execute_query`, `preview_safe_query`, `estimate_execution_risk`
- `policy` (3): `get_execution_policy`, `validate_sql_against_policy`, `refresh_policy`
- `cache` (1): `refresh_schema_cache`
- `metrics` (2): `get_tool_metrics`, `reset_tool_metrics`
- `workflow` (6): `discover_relevant_tables`, `suggest_next_tool`, `bundle_context_for_next_step`, `score_join_candidate`, `summarize_table_for_joining`, `summarize_object_for_impact`

For smaller prompts and faster discovery, prefer the workflow tools plus `detail="brief"` and filtered metadata calls.

---

## MCP Resources

Auto-listed concrete resources:

- `semantic://summary/database`

Auto-listed resource templates:

- `semantic://schema/tables/{qualified}`
- `semantic://analysis/classification/{qualified}`
- `semantic://summary/table/{qualified}`
- `semantic://summary/object/{type}/{qualified}`
- `semantic://bundle/joining/{qualified}`

Backward-compatible direct reads are also supported for:

- `semantic://schema/tables`
- `semantic://analysis/dependencies/{type}/{schema}.{name}`

---

## Running the Server

**Via the installed console script** (after `pip install -e .`):

```bash
sqlserver-semantic-mcp
```

**Via uv (without installing):**

```bash
uv run python -m sqlserver_semantic_mcp.main
```

**Via Python directly** (when the package is already on `sys.path`):

```bash
python -m sqlserver_semantic_mcp.main
```

The server speaks MCP over stdio. On startup it:

1. Opens (or creates) the SQLite cache
2. Reuses the existing Structural cache when `SEMANTIC_MCP_STARTUP_MODE=cache_first`, otherwise refreshes from SQL Server
3. Enqueues all tables for Semantic analysis
4. Launches the background fill task
5. Accepts MCP tool/resource calls

Background fill uses exponential backoff (2ⁿ seconds, capped at 60s) on persistent errors to avoid log spam or CPU burn.

---

## Development

### Running tests

```bash
uv run --extra dev pytest tests/unit
uv run --extra dev pytest tests/integration -m integration
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

## Troubleshooting

### pymssql / FreeTDS installation fails on Linux

`pymssql` links against FreeTDS. On Debian/Ubuntu, install the required system libraries before running `pip install`:

```bash
sudo apt-get install -y libssl-dev libkrb5-dev freetds-dev
pip install pymssql
```

On Alpine / Docker: `apk add freetds-dev openssl-dev krb5-dev`.

### "Cannot open server" or connection refused

- Confirm the server name and port are correct (`SEMANTIC_MCP_MSSQL_SERVER`, `SEMANTIC_MCP_MSSQL_PORT`).
- Check that TCP/IP is enabled in SQL Server Configuration Manager.
- If using a named instance (e.g. `MY-PC\SQLEXPRESS`), confirm SQL Server Browser is running so the port can be resolved dynamically.
- If using a non-default port, set `SEMANTIC_MCP_MSSQL_PORT` explicitly — SQL Server Browser is not needed when the port is fixed.
- Check firewall rules: port 1433 (or your custom port) must be reachable from the machine running the MCP server.

### "Login failed for user"

- Confirm `SEMANTIC_MCP_MSSQL_USER` and `SEMANTIC_MCP_MSSQL_PASSWORD` are correct.
- Verify that SQL Server Authentication is enabled on the instance (Server Properties → Security → SQL Server and Windows Authentication mode).
- For Azure SQL, the user may need to be in the format `user@servername` depending on your driver version.

### Windows Authentication not working on Linux or macOS

pymssql does not support Windows Authentication (Kerberos/NTLM) on non-Windows platforms. Use SQL Authentication (`MSSQL_USER` + `MSSQL_PASSWORD`) instead. `SEMANTIC_MCP_MSSQL_WINDOWS_AUTH=true` is only effective on Windows.

### LocalDB not connecting

- LocalDB is Windows-only and communicates over a named pipe, not TCP.
- Use the exact format `(localdb)\MSSQLLocalDB` (or your instance name) for `SEMANTIC_MCP_MSSQL_SERVER`.
- Set `SEMANTIC_MCP_MSSQL_WINDOWS_AUTH=true`; SQL auth is not supported by LocalDB by default.
- Run `sqllocaldb info` in a Windows terminal to list available instances and confirm they are running.

### Policy file not found or ignored

When the policy file cannot be read (missing, unreadable, or invalid JSON), the server falls back to built-in read-only mode and logs a warning. Check the startup logs for lines containing `policy`. If `SEMANTIC_MCP_POLICY_FILE` is set to a relative path, it is resolved from the process working directory — use an absolute path to avoid ambiguity.

### Server starts but tools return empty results

The Structural Cache may not have been populated yet. Check the startup logs for warmup progress. You can force a full refresh with the `refresh_schema_cache` MCP tool. Also verify that the connected database user has `VIEW DEFINITION` permission; without it, object definitions and comments will be absent from the cache.

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
