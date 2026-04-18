# P2+P3 MCP Surface Slimming & Server-Side Summarization — Design Spec

**Date:** 2026-04-19
**Target release:** v0.4.0
**Baseline:** v0.3.0 (commit 8abf113, post-P1)

---

## 1. Goal & Scope

Two complementary moves:

- **P2 (surface slimming):** Expose fewer tools per deployment so `list_tools` stops paying prompt-cost for capabilities a given agent doesn't use. Remove resource/tool duplication.
- **P3 (server-side summarization):** Add task-focused tools that return *reasoning-ready* shapes (e.g. "how do I join this table?"), and upgrade `describe_view`/`describe_procedure` to split dependencies into **read** vs **write** sets.

**In scope:**

1. **Tool profile** via env var `SEMANTIC_MCP_TOOL_PROFILE` — comma-separated list from `{metadata, relationship, semantic, object, query, policy, cache}`. Default `all`.
2. **Resource dedup** — drop `semantic://schema/tables` concrete resource (duplicates `get_tables` tool, now with filters). Keep the two `ResourceTemplate`s and `semantic://summary/database`.
3. **New tool `summarize_table_for_joining(schema, table)`** — returns `{table, pk, classification, join_candidates, common_filter_columns}` suitable for agents deciding a join strategy.
4. **Write-intent `affected_tables`** — reuse `policy.analyzer` regex intent analysis on an object's `definition` to split `depends_on` into `read_tables` vs `write_tables`. Expose via `describe_view`/`describe_procedure` at `detail=standard`/`full`.

**Out of scope:**

| Item | Deferred to |
|---|---|
| `summarize_object_for_impact_analysis` new tool | Future polish |
| Tool description/inputSchema prose trimming | Future polish |
| `response_bytes` / `calls_per_task` instrumentation | P4 |

---

## 2. Architecture

### 2.1 Tool profile gating

- Add `tool_profile: str = "all"` to `Config`.
- `server/tools/__init__.py:register_all` parses the profile into a set of group names, validates against the known universe, and invokes `register()` only for allowed groups.
- Unknown profile tokens raise `ValueError` at startup (fail-fast surfaces misconfiguration).
- `"all"` is the sentinel for "register everything" (legacy behavior).

### 2.2 Resource dedup

`semantic://schema/tables` resource duplicated the `get_tables` tool output. With filters now on the tool, the resource is strictly less useful. Remove it. Keep:
- `semantic://summary/database` (no tool equivalent)
- `ResourceTemplate semantic://schema/tables/{qualified}` (parameterized — template uses `describe_table` under the hood via `read_resource`)
- `ResourceTemplate semantic://analysis/classification/{qualified}`

### 2.3 `summarize_table_for_joining`

New tool in the `semantic` group. Returns:

```json
{
  "table": "dbo.Orders",
  "pk": ["Id"],
  "classification": "fact",
  "join_candidates": [
    {"via_column": "UserId",    "to_table": "dbo.Users",  "to_column": "Id"},
    {"via_column": "ProductId", "to_table": "dbo.Product", "to_column": "Id"}
  ],
  "common_filter_columns": ["Status", "CreatedAt", "DeletedAt"]
}
```

**Heuristic:**
- `join_candidates` = outbound FK edges (one entry per FK, with source/target columns).
- `common_filter_columns` = columns with semantic tag in `{"status", "type", "audit_timestamp", "soft_delete"}` — the agent's typical filter targets.

### 2.4 Write-intent `affected_tables`

