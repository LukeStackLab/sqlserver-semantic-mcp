# P1 Response Contract Reset — Design Spec

**Date:** 2026-04-19
**Target release:** v0.3.0
**Baseline:** v0.2.0 (commit 571007a, post-P0)

---

## 1. Goal & Scope

Introduce tiered response shapes on **heavy tools** via a `detail` parameter (`brief` | `standard` | `full`, default `brief`), and add **filter parameters** to list-type tools so agents don't receive whole-database dumps as a first resort.

**In scope:**

1. **`detail` parameter on heavy tools** — `describe_table`, `get_columns`, `describe_view`, `describe_procedure`, `classify_table`.
2. **Filter parameters on list tools** — `schema` / `keyword` on `get_tables` and `detect_lookup_tables`; `confidence_min` on `detect_lookup_tables`; `schema` on `get_dependency_chain`.
3. **Brief shape contracts** — concrete per-tool definitions below.
4. **Reconciliation with P0's `include_definition`** — `detail=full` implies `include_definition=true`; explicit `include_definition` still works as an override.

**Out of scope (deferred):**

| Item | Deferred to |
|---|---|
| Tool profile gating (metadata-only / semantic-only deployments) | P2 |
| `summarize_table_for_joining` / `summarize_object_for_impact_analysis` new tools | P3 |
| SQL intent analysis for `affected_tables` write-set | P3 |
| `response_bytes` / `calls_per_task` instrumentation | P4 |

---

## 2. Architecture

Each heavy tool handler reads `args["detail"]` (defaulting to `"brief"`), fetches the cached full response from its service, then applies a **tool-local projection function** to produce the requested shape. Filters are applied in-service (not post-hoc) where possible so the filter narrows the underlying query, not just the output.

- Default `detail` is `"brief"` — this is a breaking change from v0.2.0 full-shape default. Version bump to 0.3.0.
- Invalid `detail` values raise (rejected at tool-handler entry). Treat unknown values as hard error, not silent fallback — so agents notice typos.
- `detail` applies to tools listed in §1.1; other tools (policy, query, cache, metadata top-level like `get_tables`) ignore it.

**Projection lives in tool handlers**, not services, because:
- Services should return canonical full data; shaping is a presentation concern.
- P0's `compact()` continues to run afterwards at the transport layer.
- Future P3 summarization adds another projection layer without disturbing services.

---

## 3. Brief-Shape Contracts

### 3.1 `describe_table`

**brief (default):**
```json
{
  "table": "dbo.Users",
  "column_count": 12,
  "pk": ["Id"],
  "fk_to": ["dbo.Org", "dbo.Role"],
  "important_columns": ["Id", "OrgId", "Email", "Status", "CreatedAt"],
  "classification": "dimension"
}
```

`fk_to` is a deduplicated sorted list of qualified *target* tables (from `foreign_keys[].ref_schema.ref_table`).

`important_columns` heuristic (cap 8, order preserved):
1. All PK columns.
2. All FK source columns.
3. Columns with non-`generic` semantic tag (from `analyze_columns` cache if present) — capped at remaining slots.
4. Fill remaining slots with the next ordinal-position columns.

`classification` is the short type string (e.g. `"dimension"`); the full classification dict is not included at brief tier.

**standard:**
- Everything in brief, **plus** the full `columns` list (each: `{name, type, is_nullable}`), plus `foreign_keys` in full form.

**full:**
- Everything in standard, **plus** `indexes`, `description`, per-column `default_value` and `description`.

### 3.2 `get_columns`

**brief (default):**
```json
[{"name": "Id", "semantic": "generic"}, {"name": "CreatedAt", "semantic": "audit_timestamp"}]
```

**standard:**
```json
[{"name": "Id", "type": "int", "is_nullable": false, "semantic": "generic"}]
```

**full:**
```json
[{"name": "Id", "type": "int", "max_length": 4, "is_nullable": false, "default_value": null, "description": "primary key", "semantic": "generic"}]
```

Semantic tag comes from the same regex patterns `semantic_service._column_semantic` uses. If semantic analysis isn't cached, tool invokes it synchronously (cheap, regex-only).

### 3.3 `describe_view` / `describe_procedure`

**brief (default):**
```json
{"object": "dbo.vw_ActiveUsers", "type": "VIEW", "depends_on": ["dbo.Users"], "definition_bytes": 487}
```

`definition_hash` is dropped from brief (the byte-count is enough to know whether it changed in conjunction with semantic cache hash); restored in `standard`/`full`.

**standard:**
- Brief + `definition_hash`, `affected_tables`, `status`, `description`.

