"""Tests for detail-tier projection helpers (P1)."""
import pytest

from sqlserver_semantic_mcp.server.tools.shape import (
    resolve_detail,
    project_describe_table,
    project_get_columns,
    project_classify,
    project_describe_object,
    DetailError,
)


# ---------- resolve_detail ----------

def test_resolve_detail_default_is_brief():
    assert resolve_detail({}) == "brief"


def test_resolve_detail_honors_value():
    assert resolve_detail({"detail": "standard"}) == "standard"
    assert resolve_detail({"detail": "full"}) == "full"
    assert resolve_detail({"detail": "brief"}) == "brief"


def test_resolve_detail_rejects_invalid():
    with pytest.raises(DetailError):
        resolve_detail({"detail": "verbose"})


# ---------- describe_table projection ----------

_FULL_TABLE = {
    "schema_name": "dbo",
    "table_name": "Users",
    "columns": [
        {"column_name": "Id", "data_type": "int", "is_nullable": False,
         "default_value": None, "description": None, "max_length": 4,
         "ordinal_position": 1},
        {"column_name": "OrgId", "data_type": "int", "is_nullable": False,
         "default_value": None, "description": None, "max_length": 4,
         "ordinal_position": 2},
        {"column_name": "Email", "data_type": "nvarchar(255)", "is_nullable": False,
         "default_value": None, "description": "login email",
         "max_length": 255, "ordinal_position": 3},
        {"column_name": "Status", "data_type": "int", "is_nullable": False,
         "default_value": None, "description": None, "max_length": 4,
         "ordinal_position": 4},
        {"column_name": "CreatedAt", "data_type": "datetime", "is_nullable": False,
         "default_value": "getdate()", "description": None, "max_length": 8,
         "ordinal_position": 5},
        {"column_name": "Note", "data_type": "nvarchar(max)", "is_nullable": True,
         "default_value": None, "description": None, "max_length": -1,
         "ordinal_position": 6},
    ],
    "primary_key": ["Id"],
    "foreign_keys": [
        {"column_name": "OrgId", "ref_schema": "dbo", "ref_table": "Org",
         "ref_column": "Id"},
    ],
    "indexes": [{"index_name": "IX_Users_Email", "is_unique": True,
                 "is_primary_key": False, "columns": ["Email"]}],
    "description": None,
}


def test_describe_table_brief_shape():
    classification = {"type": "dimension", "confidence": 0.5}
    column_semantics = {"CreatedAt": "audit_timestamp", "Status": "status"}
    out = project_describe_table(
        _FULL_TABLE, detail="brief",
        classification=classification, column_semantics=column_semantics,
    )
    assert out == {
        "table": "dbo.Users",
        "column_count": 6,
        "pk": ["Id"],
        "fk_to": ["dbo.Org"],
        "important_columns": ["Id", "OrgId", "Status", "CreatedAt", "Email", "Note"],
        "classification": "dimension",
    }


def test_describe_table_standard_shape():
    out = project_describe_table(
        _FULL_TABLE, detail="standard",
        classification={"type": "dimension", "confidence": 0.5},
        column_semantics={},
    )
    assert out["table"] == "dbo.Users"
    assert out["column_count"] == 6
    assert out["pk"] == ["Id"]
    assert out["fk_to"] == ["dbo.Org"]
    assert len(out["columns"]) == 6
    # standard columns are name+type+nullable only
    c0 = out["columns"][0]
    assert set(c0.keys()) == {"name", "type", "is_nullable"}
    assert c0 == {"name": "Id", "type": "int", "is_nullable": False}
    # full FKs
    assert out["foreign_keys"][0]["column_name"] == "OrgId"
    # standard excludes indexes/description
    assert "indexes" not in out
    assert "description" not in out


def test_describe_table_full_shape_includes_everything():
    out = project_describe_table(
        _FULL_TABLE, detail="full",
        classification={"type": "dimension", "confidence": 0.5},
        column_semantics={},
    )
    assert "indexes" in out
    assert out["columns"][2]["description"] == "login email"
    assert out["columns"][4]["default_value"] == "getdate()"


