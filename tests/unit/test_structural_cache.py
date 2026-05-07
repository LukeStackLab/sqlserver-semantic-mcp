import pytest
import aiosqlite
from unittest.mock import MagicMock, patch

from sqlserver_semantic_mcp.infrastructure.cache.store import init_store
from sqlserver_semantic_mcp.infrastructure.cache.structural import (
    compute_structural_hash,
    compute_object_hash,
    compute_comment_hash,
    write_structural_snapshot,
    read_schema_version,
    StructuralSnapshot,
    fetch_snapshot_from_server,
)


def test_structural_hash_stable():
    tables = [("dbo", "Users"), ("dbo", "Orders")]
    columns = [("dbo", "Users", "Id", "int", None, 0, None, 1)]
    pks = [("dbo", "Users", "Id")]
    fks: list = []
    indexes: list = []

    h1 = compute_structural_hash(tables, columns, pks, fks, indexes)
    h2 = compute_structural_hash(list(reversed(tables)), columns, pks, fks, indexes)
    assert h1 == h2


def test_structural_hash_differs():
    h1 = compute_structural_hash([("dbo", "A")], [], [], [], [])
    h2 = compute_structural_hash([("dbo", "B")], [], [], [], [])
    assert h1 != h2


def test_object_hash():
    objs = [("dbo", "v1", "VIEW"), ("dbo", "p1", "PROCEDURE")]
    h1 = compute_object_hash(objs)
    h2 = compute_object_hash(list(reversed(objs)))
    assert h1 == h2


def test_comment_hash():
    comments = [("dbo", "Users", "", "table desc"),
                ("dbo", "Users", "Id", "id desc")]
    h1 = compute_comment_hash(comments)
    h2 = compute_comment_hash(list(reversed(comments)))
    assert h1 == h2


@pytest.mark.asyncio
async def test_write_and_read_snapshot(tmp_path):
    db_path = str(tmp_path / "test.db")
    await init_store(db_path)

    snap = StructuralSnapshot(
        tables=[("dbo", "Users")],
        columns=[("dbo", "Users", "Id", "int", None, 0, None, 1)],
        primary_keys=[("dbo", "Users", "Id")],
        foreign_keys=[],
        indexes=[("dbo", "Users", "PK_Users", 1, 1, "Id")],
        objects=[("dbo", "vw_X", "VIEW")],
        comments=[("dbo", "Users", "", "user table")],
    )
    await write_structural_snapshot(db_path, "testdb", snap)

    ver = await read_schema_version(db_path, "testdb")
    assert ver is not None
    assert ver["database_name"] == "testdb"
    assert ver["structural_hash"]
    assert ver["object_hash"]
    assert ver["comment_hash"]

    async with aiosqlite.connect(db_path) as db:
        cur = await db.execute("SELECT COUNT(*) FROM sc_tables")
        assert (await cur.fetchone())[0] == 1
        cur = await db.execute("SELECT COUNT(*) FROM sc_comments")
        assert (await cur.fetchone())[0] == 1


def test_fetch_snapshot_from_server_uses_single_connection():
    cfg = MagicMock()
    conn = MagicMock()
    cursor = MagicMock()
    conn.cursor.return_value = cursor
    cursor.fetchall.side_effect = [
        [("dbo", "Users")],
        [("dbo", "Users", "Id", "int", None, 0, None, 1)],
        [("dbo", "Users", "Id")],
        [],
        [],
        [],
        [],
    ]

    with patch(
        "sqlserver_semantic_mcp.infrastructure.cache.structural.open_connection",
    ) as mock_open:
        mock_open.return_value.__enter__.return_value = conn
        snap = fetch_snapshot_from_server(cfg)

    assert snap.tables == [("dbo", "Users")]
    assert snap.columns[0][2] == "Id"
    assert cursor.execute.call_count == 7
    conn.cursor.assert_called_once()