**full:**
- Standard + `definition` (equivalent to P0's `include_definition=true`).

**Reconciliation with P0 `include_definition`:**
- If caller passes `detail=full`, `include_definition` is treated as `true` regardless.
- If caller passes `include_definition=true` explicitly and `detail=brief`, the response is brief+`definition` (explicit override wins for that one field).
- If caller passes neither, default is `detail=brief`, no definition.

### 3.4 `classify_table`

**brief (default):**
```json
{"type": "dimension", "confidence": 0.5}
```

**standard:**
```json
{"type": "dimension", "confidence": 0.5, "reasons": ["few FKs with multiple descriptive columns"]}
```

**full:**
Same as standard (there is no further info today). `full` kept to preserve the three-tier contract consistency.

### 3.5 Tools NOT gaining `detail` in P1

- `get_tables` — already minimal after P0's compact step. Filters (below) reduce cardinality instead.
- `find_join_path` — output is already small (ordered list of edges).
- `trace_object_dependencies` — returns a flat list of strings.
- `get_table_relationships` — two small lists.
- `get_execution_policy`, `validate_*`, `run_safe_query`, `refresh_*` — policy/query/cache surface, not shape-heavy.

---

## 4. Filter Contracts

Filters apply at the service level (SQL-level `WHERE` or in-loop predicate), NOT post-response — so the expensive path is cut short.

### 4.1 `get_tables`

| Param | Type | Behavior |
|---|---|---|
| `schema` | string or list of strings, optional | Include only tables whose `schema_name` matches. If a list, any match. |
| `keyword` | string, optional | Case-insensitive substring match on the qualified name `schema_name.table_name`. |

Both can be combined (AND). Missing → no filter applied.

### 4.2 `detect_lookup_tables`

| Param | Type | Behavior |
|---|---|---|
| `schema` | string or list, optional | As above |
| `keyword` | string, optional | As above |
| `confidence_min` | float in `[0.0, 1.0]`, optional (default 0.0) | Exclude rows where `confidence < confidence_min`. |

### 4.3 `get_dependency_chain`

| Param | Type | Behavior |
|---|---|---|
| `schema` | string or list, optional | Limit the BFS frontier to nodes whose schema is in the allowed set. Starting table is always included even if outside the set. |

---

## 5. File Touch Points

| File | Change |
|---|---|
| `sqlserver_semantic_mcp/server/tools/metadata.py` | Add `detail` to `describe_table`/`get_columns` inputSchema; implement projection helpers; add `schema`/`keyword` to `get_tables` |
| `sqlserver_semantic_mcp/server/tools/object_tool.py` | Add `detail` to describe_view/procedure; reconcile with P0's `include_definition` |
| `sqlserver_semantic_mcp/server/tools/semantic.py` | Add `detail` to `classify_table`; add `schema`/`keyword`/`confidence_min` to `detect_lookup_tables` |
| `sqlserver_semantic_mcp/server/tools/relationship.py` | Add `schema` to `get_dependency_chain` |
| `sqlserver_semantic_mcp/services/metadata_service.py` | Accept optional filter kwargs in `list_tables` (pushes WHERE into SQL) |
| `sqlserver_semantic_mcp/services/semantic_service.py` | Accept filters in `detect_lookup_tables` |
| `sqlserver_semantic_mcp/services/relationship_service.py` | Accept `schema` kwarg in dependency chain walker |
| `sqlserver_semantic_mcp/server/tools/shape.py` | **new** — projection helpers + `resolve_detail(args)` + `validate_detail_value` |
| `tests/unit/test_tool_shapes.py` | **new** — brief/standard/full projections per tool |
| `tests/unit/test_tool_filters.py` | **new** — filter semantics |
| Existing tests | update as needed (default response shape is now brief) |

---

## 6. Testing Strategy

### 6.1 Projection helpers (`test_tool_shapes.py`)

Each heavy tool:
1. Build a mock service response (full dict).
2. Apply projection at each tier (`brief`, `standard`, `full`).
3. Assert exact key set + value shapes per §3.

Cases per tool × 3 tiers, plus:
- Invalid `detail` value raises a clear error.
- Missing `detail` defaults to `brief`.
- `describe_view` with `detail=brief` + `include_definition=true` includes `definition`.
- `describe_view` with `detail=full` + `include_definition=false` still includes `definition` (detail wins when it wants more).

### 6.2 Filters (`test_tool_filters.py`)

- `get_tables(schema="dbo")` returns only rows with `schema_name="dbo"`.
- `get_tables(schema=["dbo","sales"])` matches either.
- `get_tables(keyword="user")` case-insensitive substring on qualified name.
- Combined `schema` + `keyword` uses AND.
- `detect_lookup_tables(confidence_min=0.6)` excludes lower-confidence rows.
- `get_dependency_chain(schema="dbo")` stops at cross-schema FK edges.

### 6.3 Regression

Full unit suite must stay at 0 failures. Existing tool-level tests that asserted old full shapes must be updated to either:
- Pass `detail="full"` explicitly to preserve existing expectations, or
- Update assertions for the new brief default.

### 6.4 Golden size

Add golden-size assertion: a `describe_table(detail="brief")` response on a 12-column, 2-FK mocked table must be **<20% the size** of its `detail="full"` response.

---

## 7. Risk & Rollback

**Breaking change:** default shape changes from full (v0.2.0) to brief (v0.3.0). Agent prompts hard-coded to old field names break.

**Mitigation:**
- Bump to v0.3.0 — major semantic shift.
- Release notes enumerate shape contract changes.
- Agents can restore v0.2.0 behavior by passing `detail="full"` on every call (trivially scriptable migration).

**Rollback:** projection logic and filter predicates are strictly additive; reverting the P1 commit series restores v0.2.0.

---

## 8. Success Criteria

- [ ] `test_tool_shapes.py` — all projection cases pass for 5 heavy tools × 3 tiers.
- [ ] `test_tool_filters.py` — all filter cases pass.
- [ ] Golden size assertion on `describe_table` — brief <20% of full.
- [ ] Full unit suite — 0 failures.
- [ ] `pyproject.toml` + README badges → 0.3.0.
- [ ] Commits pushed to `origin/main`.
