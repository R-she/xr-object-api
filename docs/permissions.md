# 團隊與權限設計（XR 場景物件管理 API）

團隊定義放在 `.opencode/agents/team/`，子資料夾會成為 ID 前綴（`team/architect`、`team/coder`…）。
所有角色採 **預設拒絕（deny-by-default）＋ 白名單**：第一條規則是 `{"action":"*","resource":"*","effect":"deny"}`，之後才逐條開放。
OpenCode 的規則是「最後一條符合的規則勝出」，所以越具體的例外要寫在越後面。

## 1. 團隊成員

| 代理（ID） | 模式 | 職責 | 唯一可寫範圍 | steps |
| --- | --- | --- | --- | --- |
| 主 Agent（Tech Lead / `build`） | primary | 理解需求、派工、整合與驗收 | 全專案（含 `docs/compare.md`） | — |
| `team/architect` | subagent | 需求 → 規格與 API 契約 | `docs/spec.md` | 24 |
| `team/coder` | subagent | 依規格實作 FastAPI 服務 | `app/**`、`requirements*.txt`、`pyproject.toml`、`README.md` | 40 |
| `team/tester` | subagent | 契約 → pytest 測試、回報缺陷 | `tests/**`、`pytest.ini` | 40 |
| `team/reviewer` | subagent | 唯讀審查、風險分級 | `docs/review-report.md` | 24 |
| `team/db-bench` | subagent | 平行評估單一儲存方案（SQLite / PostgreSQL / MongoDB） | `bench/**` | 18 |
| `team/security` | subagent | OWASP Top 10 資安審查（加分題） | `docs/security-report.md` | 22 |

## 2. 權限矩陣

| 動作 / 資源 | 主 Agent | architect | coder | tester | reviewer | db-bench | security |
| --- | --- | --- | --- | --- | --- | --- | --- |
| `read` / `glob` / `grep` | ✅ | ✅ | ✅ | ✅ | ✅ | ✅ | ✅ |
| `edit` `docs/**` | ✅ | ✅（僅 `docs/spec.md`） | ❌ | ❌ | ❌（僅 `docs/review-report.md` ✅） | ❌ | ❌（僅 `docs/security-report.md` ✅） |
| `edit` `app/**` | ✅ | ❌ | ✅ | ❌ | ❌ | ❌ | ❌ |
| `edit` `tests/**` | ✅ | ❌ | ❌ | ✅ | ❌ | ❌ | ❌ |
| `edit` `bench/**` | ✅ | ❌ | ❌ | ❌ | ❌ | ✅ | ❌ |
| `edit` 根目錄設定檔 | ✅ | ❌ | ✅（`requirements*.txt`、`pyproject.toml`、`README.md`） | ⚠️ 僅 `pytest.ini` | ❌ | ❌ | ❌ |
| `shell` 一般執行 | ✅ | ❌ | ✅ `py *` / `python *` | ⚠️ 僅 `py -m pytest*`、`py -m compileall*` | ⚠️ 僅 `py -m pytest*`、`py -m compileall*` | ✅ `py *` | ⚠️ 僅 `py -m pytest*` |
| `shell` 破壞性（`Remove-Item`、`pip uninstall`、`git push`） | ✅ | ❌ | ❌ | ❌ | ❌ | ❌ | ❌ |
| `webfetch` | ✅ | ⚠️ 僅 FastAPI 官方文件 | ❌ | ❌ | ❌ | ⚠️ 僅 sqlite/postgresql/mongodb 官方站 | ⚠️ 僅 owasp.org |
| `subagent`（再開子代理） | ✅ **僅 `team/*`** | ❌ | ❌ | ❌ | ❌ | ❌ | ❌ |
| `skill` | ✅ | ✅ | ✅ | ✅ | ✅ | ✅ | ✅ |
| 其他未列出動作 | ✅ | ❌ | ❌ | ❌ | ❌ | ❌ | ❌ |

圖例：✅ 允許、⚠️ 有條件允許、❌ 拒絕。主 Agent 的 `subagent` 限制寫在 `opencode.json`（`agents.build.permissions`），其餘寫在各 `.md` 的 frontmatter。

## 3. 為什麼這樣設定

