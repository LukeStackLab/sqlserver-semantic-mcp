# P0 Token Optimization — Design Spec

**Date:** 2026-04-19
**Target release:** v0.2.0
**Baseline:** v0.1.0 (commit 25c0615)

---

## 1. Goal & Scope

Reduce default MCP tool response payload size by an estimated **40–70%** without changing tool interfaces or database shape, and collapse `list_resources` from `O(tables × 2)` to a constant **4 entries**.

**In scope (P0):**

1. Remove `indent=2` pretty-printing from tool responses.
2. Strip `None`, `[]`, `{}`, `False` (with whitelist) from responses.
3. Merge identifier pairs: `{schema_name, table_name, …}` → `{table: "<schema>.<table>", …}`; `{schema, object_name, object_type, …}` → `{object: "<schema>.<name>", type: <object_type>, …}`.
4. Make `describe_view` / `describe_procedure` default-omit the SQL `definition` field; return `definition_hash` + `definition_bytes` instead. Opt-in via `include_definition: bool = False`.
5. Collapse `list_resources` to 2 concrete `Resource`s + 2 `ResourceTemplate`s.

**Explicitly out of scope (deferred):**

| Item | Deferred to | Reason |
|---|---|---|
| `detail=brief/standard/full` tiered opt-in | P1 | Response contract reset, not pure shape slimming |
| Tool-side filters (`confidence_min`, `keyword`, `schema`) | P1 | Query-shape expansion, not payload slimming |
| Tool profiles (metadata-only / semantic-only) | P2 | Deployment-layer concern |
| `affected_tables` write-intent analysis + short summary | P3 | Requires server-side summarization / SQL intent analysis |
| `response_bytes` / `calls_per_task` instrumentation | P4 | Measurement framework, separate delivery |

---

## 2. Architecture

Single new module, one ~3-line edit to the tool dispatcher, one rewrite of the resource listing function.

### 2.1 New: `sqlserver_semantic_mcp/server/compact.py`

Pure, stateless function operating on already-built dicts returned by services:

```python
def compact(obj: Any) -> Any: ...
```

**Rules (applied recursively):**

| Rule | Behavior |
|---|---|
| **R1 — drop falsy** | Remove keys whose value is `None`, `[]`, `{}`, or `False` — *except* keys listed in `NULLABLE_FALSE_KEEP = {"is_nullable"}`. |
| **R2 — merge table id** | When a dict contains both `schema_name` and `table_name`, replace them with a single `table` key whose value is `"<schema_name>.<table_name>"`. Preserves insertion order: `table` takes the position of the first of the two original keys. |
| **R3 — merge object id** | When a dict contains `schema` + `object_name`, replace them with a single `object` key valued `"<schema>.<object_name>"`. If `object_type` is also present, rename it to `type`. Preserves position. |
| **R4 — definition strip** | (Applied at the service/tool layer, not by `compact`.) When `include_definition=False`, remove `definition` and add `definition_hash` (SHA-1 hex, first 8 chars) + `definition_bytes` (len of UTF-8 encoding). |

**Rule application order (within each dict):** R2 → R3 → R1. Identifier merges run first so that R1 doesn't strip `None`-valued identifier fields before they can be merged. (In practice identifiers are always non-empty strings; this just makes the semantics robust.)

**Defensive guards:**

- R2 triggers only when both `schema_name` and `table_name` are non-empty strings. If either is missing, `None`, or empty, the dict is left untouched and R1 handles cleanup.
- R3 triggers only when `schema` and `object_name` are both non-empty strings.

**Recursion:** `compact` descends into `list` and `dict` values. Non-container leaves are returned as-is.

**Ordering:** Must preserve dict key order. Python 3.7+ dicts are insertion-ordered; we rely on that.

### 2.2 Edit: `sqlserver_semantic_mcp/server/app.py`

In `_call_tool` (currently line 53–66):

```python
# Before
text=json.dumps(result, ensure_ascii=False, indent=2, default=str),

# After
text=json.dumps(compact(result), ensure_ascii=False, default=str, separators=(",", ":")),
```

