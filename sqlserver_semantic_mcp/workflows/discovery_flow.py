"""Discovery path — narrows the candidate set before explore/describe."""
from __future__ import annotations

from typing import Optional

from ..config import Config, get_config
from ..services import metadata_service, semantic_service
from .contracts import ToolEnvelope


_STOPWORDS = {
    "the", "a", "an", "of", "to", "and", "or", "for", "on", "in", "by",
    "with", "is", "are", "what", "which", "how", "show", "list", "me",
    "my", "our", "their", "please", "need", "want", "find",
}


def _tokenize(goal: str) -> list[str]:
    if not goal:
        return []
    tokens = [t.lower().strip(".,;:!?()[]{}\"'`") for t in goal.split()]
    return [t for t in tokens if t and t not in _STOPWORDS and len(t) > 1]


def _score(table: dict, tokens: list[str]) -> tuple[float, list[str]]:
    """Return (score, reasons) for a candidate table."""
    name = f"{table['schema_name']}.{table['table_name']}".lower()
    bare = table["table_name"].lower()
    reasons: list[str] = []
    score = 0.0

    for tok in tokens:
        if tok == bare:
            score += 0.6
            reasons.append(f"exact table match: {tok}")
        elif tok in bare:
            score += 0.35
            reasons.append(f"table name contains '{tok}'")
        elif tok in name:
            score += 0.2
            reasons.append(f"qualified name contains '{tok}'")

    return min(score, 1.0), reasons


async def discover_relevant_tables(
    goal: str,
    *,
    schemas: Optional[list[str]] = None,
    keyword: Optional[str] = None,
    limit: int = 10,
    classify: bool = False,
    cfg: Optional[Config] = None,
) -> dict:
    """Return a small ranked candidate set for a natural-language ask.

    The server intentionally stays dumb (keyword scoring only) so the
    response is cheap. Agents can follow up with ``describe_table`` (which
    includes classification at "brief" detail) for the short list, or pass
    ``classify=True`` here to attach classification inline.
    """
    cfg = cfg or get_config()
    db_path = cfg.cache_path
    database = cfg.mssql_database

    tokens = _tokenize(goal)
    if keyword and keyword.lower() not in tokens:
        tokens.append(keyword.lower())

    tables = await metadata_service.list_tables(
        db_path, database,
        schemas=schemas, keyword=keyword if keyword else None,
    )

    scored: list[dict] = []
    for t in tables:
        score, reasons = _score(t, tokens)
        if score <= 0 and not keyword:
            continue
        scored.append({
            "table": f"{t['schema_name']}.{t['table_name']}",
            "schema": t["schema_name"],
            "name": t["table_name"],
            "score": round(score, 3),
            "why": reasons,
        })

    scored.sort(key=lambda x: x["score"], reverse=True)
    top = scored[:limit] if limit else scored

    if classify:
        for row in top:
            cls = await semantic_service.classify_table(
                db_path, database, row["schema"], row["name"],
            )
            row["classification"] = cls.get("type")
            row["classification_confidence"] = cls.get("confidence")

    return ToolEnvelope(
        kind="discover_relevant_tables",
        detail="brief",
        next_action=(
            "describe_table" if top else "broaden_search"
        ),
        recommended_tool=(
            "describe_table" if top else "get_tables"
        ),
        data={
            "goal": goal,
            "token_hits": tokens,
            "total_scanned": len(tables),
            "candidates": [
                {k: v for k, v in row.items() if k not in ("schema", "name")}
                for row in top
            ],
        },
    ).to_dict()