### 共通原則
- **預設拒絕**：新工具或新動作不會因為「忘了關」而自動取得權限；要開就明示。
- **一人一職、單一寫入範圍**：每個角色只碰自己負責的目錄，出問題時從檔案路徑就能定位責任。
- **禁止子代理再開子代理**：避免遞迴展開造成費用與範圍失控；派工權集中在 Tech Lead。
- **`steps` 上限**：成本與收斂的控制閥，也逼迫角色在有限步數內交出可驗收的成果。

### 主 Agent（Tech Lead）
- **`subagent` 只允許 `team/*`**：指揮者只能派自己的團隊，不能隨意啟動內建 `general`／`explore` 去繞過角色分工；要新增能力就得先定義角色與權限，團隊組成因此是可稽核的。
- **保留全專案寫入**：唯一需要寫 `docs/compare.md`（彙整 3 份 JSON 的比較表）與最終 README 的角色；整合工作無法外包給有寫入範圍限制的成員。

### architect：只能寫 `docs/spec.md`
- **理由**：架構師的產出是決策與契約，不是程式碼。若它能改 `app/`，就會用「先寫程式再說」繞過設計評審，契約與實作互相遷就。
- **`shell` 全關**：寫規格不需要執行環境，也避免它在沒有測試把關下改動工作區。
- **`webfetch` 只開 FastAPI 官方文件**：查證框架行為有正當來源，同時阻擋任意網路存取。

### coder：只能寫 `app/` 與相依設定
- **`tests/**` 明確 deny（最重要的一條）**：實作者若能改測試，遇到紅燈最省力的做法就是改測試而不是修程式。鎖住 `tests/` 之後，紅燈只能是紅燈。
- **`docs/**` deny**：契約是輸入不是產出；落差要回報 architect，不能自己改規格讓自己通過。
- **允許 `py *`**：需要 `compileall`、`py -c` 煙霧測試與必要時安裝套件。
- **破壞性指令後寫覆蓋**：`Remove-Item`、`pip uninstall`、`git push` 一律拒絕，影響超出「完成功能」的合理範圍且難以復原。
- **`webfetch` deny**：所需資訊已在 `docs/spec.md`，不把不信任內容帶進程式碼。

### tester：只能寫 `tests/`
- **`app/**` deny**：測試者改產品碼等於自己出題自己改答案，測試就失去獨立性。發現 bug 只能寫失敗測試＋回報。
- **只跑 `pytest` / `compileall`**：需要執行但不需要改環境；白名單讓「執行」與「變更」分離。
- **`docs/**` deny**：契約有疑問要提問，不能把測試改成符合現況。

### reviewer：唯讀（僅一份報告）
- **全面 deny `edit`，只留 `docs/review-report.md`**：審查的價值來自獨立性，能修就不要審；唯一例外是留下可追蹤的書面結論。
- **允許 `pytest`**：先驗證基線再審查，避免只靠讀碼猜測行為；但不可改測試或程式。
- **無 `webfetch`**：審查範圍是本地契約與實作，外部資訊只擴大攻擊面。

### db-bench：只能寫 `bench/`
- **只評估一種方案**：三個子代理平行、彼此獨立，回報格式事先約定成同一份 JSON，主 Agent 才能自動排序（符合「可切分、不相依、格式先約定」）。
- **只開 `bench/**`**：不碰產品碼與文件，避免「評估者順手改實作」污染比較結果。
- **`webfetch` 限三個官方網站**：評分需要文件佐證，但不接受任意來源。
- **禁 `pip install`／啟動資料庫**：確保三個子代理在同一個乾淨環境下評估，且不會在評分過程中改變環境；沒有本地服務的方案必須誠實標記 `measured: false`。

### security：唯讀（僅一份報告）
- **只寫 `docs/security-report.md`**：資安審查的價值在於「不動手也能指出問題」；給它修補權會讓它順手改碼，反而失去獨立驗證。
- **只開 OWASP 官方站**：判定要有依據，但不讓它連到任意來源或下載工具。
- **不准跑一般 shell**：只允許 `pytest` 驗證現況，避免「用攻擊腳本測試」失控；測試以唯讀請求和輸入邊界為主。
- **不能 `subagent`**：加分題是附加檢查，不應再展開更多子代理消耗成本。

## 4. 與產品 API 權限的區隔

上表是**開發流程**權限（誰能改哪個檔案）。產品 API 本身目前沒有認證/授權，這是作業範圍內的刻意取捨：
若日後上線，應補上 API Key 或 OAuth2 scope（`objects:read` / `objects:write`），並在 `docs/spec.md` 的「後續演進」追蹤。
