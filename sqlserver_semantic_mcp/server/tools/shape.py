"""Detail-tier projection helpers for P1 response contract reset.

See docs/superpowers/specs/2026-04-19-p1-response-contract-reset-design.md.
"""
from typing import Any, Optional

VALID_DETAILS: frozenset[str] = frozenset({"brief", "standard", "full"})

_IMPORTANT_COLS_CAP = 8


class DetailError(ValueError):
    """Raised when an invalid `detail` value is passed."""


def resolve_detail(args: dict) -> str:
    val = args.get("detail", "brief")
    if val not in VALID_DETAILS:
        raise DetailError(
            f"invalid detail '{val}'; expected one of {sorted(VALID_DETAILS)}"
        )
    return val


def _important_columns(
    columns: list[dict], pk: list[str], fks: list[dict],
    semantic_map: dict[str, str],
) -> list[str]:
    seen: set[str] = set()
    order: list[str] = []

    def push(name: str) -> None:
        if name in seen or name is None:
            return
        seen.add(name)
        order.append(name)
        if len(order) >= _IMPORTANT_COLS_CAP:
            raise StopIteration

    try:
        for name in pk:
            push(name)
        for fk in fks:
            push(fk.get("column_name"))
        # columns with a non-generic semantic tag, in ordinal order
        for col in columns:
            name = col["column_name"]
            sem = semantic_map.get(name)
            if sem and sem != "generic":
                push(name)
        # fill remaining with next columns in ordinal order
        for col in columns:
            push(col["column_name"])
    except StopIteration:
        pass

    return order[:_IMPORTANT_COLS_CAP]


def project_describe_table(
    full: dict, detail: str,
    classification: Optional[dict],
    column_semantics: dict[str, str],
) -> dict:
    schema = full.get("schema_name", "")
    table = full.get("table_name", "")
    columns = full.get("columns", [])
    pk = full.get("primary_key", []) or []
    fks = full.get("foreign_keys", []) or []
    cls_type = (classification or {}).get("type", "unknown")

    fk_to = sorted({
        f"{fk.get('ref_schema')}.{fk.get('ref_table')}"
        for fk in fks
        if fk.get("ref_schema") and fk.get("ref_table")
    })

    brief: dict[str, Any] = {
        "table": f"{schema}.{table}",
        "column_count": len(columns),
        "pk": list(pk),
        "fk_to": fk_to,
        "important_columns": _important_columns(columns, pk, fks, column_semantics),
        "classification": cls_type,
    }
    if detail == "brief":
        return brief

    # standard: brief + full columns (name/type/nullable) + full FK rows
    standard_cols = [
        {"name": c["column_name"], "type": c.get("data_type"),
         "is_nullable": bool(c.get("is_nullable"))}
        for c in columns
    ]
    standard: dict[str, Any] = {
        **brief,
        "columns": standard_cols,
        "foreign_keys": list(fks),
    }
    if detail == "standard":
        return standard

    # full: standard + indexes + description + per-column default_value + description
    full_cols = []
    for c in columns:
        full_cols.append({
            "name": c["column_name"],
            "type": c.get("data_type"),
            "is_nullable": bool(c.get("is_nullable")),
            "max_length": c.get("max_length"),
            "default_value": c.get("default_value"),
            "description": c.get("description"),
        })
    return {
        **brief,
        "columns": full_cols,
        "foreign_keys": list(fks),
        "indexes": full.get("indexes", []),
        "description": full.get("description"),
    }


def project_get_columns(
    columns: list[dict], detail: str,
    semantic_map: dict[str, str],
) -> list[dict]:
    def semantic_for(name: str) -> str:
        return semantic_map.get(name) or "generic"

    if detail == "brief":
        return [
            {"name": c["column_name"], "semantic": semantic_for(c["column_name"])}
            for c in columns
        ]
    if detail == "standard":
        return [
            {"name": c["column_name"], "type": c.get("data_type"),
             "is_nullable": bool(c.get("is_nullable")),
             "semantic": semantic_for(c["column_name"])}
            for c in columns
        ]
    # full
    return [
        {"name": c["column_name"], "type": c.get("data_type"),
         "max_length": c.get("max_length"),
         "is_nullable": bool(c.get("is_nullable")),
         "default_value": c.get("default_value"),
         "description": c.get("description"),
         "semantic": semantic_for(c["column_name"])}
        for c in columns
    ]


def project_classify(classification: dict, detail: str) -> dict:
    if detail == "brief":
        return {
            "type": classification.get("type"),
            "confidence": classification.get("confidence"),
        }
    return dict(classification)


def project_describe_object(
    obj: dict, detail: str, include_definition: bool,
) -> dict:
    schema = obj.get("schema", "")
    name = obj.get("object_name", "")
    obj_type = obj.get("object_type") or obj.get("type")

    brief: dict[str, Any] = {
        "object": f"{schema}.{name}",
        "type": obj_type,
        "depends_on": list(obj.get("dependencies", []) or []),
        "definition_bytes": obj.get("definition_bytes"),
    }
    if obj.get("status") == "error":
        brief["status"] = "error"
        brief["error_message"] = obj.get("error_message")

    # include_definition explicit true overrides brief
    if detail == "brief":
        if include_definition and obj.get("definition"):
            brief["definition"] = obj["definition"]
            brief["definition_hash"] = obj.get("definition_hash")
        return brief

    # standard / full share more fields
    standard: dict[str, Any] = {
        **brief,
        "definition_hash": obj.get("definition_hash"),
        "read_tables": list(obj.get("read_tables", []) or []),
        "write_tables": list(obj.get("write_tables", []) or []),
        "affected_tables": list(obj.get("affected_tables", []) or []),
        "description": obj.get("description"),
        "status": obj.get("status"),
    }

    if detail == "standard":
        if include_definition and obj.get("definition"):
            standard["definition"] = obj["definition"]
        return standard

    # full: always include definition
    return {**standard, "definition": obj.get("definition")}
