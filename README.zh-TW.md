# sqlserver-semantic-mcp

[![License](https://img.shields.io/badge/license-MIT-blue.svg)](LICENSE)
[![Python](https://img.shields.io/badge/python-3.11%2B-blue.svg)](https://www.python.org/)
[![MCP](https://img.shields.io/badge/MCP-1.0%2B-purple.svg)](https://modelcontextprotocol.io)
[![Version](https://img.shields.io/badge/version-0.5.0-green.svg)](pyproject.toml)
[![English](https://img.shields.io/badge/lang-English-blue.svg)](README.md)

> **SQL Server 資料庫的語意智慧層,透過 MCP 對外提供。**
> 這不是 SQL 執行器,而是為 AI Agent 打造的資料庫理解引擎。

AI Agent 不需要赤裸的 `execute_sql`。它們需要理解 schema 結構、關聯、物件相依性,最重要的是,能在操作者定義的安全邊界內運作。

`sqlserver-semantic-mcp` 透過 29 個 MCP 工具、1 個 concrete MCP 資源與 5 個 MCP resource templates 提供以上能力,底層以雙層 SQLite 快取加速,並以 JSON 格式的 policy 系統保障安全。

---

## 快速開始

依你使用的 client 選一條路徑。所有路徑都用 [`uvx`](https://docs.astral.sh/uv/) — 不需要 `git clone`、不需要建虛擬環境、不需要手動安裝。`uvx` 會在第一次使用時下載並快取套件。

> **前置:** 安裝一次 [uv](https://docs.astral.sh/uv/getting-started/installation/)(`curl -LsSf https://astral.sh/uv/install.sh | sh`)。Python 3.11+ 由 `uv` 自動取得。

> **範例中的** `localhost` / `YourDatabase` / `sa` / `YourPassword` **請替換成你的實際 SQL Server 認證。**

### 🤖 Claude Code CLI

一行指令完成註冊,`uvx` 會在第一次使用時自動解析與快取 `sqlserver-semantic-mcp`:

```bash
claude mcp add sqlserver-semantic -- uvx sqlserver-semantic-mcp \
  -e SEMANTIC_MCP_MSSQL_SERVER=localhost \
  -e SEMANTIC_MCP_MSSQL_DATABASE=YourDatabase \
  -e SEMANTIC_MCP_MSSQL_USER=sa \
  -e SEMANTIC_MCP_MSSQL_PASSWORD=YourPassword
```

或將設定 commit 到專案的 `.mcp.json`,讓整個團隊共用:

```json
{
  "mcpServers": {
    "sqlserver-semantic": {
      "command": "uvx",
      "args": ["sqlserver-semantic-mcp"],
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

用 `claude mcp list` 確認註冊成功。Server 透過 stdio 與 Claude Code 溝通,在工作階段啟動時即可使用。

### 🛠 Codex CLI

把以下區塊加進 `~/.codex/config.toml`:

```toml
[mcp_servers.sqlserver-semantic]
command = "uvx"
args = ["sqlserver-semantic-mcp"]
env = { SEMANTIC_MCP_MSSQL_SERVER = "localhost", SEMANTIC_MCP_MSSQL_DATABASE = "YourDatabase", SEMANTIC_MCP_MSSQL_USER = "sa", SEMANTIC_MCP_MSSQL_PASSWORD = "YourPassword" }
```

接著執行 `codex`,server 會出現在 MCP 工具清單中。

### 🖥 Claude Desktop

編輯設定檔:

- **macOS:** `~/Library/Application Support/Claude/claude_desktop_config.json`
- **Windows:** `%APPDATA%\Claude\claude_desktop_config.json`

```json
{
  "mcpServers": {
    "sqlserver-semantic": {
      "command": "uvx",
      "args": ["sqlserver-semantic-mcp"],
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

存檔後重啟 Claude Desktop。

### 🧪 預先測試(可選,所有 client 通用)

在連到 host 之前先確認套件能跑:

```bash
SEMANTIC_MCP_MSSQL_SERVER=localhost \
SEMANTIC_MCP_MSSQL_DATABASE=YourDatabase \
SEMANTIC_MCP_MSSQL_USER=sa \
SEMANTIC_MCP_MSSQL_PASSWORD=YourPassword \
  uvx sqlserver-semantic-mcp
```

應該會看到啟動 log 顯示 cache 初始化與工具註冊。按 `Ctrl+C` 結束。

### 🧰 本機開發(僅貢獻者)

只想使用 server 的話請略過此段。

```bash
git clone https://github.com/lukedev999-boom/sqlserver-semantic-mcp.git
cd sqlserver-semantic-mcp
cp .env.example .env             # 然後填入 MSSQL 認證
uv sync --dev                    # 建立 .venv 並安裝 dev 依賴
uv run python -m sqlserver_semantic_mcp.main
```

如果偏好 pip editable install:

```bash
pip install -e ".[dev]"
sqlserver-semantic-mcp
```

完整環境變數列表請見[設定](#設定)章節。

---

## 功能特色

- **29 個 MCP 工具**,分佈於 9 個能力群組(metadata、relationship、semantic、object、query、policy、cache、metrics、workflow)
- **雙層 SQLite 快取** — Structural Cache(啟動時預熱)+ Semantic Cache(延遲載入 + 背景填入)
- **Cache-first 啟動** — 預設重用既有 structural cache,避免每次程序重啟都強制全量預熱
- **三重 hash schema 版本控制** — 偵測結構 / 物件 / 註解變更何時讓快取分析失效
- **Policy 閘門執行** — SELECT/INSERT/UPDATE/DELETE/… 權限、WHERE 子句要求、資料列上限、schema/table 白名單
- **語意分類** — 自動識別 fact / dimension / lookup / bridge / audit 表
- **Join 路徑探索** — 在 FK 圖上以 BFS 找出兩張表之間的關聯路徑
- **物件檢視** — view / procedure / function 定義與相依追蹤,並拆分 reads / writes
- **Workflow 快捷工具** — discovery、risk estimation、context bundling、direct execution fast path
- **Payload metrics** — 內建每個工具回應大小量測
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

> 一般使用者請依[快速開始](#快速開始)使用 `uvx`,無需安裝步驟。本段針對貢獻者與離線/封閉環境。

需要 Python 3.11+。

**透過 uvx 一次性執行**(無需安裝,推薦給終端使用者):

```bash
uvx sqlserver-semantic-mcp
```

**安裝為全域 CLI 工具:**

```bash
uv tool install sqlserver-semantic-mcp
# 或:
pipx install sqlserver-semantic-mcp
```

**從原始碼以 pip editable 安裝**(註冊 `sqlserver-semantic-mcp` 指令到 PATH):

```bash
pip install -e ".[dev]"
```

**從原始碼以 uv 安裝:**

```bash
uv sync          # 或 uv sync --dev 包含開發依賴
```

執行時依賴:`mcp`、`pymssql`、`pydantic`、`pydantic-settings`、`aiosqlite`。
開發依賴:`pytest`、`pytest-asyncio`、`pytest-mock`。

> **Linux 注意:** `pymssql` 連結 FreeTDS。若 `pip install` 因編譯錯誤失敗,請先安裝系統 header — 詳見英文 README 的 Troubleshooting。

---

## 設定

所有設定透過 `SEMANTIC_MCP_` 前綴的環境變數進行。工作目錄下的 `.env` 檔也會自動載入。建議直接從 `.env.example` 開始。

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
| `SEMANTIC_MCP_STARTUP_MODE` | `cache_first` | `cache_first` 會在重啟時優先重用既有 cache;`full` 則每次都先向 SQL Server 重新抓結構 |
| `SEMANTIC_MCP_BACKGROUND_BATCH_SIZE` | `5` | 每次背景批次處理的表數 |
| `SEMANTIC_MCP_BACKGROUND_INTERVAL_MS` | `500` | 批次之間的延遲 |
| `SEMANTIC_MCP_POLICY_FILE` | *(內建唯讀)* | Policy JSON 檔路徑 |
| `SEMANTIC_MCP_POLICY_PROFILE` | *(檔案的 active_profile)* | 覆寫啟用中的 profile |
| `SEMANTIC_MCP_MAX_ROWS_RETURNED` | `1000` | 覆寫 SELECT 回傳列數上限 |
| `SEMANTIC_MCP_MAX_ROWS_AFFECTED` | `100` | 覆寫 DML 受影響列數上限 |
| `SEMANTIC_MCP_QUERY_TIMEOUT` | `30` | 查詢逾時(秒) |
| `SEMANTIC_MCP_TOOL_PROFILE` | `all` | 以逗號分隔的工具群組: metadata、relationship、semantic、object、query、policy、cache、metrics、workflow |
| `SEMANTIC_MCP_WORKFLOW_TOOLS_ENABLED` | `true` | 關閉 workflow shortcut 工具 |
| `SEMANTIC_MCP_METRICS_ENABLED` | `true` | 啟用每個工具回應大小量測 |
| `SEMANTIC_MCP_DEFAULT_DETAIL` | `brief` | Agent-facing 工具的預設 detail tier |
| `SEMANTIC_MCP_DEFAULT_RESPONSE_MODE` | `summary` | 查詢執行的預設回應 shape |
| `SEMANTIC_MCP_DEFAULT_TOKEN_BUDGET_HINT` | `low` | 查詢取樣與 payload 的預設 budget |
| `SEMANTIC_MCP_DIRECT_EXECUTE_ENABLED` | `true` | 當 policy 允許時啟用 workflow fast path 直接執行 |
| `SEMANTIC_MCP_STRICT_ROWS_AFFECTED_CAP` | `true` | 預設在超出 rows-affected cap 時回滾 |
| `SEMANTIC_MCP_INTENT_ANALYZER` | `regex` | SQL 意圖分析器後端(`regex` 或 `ast`) |

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

目前的工具群組:

- `metadata`(3): `get_tables`、`describe_table`、`get_columns`
- `relationship`(3): `get_table_relationships`、`find_join_path`、`get_dependency_chain`
- `semantic`(3): `classify_table`、`analyze_columns`、`detect_lookup_tables`
- `object`(3): `describe_view`、`describe_procedure`、`trace_object_dependencies`
- `query`(5): `validate_query`、`run_safe_query`、`plan_or_execute_query`、`preview_safe_query`、`estimate_execution_risk`
- `policy`(3): `get_execution_policy`、`validate_sql_against_policy`、`refresh_policy`
- `cache`(1): `refresh_schema_cache`
- `metrics`(2): `get_tool_metrics`、`reset_tool_metrics`
- `workflow`(6): `discover_relevant_tables`、`suggest_next_tool`、`bundle_context_for_next_step`、`score_join_candidate`、`summarize_table_for_joining`、`summarize_object_for_impact`

若要降低 prompt 成本,優先使用 workflow tools,再搭配 `detail=\"brief\"` 與帶 filter 的 metadata calls。

---

## MCP 資源

自動列出的 concrete resources:

- `semantic://summary/database`

自動列出的 resource templates:

- `semantic://schema/tables/{qualified}`
- `semantic://analysis/classification/{qualified}`
- `semantic://summary/table/{qualified}`
- `semantic://summary/object/{type}/{qualified}`
- `semantic://bundle/joining/{qualified}`

另外也保留相容性的 direct reads:

- `semantic://schema/tables`
- `semantic://analysis/dependencies/{type}/{schema}.{name}`

---

## 啟動伺服器

```bash
python -m sqlserver_semantic_mcp.main
```

伺服器透過 stdio 以 MCP 通訊。啟動時會:

1. 開啟(或建立)SQLite 快取
2. 當 `SEMANTIC_MCP_STARTUP_MODE=cache_first` 時優先重用既有 Structural cache,否則再從 SQL Server 抓取新的快照
3. 將所有表加入 Semantic 分析佇列
4. 啟動背景填入任務
5. 接受 MCP 工具/資源呼叫

背景填入對持續性錯誤採用指數退避(2ⁿ 秒,上限 60 秒),避免日誌洪流或 CPU 空轉。

---

## 開發

### 執行測試

```bash
uv run --extra dev pytest tests/unit
uv run --extra dev pytest tests/integration -m integration
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
