# sqlserver-semantic-mcp

[![License](https://img.shields.io/badge/license-MIT-blue.svg)](LICENSE)
[![Python](https://img.shields.io/badge/python-3.11%2B-blue.svg)](https://www.python.org/)
[![MCP](https://img.shields.io/badge/MCP-1.0%2B-purple.svg)](https://modelcontextprotocol.io)
[![Version](https://img.shields.io/badge/version-0.4.0-green.svg)](pyproject.toml)
[![English](https://img.shields.io/badge/lang-English-blue.svg)](README.md)

> **SQL Server 資料庫的語意智慧層,透過 MCP 對外提供。**
> 這不是 SQL 執行器,而是為 AI Agent 打造的資料庫理解引擎。

AI Agent 不需要赤裸的 `execute_sql`。它們需要理解 schema 結構、關聯、物件相依性,最重要的是,能在操作者定義的安全邊界內運作。

`sqlserver-semantic-mcp` 透過 18 個 MCP 工具與 6 個 MCP 資源提供以上能力,底層以雙層 SQLite 快取加速,並以 JSON 格式的 policy 系統保障安全。

---

## 功能特色

- **18 個 MCP 工具**,分佈於 6 個能力群組(metadata、relationship、semantic、object、query、policy)
- **雙層 SQLite 快取** — Structural Cache(啟動時預熱)+ Semantic Cache(延遲載入 + 背景填入)
- **三重 hash schema 版本控制** — 偵測結構 / 物件 / 註解變更何時讓快取分析失效
- **Policy 閘門執行** — SELECT/INSERT/UPDATE/DELETE/… 權限、WHERE 子句要求、資料列上限、schema/table 白名單
- **語意分類** — 自動識別 fact / dimension / lookup / bridge / audit 表
- **Join 路徑探索** — 在 FK 圖上以 BFS 找出兩張表之間的關聯路徑
- **物件檢視** — view / procedure / function 定義與相依追蹤
- **優雅降級** — policy 檔遺失或損壞時回退為唯讀;資料庫不可達時亦不會破壞快取

---

## 架構

五層架構,嚴格單向相依:

```
MCP Interface      (server/)          ← tool / resource 註冊
      ↓
Application        (services/)        ← 6 個服務編排快取 + policy + DB
      ↓
Policy / Domain    (policy/, domain/) ← 模型、SQL 意圖分析、強制執行
      ↓
Infrastructure     (infrastructure/)  ← pymssql + SQLite + 背景任務
      ↓
SQL Server + SQLite
```

### 快取模型

| 層級 | 內容 | 策略 | 失效條件 |
|---|---|---|---|
| **Structural Cache** | 表、欄位、PK/FK、索引、物件清單、註解 | 啟動時預熱,SQLite 持久化 | `structural_hash` / `object_hash` / `comment_hash` 不一致 |
| **Semantic Cache** | 表分類、欄位語意、物件定義、相依性 | 延遲 + 背景漸進填入 | hash 變更 → 標記為 `dirty` → 重新計算 |

---

## 安裝

需要 Python 3.11+。

```bash
pip install -e ".[dev]"
```

會一併安裝:
- `mcp`(MCP SDK)
- `pymssql`(SQL Server 驅動)
- `pydantic` + `pydantic-settings`(設定 + 模型驗證)
- `aiosqlite`(非同步 SQLite 快取)
- `pytest` + `pytest-asyncio` + `pytest-mock`(測試依賴)

---

## 設定

所有設定透過 `SEMANTIC_MCP_` 前綴的環境變數進行。工作目錄下的 `.env` 檔也會自動載入。

### 必要項目

| 變數 | 說明 |
|---|---|
| `SEMANTIC_MCP_MSSQL_SERVER` | SQL Server 主機(支援 `(localdb)\Instance` 與 `*.database.windows.net`) |
| `SEMANTIC_MCP_MSSQL_DATABASE` | 目標資料庫名稱 |
| `SEMANTIC_MCP_MSSQL_USER` | SQL 認證使用者(`SEMANTIC_MCP_MSSQL_WINDOWS_AUTH=true` 時可省略) |
| `SEMANTIC_MCP_MSSQL_PASSWORD` | SQL 認證密碼 |

### 選用項目

| 變數 | 預設值 | 說明 |
|---|---|---|
| `SEMANTIC_MCP_MSSQL_PORT` | `1433` | TCP 連接埠 |
| `SEMANTIC_MCP_MSSQL_WINDOWS_AUTH` | `false` | 使用 Windows 驗證 |
| `SEMANTIC_MCP_MSSQL_ENCRYPT` | `false` | 強制 TLS(Azure SQL 自動啟用) |
| `SEMANTIC_MCP_CACHE_PATH` | `./cache/semantic_mcp.db` | SQLite 快取檔位置 |
| `SEMANTIC_MCP_CACHE_ENABLED` | `true` | 關閉可略過啟動預熱 |
| `SEMANTIC_MCP_BACKGROUND_BATCH_SIZE` | `5` | 每次背景批次處理的表數 |
| `SEMANTIC_MCP_BACKGROUND_INTERVAL_MS` | `500` | 批次之間的延遲 |
| `SEMANTIC_MCP_POLICY_FILE` | *(內建唯讀)* | Policy JSON 檔路徑 |
| `SEMANTIC_MCP_POLICY_PROFILE` | *(檔案的 active_profile)* | 覆寫啟用中的 profile |
| `SEMANTIC_MCP_MAX_ROWS_RETURNED` | `1000` | 覆寫 SELECT 回傳列數上限 |
| `SEMANTIC_MCP_MAX_ROWS_AFFECTED` | `100` | 覆寫 DML 受影響列數上限 |
| `SEMANTIC_MCP_QUERY_TIMEOUT` | `30` | 查詢逾時(秒) |

---

## Policy 系統

若未提供 policy 檔,會採用內建的 **唯讀** profile:僅允許 `SELECT`,最多回傳 1000 列,拒絕多敘述查詢。

如需自訂 policy,請建立 JSON 檔(參考 `config/policy.example.json`)並將 `SEMANTIC_MCP_POLICY_FILE` 指向該檔:

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

### Policy 欄位

**Operations** — 10 個旗標(select / insert / update / delete / truncate / create / alter / drop / execute / merge)

**Constraints** — `require_where_for_update`、`require_where_for_delete`、`require_top_for_select`、`max_rows_returned`、`max_rows_affected`、`allow_multi_statement`、`query_timeout_seconds`

**Scope** — `allowed_databases`、`allowed_schemas`、`allowed_tables`、`denied_tables`

> **安全提醒:** 當設定 `allowed_schemas` 時,若查詢引用的表未帶 schema 前綴(例如 `SELECT * FROM Users` 而非 `dbo.Users`)將被拒絕 — 無法以隱含預設值繞過 schema 級別的存取控制。

### 失效行為

| 條件 | 行為 |
|---|---|
| Policy 檔路徑未設定 | 內建唯讀,記錄警告 |
| Policy 檔缺失 | 內建唯讀,記錄警告 |
| Policy 檔無法讀取 | 內建唯讀,記錄錯誤 |
| Policy 檔 JSON 格式錯誤 | 內建唯讀,記錄錯誤 |
| Policy 檔 schema 驗證失敗 | 內建唯讀,記錄錯誤 |
| `active_profile` / 覆寫指向不存在的 profile | 伺服器拒絕啟動(顯露設定錯誤) |

---

## MCP 工具

### Metadata(3)

| 工具 | 用途 |
|---|---|
| `get_tables` | 列出所有表(schema + 名稱) |
| `describe_table` | 欄位、PK、FK、索引、表描述 |
| `get_columns` | 欄位清單含型別與描述 |

### Relationship(3)

| 工具 | 用途 |
|---|---|
| `get_table_relationships` | 某張表的 FK 入邊與出邊 |
| `find_join_path` | 兩張表之間以 FK 為基礎的最短 join 路徑(BFS、雙向) |
| `get_dependency_chain` | 從指定表出發、透過 FK 可達的所有表 |

### Semantic(3)

| 工具 | 用途 |
|---|---|
| `classify_table` | 回傳表類型:fact / dimension / lookup / bridge / audit |
| `analyze_columns` | 每個欄位的語意標籤(audit_timestamp、audit_user、status、type…) |
| `detect_lookup_tables` | 掃描資料庫並回傳可能的 lookup 表(優先使用快取) |

### Object(3)

| 工具 | 用途 |
|---|---|
| `describe_view` | View 定義與相依 |
| `describe_procedure` | Stored procedure 定義與相依 |
| `trace_object_dependencies` | view/proc/function 相依的所有物件/表之平坦清單 |

### Query(2)

| 工具 | 用途 |
|---|---|
| `validate_query` | 分析 SQL 意圖並回報 policy 是否允許(不執行) |
| `run_safe_query` | 經 policy 驗證後執行 SQL;結果會被截斷至 `max_rows_returned` |

### Policy(3)

| 工具 | 用途 |
|---|---|
| `get_execution_policy` | 回傳啟用中的 policy profile |
| `validate_sql_against_policy` | 與 `validate_query` 相同,但以 policy 為焦點 |
| `refresh_policy` | 熱重載 policy 檔 |

### Cache(1)

| 工具 | 用途 |
|---|---|
| `refresh_schema_cache` | 重新取得結構 metadata;hash 有變動的 semantic 列會被標記為 dirty |

---

## MCP 資源

```
semantic://schema/tables                          — 所有表(JSON)
semantic://schema/tables/{schema}.{table}         — 單張表 metadata
semantic://summary/database                       — 計數與 hash
semantic://analysis/classification/{schema}.{table}
semantic://analysis/dependencies/{type}/{schema}.{name}   — type ∈ VIEW/PROCEDURE/FUNCTION
```

`list_resources` 呼叫時會自動依表列出資源;個別讀取則以上述 URI 為目標。

---

## 啟動伺服器

```bash
python -m sqlserver_semantic_mcp.main
```

伺服器透過 stdio 以 MCP 通訊。啟動時會:

1. 開啟(或建立)SQLite 快取
2. 從 SQL Server 抓取新的 Structural 快照並寫入
3. 將所有表加入 Semantic 分析佇列
4. 啟動背景填入任務
5. 接受 MCP 工具/資源呼叫

背景填入對持續性錯誤採用指數退避(2ⁿ 秒,上限 60 秒),避免日誌洪流或 CPU 空轉。

---

## 開發

### 執行測試

```bash
pytest tests/unit                      # 82 個單元測試,不需資料庫
pytest tests/integration -m integration # 需要實際的 SQL Server
```

### 專案結構

```
sqlserver_semantic_mcp/
├── config.py                         — 以環境變數為基礎的 Pydantic 設定
├── main.py                           — stdio 伺服器 + 啟動 + 背景任務
├── domain/
│   ├── enums.py                      — TableType、ObjectType、CacheStatus、RiskLevel、SqlOperation
│   └── models/                       — Column、Table、ForeignKey、Index、Relationship、DbObject
├── policy/
│   ├── models.py                     — PolicyProfile / PolicyOperations / PolicyConstraints / PolicyScope
│   ├── loader.py                     — JSON 載入,附優雅回退
│   ├── analyzer.py                   — regex 為基礎的 SQL 意圖擷取
│   └── enforcer.py                   — policy 裁決(allow/reject + 原因)
├── infrastructure/
│   ├── connection.py                 — pymssql 連線與輔助工具
│   ├── background.py                 — 背景 semantic 填入迴圈含退避
│   ├── cache/
│   │   ├── store.py                  — SQLite DDL + 初始化
│   │   ├── structural.py             — hash + 預熱 + 快照持久化
│   │   └── semantic.py               — 分析/定義 I/O + pending 佇列
│   └── queries/                      — SQL Server 查詢(metadata / 註解 / 物件)
├── services/                         — 6 個服務(metadata / relationship / semantic / object / policy / query)
└── server/
    ├── app.py                        — MCP Server、工具註冊表、JSON envelope
    ├── tools/                        — 7 個工具模組(每個能力群組一個)
    └── resources/                    — schema / analysis / summary URI
```

### 測試慣例

- **單元測試** 使用記憶體或暫存目錄的 SQLite,並 mock pymssql。
- **整合測試** 標記為 `@pytest.mark.integration`,未設定 `SEMANTIC_MCP_MSSQL_SERVER` 時跳過。
- Pydantic 模型直接測試;infrastructure 層以 mocked connection 驗證。

---

## 安全設計

- **預設唯讀**:若未設定 policy,只允許 `SELECT`。
- **強制 SQL 驗證**:每個查詢在抵達 `cursor.execute()` 前,都會經過意圖分析器與 policy 執行器。
- **拒絕危險敘述**:`DROP` / `TRUNCATE` 被分類為 `CRITICAL` 風險等級;除非明確允許,否則封鎖。
- **Schema 感知存取控制**:`allowed_schemas` 會拒絕隱含 schema 的查詢,防止利用 schema 預設值繞過。
- **Policy 強化**:格式錯誤的 policy 檔會回退為唯讀,而不是讓伺服器崩潰。

---

## 限制 / 未來工作

- SQL 意圖分析器為 regex 基底,非完整 T-SQL parser — CTE 內定義的名稱可能被視為表。若有疑慮,請先使用 `validate_sql_against_policy`。
- 索引查詢使用的 `STRING_AGG` 需 SQL Server 2017+。更舊版本需替代查詢。
- `sys.extended_properties` 的讀取需要 `VIEW DEFINITION` 權限;受限物件的註解不會出現在快取中。
- 背景填入採單一 worker;在非常龐大的 schema 上,Semantic Cache 可能需要時間才能收斂(使用 `refresh_schema_cache` 可強制結構重新整理;semantic 分類仍會延遲填入)。

---

## 授權

本專案採用 MIT 授權 — 詳見 `LICENSE`。