The error branch (when tool raises) is **not** routed through `compact` — raw `{"error": "..."}` preserves debugging fidelity.

### 2.3 Rewrite: `sqlserver_semantic_mcp/server/resources/schema.py:list_resources`

Replace the per-table loop with:

```python
resources = [
    Resource(uri=AnyUrl("semantic://schema/tables"),     name="All tables",        mimeType="application/json"),
    Resource(uri=AnyUrl("semantic://summary/database"),  name="Database summary",  mimeType="application/json"),
]
templates = [
    ResourceTemplate(uriTemplate="semantic://schema/tables/{qualified}",
                     name="Table metadata",       mimeType="application/json"),
    ResourceTemplate(uriTemplate="semantic://analysis/classification/{qualified}",
                     name="Table classification", mimeType="application/json"),
]
return resources  # concrete list (templates exposed separately if SDK supports list_resource_templates)
```

**SDK check required:** the `mcp` Python SDK may expose `ResourceTemplate` via a separate `list_resource_templates` handler rather than returning them in `list_resources`. Implementation plan must verify and fall back to Approach A (concrete only, no per-table at all) if template support is missing.

### 2.4 Edit: `sqlserver_semantic_mcp/server/tools/object_tool.py`

Add `include_definition: bool = False` parameter to both `describe_view` and `describe_procedure`. In the tool handler, compute `definition_hash` and `definition_bytes` from the full definition, and:

- default path: return `{..., definition_hash, definition_bytes}` without `definition`
- `include_definition=True`: return `{..., definition, definition_hash, definition_bytes}`

R4 logic lives here (not in `compact`) so that the service layer (`object_service.describe_object`) continues to return the full cached row unchanged — callers wanting raw access stay unaffected.

---

## 3. Response Shape Contract

### 3.1 `get_tables`

**Before**
```json
[
  {"schema_name":"dbo","table_name":"Users","type":"USER_TABLE","description":null},
  {"schema_name":"dbo","table_name":"Orders","type":"USER_TABLE","description":"orders"}
]
```

**After**
```json
[{"table":"dbo.Users","type":"USER_TABLE"},{"table":"dbo.Orders","type":"USER_TABLE","description":"orders"}]
```

### 3.2 `describe_table`

**Before** — Pretty-printed, includes empty `indexes: []`, null `description`, two-part identifier, `is_nullable: false` on every non-nullable column.

**After**
```json
{"table":"dbo.Users","columns":[{"name":"Id","type":"int","is_nullable":false},{"name":"Email","type":"nvarchar(255)","description":"login email"}],"primary_keys":["Id"],"foreign_keys":[{"column":"OrgId","references":"dbo.Org.Id"}]}
```

`is_nullable: false` is **preserved** (whitelisted) — stripping it would force agents to assume a default, and SQL's actual default is `NULL` allowed, which would mislead on PK/NOT NULL columns.

### 3.3 `describe_view` / `describe_procedure`

**Before** — Returns full cached row including the entire `definition` SQL text (often multi-KB).

**After** (default, `include_definition=False`)
```json
{"object":"dbo.usp_CloseOrder","type":"PROCEDURE","depends_on":["sales.Orders","sales.OrderItems"],"definition_hash":"8c2fab3d","definition_bytes":2847}
```

**With `include_definition=True`**
```json
{"object":"dbo.usp_CloseOrder","type":"PROCEDURE","depends_on":["sales.Orders","sales.OrderItems"],"definition":"CREATE PROCEDURE ...","definition_hash":"8c2fab3d","definition_bytes":2847}
```

### 3.4 `list_resources`

Constant 2 + 2 (templates), regardless of table count:

```json
{"resources":[
  {"uri":"semantic://schema/tables","name":"All tables","mimeType":"application/json"},
  {"uri":"semantic://summary/database","name":"Database summary","mimeType":"application/json"}
],"resourceTemplates":[
  {"uriTemplate":"semantic://schema/tables/{qualified}","name":"Table metadata","mimeType":"application/json"},
  {"uriTemplate":"semantic://analysis/classification/{qualified}","name":"Table classification","mimeType":"application/json"}
]}
```

