# XR 場景物件管理 API

XR 應用需要一個後端，管理場景中的 3D 物件（名稱、模型網址、位置、旋轉、縮放）。
本專案由 **Subagent 團隊**（architect / coder / tester / reviewer / db-bench）在 OpenCode 中協作完成，技術棧為 Python 3.13 + FastAPI + Pydantic v2 + pytest。

GitHub：<https://github.com/R-she/xr-object-api>　·　繳交清單：[`SUBMISSION.md`](SUBMISSION.md)

## 文件

| 文件 | 內容 | 作者 |
| --- | --- | --- |
| [`docs/spec.md`](docs/spec.md) | 架構、資料模型、API 契約、測試案例清單 | `team/architect` |
| [`docs/compare.md`](docs/compare.md) | SQLite / PostgreSQL / MongoDB 評估與選擇理由 | 3 × `team/db-bench` 平行產出，主 Agent 彙整 |
| [`docs/permissions.md`](docs/permissions.md) | 團隊角色與權限設計表（含設計理由） | 主 Agent |
| [`docs/review-report.md`](docs/review-report.md) | 程式碼審查報告（分級發現） | `team/reviewer` |
| [`docs/security-report.md`](docs/security-report.md) | OWASP Top 10 資安審查（加分題） | `team/security` |
| [`docs/reflection.md`](docs/reflection.md) | 反思報告：序列 vs 平行、角色表現與調整 | 主 Agent |

## 團隊

| 代理 | 職責 | 可寫範圍 |
| --- | --- | --- |
| 主 Agent（Tech Lead） | 需求拆解、派工、彙整、驗收 | 全專案 |
| `team/architect` | 寫規格與 API 契約 | `docs/spec.md` |
| `team/coder` | 依規格實作 FastAPI | `app/**`、相依設定 |
| `team/tester` | 撰寫並執行 pytest | `tests/**` |
| `team/reviewer` | 唯讀審查（契約、安全、測試品質） | `docs/review-report.md` |
| `team/db-bench` | 平行評估單一儲存方案 | `bench/**` |

權限設計與理由見 [`docs/permissions.md`](docs/permissions.md)。

## 快速開始

```powershell
py -m pip install -r requirements.txt
py -m uvicorn app.main:create_app --factory --reload
```

> `create_app()` 是 application factory，啟動時要加 `--factory`。
> 預設使用記憶體儲存；在專案根目錄設定環境變數即可切換到 SQLite（父目錄不存在時會自動建立）：
>
> ```powershell
> $env:XR_DB_PATH = "xr.db"
> py -m uvicorn app.main:create_app --factory --reload
> ```

- Swagger UI：<http://127.0.0.1:8000/docs>
- 健康檢查：`GET /healthz`

## 測試

```powershell
py -m pytest -q
```

## 目錄結構

```
.opencode/agents/team/   團隊角色定義（frontmatter 即權限）
app/                     FastAPI 應用（router / service / repository 分層）
tests/                   pytest 測試
bench/                   三種資料庫的評估腳本與 JSON 結果
docs/                    規格、比較表、權限設計、審查與反思
opencode.json            主 Agent 的 subagent 權限（僅 team/*）
```
