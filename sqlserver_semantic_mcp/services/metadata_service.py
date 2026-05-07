from typing import Optional
import aiosqlite


async def _list_columns_from_db(
    db: aiosqlite.Connection,
    database: str,
    schema: str,
    table: str,
) -> list[dict]:
    cur = await db.execute(
        "SELECT column_name, data_type, max_length, is_nullable, "
        "column_default, ordinal_position "
        "FROM sc_columns "
        "WHERE database_name=? AND schema_name=? AND table_name=? "
        "ORDER BY ordinal_position",
        (database, schema, table),
    )
    cols = [dict(r) for r in await cur.fetchall()]

    cur = await db.execute(
        "SELECT column_name, description FROM sc_comments "
        "WHERE database_name=? AND schema_name=? AND object_name=? "
        "AND column_name<>''",
        (database, schema, table),
    )
    comments = {r["column_name"]: r["description"]
                for r in await cur.fetchall()}

    for c in cols:
        c["is_nullable"] = bool(c["is_nullable"])
        c["default_value"] = c.pop("column_default", None)
        c["description"] = comments.get(c["column_name"])
    return cols


async def list_tables(
    db_path: str, database: str, *,
    schemas: Optional[list[str]] = None,
    keyword: Optional[str] = None,
) -> list[dict]:
    sql = ("SELECT schema_name, table_name FROM sc_tables "
           "WHERE database_name = ?")
    params: list = [database]

    if schemas:
        placeholders = ",".join("?" for _ in schemas)
        sql += f" AND schema_name IN ({placeholders})"
        params.extend(schemas)

    if keyword:
        sql += (" AND (LOWER(schema_name || '.' || table_name) "
                "LIKE ? ESCAPE '\\')")
        kw = keyword.lower().replace("\\", "\\\\").replace("%", "\\%").replace("_", "\\_")
        params.append(f"%{kw}%")

    sql += " ORDER BY schema_name, table_name"

    async with aiosqlite.connect(db_path) as db:
        db.row_factory = aiosqlite.Row
        cur = await db.execute(sql, tuple(params))
        return [dict(r) for r in await cur.fetchall()]


async def list_columns(
    db_path: str, database: str, schema: str, table: str,
) -> list[dict]:
    async with aiosqlite.connect(db_path) as db:
        db.row_factory = aiosqlite.Row
        return await _list_columns_from_db(db, database, schema, table)


async def describe_table(
    db_path: str, database: str, schema: str, table: str,
) -> Optional[dict]:
    async with aiosqlite.connect(db_path) as db:
        db.row_factory = aiosqlite.Row
        cur = await db.execute(
            "SELECT 1 FROM sc_tables WHERE database_name=? "
            "AND schema_name=? AND table_name=?",
            (database, schema, table),
        )
        if not await cur.fetchone():
            return None

        columns = await _list_columns_from_db(db, database, schema, table)

        cur = await db.execute(
            "SELECT column_name FROM sc_primary_keys "
            "WHERE database_name=? AND schema_name=? AND table_name=?",
            (database, schema, table),
        )
        pk = [r["column_name"] for r in await cur.fetchall()]

        cur = await db.execute(
            "SELECT column_name, ref_schema, ref_table, ref_column "
            "FROM sc_foreign_keys "
            "WHERE database_name=? AND schema_name=? AND table_name=?",
            (database, schema, table),
        )
        fks = [dict(r) for r in await cur.fetchall()]

        cur = await db.execute(
            "SELECT index_name, is_unique, is_primary_key, columns "
            "FROM sc_indexes "
            "WHERE database_name=? AND schema_name=? AND table_name=?",
            (database, schema, table),
        )
        indexes = []
        for r in await cur.fetchall():
            indexes.append({
                "index_name": r["index_name"],
                "is_unique": bool(r["is_unique"]),
                "is_primary_key": bool(r["is_primary_key"]),
                "columns": r["columns"].split(",") if r["columns"] else [],
            })

        cur = await db.execute(
            "SELECT description FROM sc_comments "
            "WHERE database_name=? AND schema_name=? AND object_name=? "
            "AND column_name=''",
            (database, schema, table),
        )
        row = await cur.fetchone()
        description = row["description"] if row else None

    return {
        "schema_name": schema,
        "table_name": table,
        "columns": columns,
        "primary_key": pk,
        "foreign_keys": fks,
        "indexes": indexes,
        "description": description,
    }


async def database_summary(db_path: str, database: str) -> dict:
    async with aiosqlite.connect(db_path) as db:
        db.row_factory = aiosqlite.Row
        counts = {}
        for tbl in ["sc_tables", "sc_columns", "sc_foreign_keys",
                    "sc_indexes", "sc_objects"]:
            cur = await db.execute(
                f"SELECT COUNT(*) AS n FROM {tbl} WHERE database_name=?",
                (database,),
            )
            counts[tbl] = (await cur.fetchone())["n"]

        cur = await db.execute(
            "SELECT object_type, COUNT(*) AS n FROM sc_objects "
            "WHERE database_name=? GROUP BY object_type",
            (database,),
        )
        object_counts = {r["object_type"]: r["n"]
                         for r in await cur.fetchall()}

        cur = await db.execute(
            "SELECT * FROM schema_version WHERE database_name=?",
            (database,),
        )
        ver = await cur.fetchone()

    return {
        "database_name": database,
        "table_count": counts["sc_tables"],
        "column_count": counts["sc_columns"],
        "foreign_key_count": counts["sc_foreign_keys"],
        "index_count": counts["sc_indexes"],
        "object_count": counts["sc_objects"],
        "objects_by_type": object_counts,
        "schema_version": dict(ver) if ver else None,
    }