(Actual serialization is driven by the MCP SDK; shape above is conceptual.)

---

## 4. File Touch Points

| File | Change |
|---|---|
| `sqlserver_semantic_mcp/server/compact.py` | **new** — pure function + `NULLABLE_FALSE_KEEP` constant |
| `sqlserver_semantic_mcp/server/app.py` | edit `_call_tool`: drop `indent=2`, apply `compact()`, use `separators=(",", ":")` |
| `sqlserver_semantic_mcp/server/resources/schema.py` | rewrite `list_resources`; possibly add `list_resource_templates` if SDK requires |
| `sqlserver_semantic_mcp/server/tools/object_tool.py` | add `include_definition` param + hash/bytes computation |
| `tests/unit/test_compact.py` | **new** — R1–R3 rules + golden-size assertion + ordering preservation |
| `tests/unit/test_server_wiring.py` | update shape assertions if they hard-code old fields |
| `tests/unit/test_object_service.py` | add `include_definition=False/True` cases |

---

## 5. Testing Strategy

### 5.1 `test_compact.py` — required cases

1. **R1** — `compact({"a":1,"b":None,"c":[],"d":{},"e":False})` == `{"a":1}`
2. **R1 whitelist** — `compact({"is_nullable":False,"default_value":False})` == `{"is_nullable":False}` (default_value is stripped, is_nullable retained)
3. **R2 merge** — `compact({"schema_name":"dbo","table_name":"Users","type":"USER_TABLE"})` == `{"table":"dbo.Users","type":"USER_TABLE"}`
4. **R3 merge** — `compact({"schema":"dbo","object_name":"vw_x","object_type":"VIEW","depends_on":[]})` == `{"object":"dbo.vw_x","type":"VIEW"}` (R3 merges identifiers; R1 then strips empty list)
5. **R2 guard** — if `table_name=None` or `""`, the dict is NOT merged, and R1 strips the null/empty afterwards
6. **Recursion** — nested lists of dicts and dict-of-dicts apply all rules
7. **Key order preserved** — merged `table`/`object` appears at the position of the first replaced key
8. **Golden size** — JSON-serialize a mocked `describe_table` fixture (before vs. after). Assert `after_size < 0.7 * before_size` (≥30% reduction).

### 5.2 Integration-level

Existing integration tests unchanged. `compact()` only executes at the `_call_tool` transport boundary; service-layer return shapes are not re-validated through the tool layer in integration tests.

### 5.3 Regression guard

`test_server_wiring.py` — if it currently asserts presence of `schema_name` / `table_name` in a decoded tool response, update to assert `table`.

---

## 6. Risk & Rollback

**Risk — breaking change to response shape.** Any consumer hard-coding `schema_name` / `table_name` / `schema` / `object_name` / `definition` on default responses will break.

**Mitigation:**

- v0.1.0 shipped hours before this change; repo has no external consumers.
- Treated as acceptable breaking change. Version bumped to **0.2.0**.
- Release notes explicitly list the shape contract change.

**Rollback:**

All compact logic is concentrated in two places (`compact.py` + the 1-line `_call_tool` wiring). `git revert` of the P0 commit restores full v0.1.0 behavior. No database migration or cache-format change is involved.

**Latent risk — SDK template support.** If the installed `mcp` SDK version doesn't expose `ResourceTemplate` symmetrically, fall back to returning only the 2 concrete resources (no per-table, no templates). Agents must then call `get_tables` tool for discovery. This degradation is acceptable; implementation plan verifies SDK capability first.

---

## 7. Success Criteria

P0 ships when **all** of the following hold:

- [ ] `test_compact.py` — all rule cases pass; golden-size test asserts ≥30% reduction on `describe_table` fixture.
- [ ] Full unit suite (`pytest tests/unit`) — 0 failures.
- [ ] `describe_view` / `describe_procedure` default response omits `definition`; `include_definition=True` restores it.
- [ ] `list_resources` returns a constant-size list irrespective of database table count.
- [ ] Version in `pyproject.toml` and README badges updated to 0.2.0.
- [ ] Commit pushed to `origin/main`.