def test_describe_table_brief_important_columns_caps_at_eight():
    many = {
        "schema_name": "dbo", "table_name": "Wide",
        "columns": [
            {"column_name": f"c{i}", "data_type": "int", "is_nullable": False,
             "default_value": None, "description": None,
             "max_length": 4, "ordinal_position": i}
            for i in range(1, 13)
        ],
        "primary_key": ["c1"],
        "foreign_keys": [
            {"column_name": "c2", "ref_schema": "dbo", "ref_table": "A",
             "ref_column": "Id"},
        ],
        "indexes": [],
        "description": None,
    }
    out = project_describe_table(
        many, detail="brief",
        classification={"type": "fact", "confidence": 0.7},
        column_semantics={},
    )
    assert len(out["important_columns"]) == 8
    # must start with PK, then FK
    assert out["important_columns"][0] == "c1"
    assert out["important_columns"][1] == "c2"


# ---------- get_columns projection ----------

_FULL_COLS = [
    {"column_name": "Id", "data_type": "int", "is_nullable": False,
     "default_value": None, "description": None, "max_length": 4,
     "ordinal_position": 1},
    {"column_name": "CreatedAt", "data_type": "datetime", "is_nullable": False,
     "default_value": None, "description": None, "max_length": 8,
     "ordinal_position": 2},
]


def test_get_columns_brief_shape():
    out = project_get_columns(_FULL_COLS, detail="brief",
                              semantic_map={"CreatedAt": "audit_timestamp"})
    assert out == [
        {"name": "Id", "semantic": "generic"},
        {"name": "CreatedAt", "semantic": "audit_timestamp"},
    ]


def test_get_columns_standard_shape():
    out = project_get_columns(_FULL_COLS, detail="standard",
                              semantic_map={})
    assert out[0] == {"name": "Id", "type": "int",
                      "is_nullable": False, "semantic": "generic"}


def test_get_columns_full_shape():
    out = project_get_columns(_FULL_COLS, detail="full",
                              semantic_map={"CreatedAt": "audit_timestamp"})
    assert out[1] == {
        "name": "CreatedAt", "type": "datetime", "max_length": 8,
        "is_nullable": False, "default_value": None, "description": None,
        "semantic": "audit_timestamp",
    }


# ---------- classify projection ----------

def test_classify_brief_drops_reasons():
    cls = {"type": "dimension", "confidence": 0.5, "reasons": ["x"]}
    assert project_classify(cls, "brief") == {"type": "dimension", "confidence": 0.5}


def test_classify_standard_and_full_keep_reasons():
    cls = {"type": "dimension", "confidence": 0.5, "reasons": ["x"]}
    assert project_classify(cls, "standard") == cls
    assert project_classify(cls, "full") == cls


# ---------- describe_object projection ----------

_FULL_OBJ = {
    "schema": "dbo", "object_name": "vw_x", "object_type": "VIEW",
    "definition": "CREATE VIEW vw_x AS SELECT 1",
    "definition_hash": "abcdef12", "definition_bytes": 28,
    "dependencies": ["dbo.Users"],
    "affected_tables": ["dbo.Users"],
    "description": "active users view", "status": "ready",
}


def test_describe_object_brief_shape():
    out = project_describe_object(_FULL_OBJ, detail="brief",
                                  include_definition=False)
    assert out == {
        "object": "dbo.vw_x", "type": "VIEW",
        "depends_on": ["dbo.Users"],
        "definition_bytes": 28,
    }


def test_describe_object_standard_shape():
    out = project_describe_object(_FULL_OBJ, detail="standard",
                                  include_definition=False)
    assert out["object"] == "dbo.vw_x"
    assert out["definition_hash"] == "abcdef12"
    assert out["affected_tables"] == ["dbo.Users"]
    assert out["description"] == "active users view"
    assert "definition" not in out


def test_describe_object_full_shape_includes_definition():
    out = project_describe_object(_FULL_OBJ, detail="full",
                                  include_definition=False)
    assert out["definition"] == "CREATE VIEW vw_x AS SELECT 1"


def test_describe_object_explicit_include_definition_overrides_brief():
    out = project_describe_object(_FULL_OBJ, detail="brief",
                                  include_definition=True)
    assert out["definition"] == "CREATE VIEW vw_x AS SELECT 1"


def test_describe_object_full_wins_over_explicit_false():
    out = project_describe_object(_FULL_OBJ, detail="full",
                                  include_definition=False)
    # detail=full always includes definition
    assert "definition" in out