Currently `object_service.describe_object` populates `affected_tables` as "the subset of depends_on that are TABLE objects" — which is naming-wise misleading (it's all table dependencies, not just write targets).

Upgrade:
- On cache miss, after fetching definition, call `policy.analyzer.analyze_sql(definition)` (reuse existing intent analyzer).
- Collect `UPDATE`/`INSERT`/`DELETE`/`MERGE`/`TRUNCATE`/`EXEC` target tables into `write_tables`.
- Collect `SELECT`/`FROM`/`JOIN` targets into `read_tables`.
- Keep `affected_tables` as an alias for `write_tables` for backward compat; add the new `read_tables` / `write_tables` keys.
- Works for `PROCEDURE` and `FUNCTION`; views have no writes, so their `write_tables` is always `[]`.

**Error handling:** if SQL parse fails, fall back to the existing naïve behavior (`affected_tables = depends_on`), set `write_tables = []`, `read_tables = depends_on`. Log a warning.

---

## 3. File Touch Points

| File | Change |
|---|---|
| `sqlserver_semantic_mcp/config.py` | add `tool_profile: str = "all"` |
| `sqlserver_semantic_mcp/server/tools/__init__.py` | gate `register_all()` by profile set |
| `sqlserver_semantic_mcp/server/resources/schema.py` | remove `semantic://schema/tables` concrete `Resource`; keep template + summary |
| `sqlserver_semantic_mcp/services/object_service.py` | split `dependencies` into `read_tables`/`write_tables`/`affected_tables` using intent analyzer |
| `sqlserver_semantic_mcp/server/tools/shape.py` | `project_describe_object` includes `read_tables`/`write_tables` at standard/full |
| `sqlserver_semantic_mcp/services/semantic_service.py` | new `summarize_for_joining(schema, table)` |
| `sqlserver_semantic_mcp/server/tools/semantic.py` | register new tool |
| `tests/unit/test_tool_profile.py` | **new** — profile gating cases |
| `tests/unit/test_list_resources.py` | update to expect 1 concrete resource |
| `tests/unit/test_summarize_joining.py` | **new** — heuristic cases |
| `tests/unit/test_object_write_intent.py` | **new** — read/write split |

---

## 4. Testing Strategy

### 4.1 Profile gating (`test_tool_profile.py`)

- Default (no env / `all`): all groups registered.
- `metadata,semantic`: only 3+3 tools from those groups registered.
- `bogus-group`: startup raises with a clear error message.
- Empty string: treated same as `all`.

### 4.2 Resource dedup (`test_list_resources.py` updated)

- `list_resources()` returns **1** concrete resource (summary) and **2** templates.

### 4.3 Summarize for joining (`test_summarize_joining.py`)

- Table with 2 FKs and a `Status` column → `join_candidates` has 2 entries, `common_filter_columns` contains `Status`.
- Table with no FKs → `join_candidates: []`.
- Table with audit columns → `common_filter_columns` includes `CreatedAt`.
- Non-existent table → returns `None`.

### 4.4 Write-intent (`test_object_write_intent.py`)

- `CREATE PROCEDURE ... AS UPDATE T SET x=1 ...` → `write_tables = ["T"]`, `read_tables` contains none.
- `CREATE VIEW ... AS SELECT * FROM T JOIN U ON ...` → `write_tables = []`, `read_tables = ["T", "U"]`.
- Procedure with both SELECT and UPDATE → populated both ways.
- Parse failure → falls back with warning; `read_tables = depends_on`.

---

## 5. Risk & Rollback

**Breaking change:** Removing `semantic://schema/tables` resource breaks agents that enumerated it. Mitigation: `get_tables` tool covers this with more flexibility.

**Tool profile:** opt-in (default preserves all). Zero risk unless operator sets an invalid profile (caught at startup).

**SQL intent on views:** the policy analyzer is regex-based; known false-positives exist for dynamic SQL or CTEs. Fallback behavior documented above.

**Rollback:** all changes revertable per-commit; no cache schema change.

---

## 6. Success Criteria

- [ ] `test_tool_profile.py` — all cases pass, profile gating respects config.
- [ ] `test_list_resources.py` — returns 1 concrete + 2 templates.
- [ ] `test_summarize_joining.py` — heuristic cases pass.
- [ ] `test_object_write_intent.py` — read/write split works for views and procedures.
- [ ] Full unit suite — 0 failures.
- [ ] `pyproject.toml` + README badges → 0.4.0.
- [ ] Commits pushed to `origin/main`.
