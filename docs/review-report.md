# XR 場景物件管理 API — 程式碼審查報告

- 審查者：`team/reviewer`（唯讀；僅寫入本檔）
- 日期：2026-11-18
- 基線：`py -m pytest -q` → **80 passed, 1 warning**（1.01s）
- 契約來源：`docs/spec.md`（v1.0）

> 工具註記：審查過程中 `Get-ChildItem` 被權限拒絕（角色僅放行 `py -m pytest*` 等），已改用 `glob` / `read` / `grep` 完成靜態審查；未修改任何程式碼或測試。

## 結論

**需修正後合併。** 沒有 blocker；預設 in-memory 路徑的契約實作正確、測試完整度良好（T01–T18 全數覆蓋）。
有 **5 個 major**：其中 3 個是「靜默資料損毀風險 / SQLite 錯誤碼錯映射 / 文件教學路徑跑不起來」，2 個是「SQLite 與併發這兩個 spec 明列承諾缺測試」。
建議修完 blocker/major 再合併；minor 可排入後續。

| 嚴重度 | 數量 |
| --- | --- |
| blocker | 0 |
| major | 5 |
| minor | 6 |
| nit | 7 |

## 通過項目（已核對，非抽樣）

1. **端點與狀態碼**：`/healthz` 200；`GET /objects` 200；`POST` 201 + `Location`；`GET /{id}` 200；`PUT` 200；`DELETE` 204 且 body 為空（`app/routers/objects.py:27-71`）。
2. **錯誤 envelope**：`AppError`、`RequestValidationError`、`StarletteHTTPException`、`Exception` 四個 handler 都輸出 `{error:{code,message,details}}`；500 訊息固定、不帶堆疊或路徑（`app/main.py:56-95`、`app/errors.py:10-22`）。
3. **422 細節**：`details` 一律陣列；`_field_path` 會去掉 `body/query` 前綴並產生 `scale.y` 這類點路徑（`app/errors.py:72-82`）；缺欄位、型別錯誤、越界、`NaN/Infinity`、malformed JSON 都有對應訊息與測試。
4. **名稱規則**：`strip` 後 1–120；`casefold()` 唯一；建立與改名衝突皆 409；與自己只改大小寫允許並以新名稱儲存；刪除後名稱可重用（`app/models.py:21-24`、`app/service.py:71-108`、`tests/test_create.py:89-139`、`tests/test_update_put.py:165-183`）。
5. **PUT 完整取代語意**：`name`/`model_url` 必填；省略選填欄位重設為預設（不是保留）；`id`/`created_at` 不變；`updated_at` 以 `stamp_after` 保證嚴格遞增（同毫秒 +1ms）（`app/service.py:33-38,89-108`、`app/models.py:84-106`）。
6. **列表契約**：排序 `created_at DESC, id ASC`（in-memory 用兩次穩定排序、SQLite 用 `ORDER BY created_at DESC, id ASC`）；`total` 為過濾後總數；`limit` 1–100、`offset` ≥ 0；`q` 去空白後 0 或 >64 的行為符合 spec（`app/service.py:47-62`、`app/storage.py:55-66,156-174`）。
7. **URL 驗證**：只允許 `http/https` + 非空 host + 長度 ≤ 2048；`ftp:`、`javascript:`、相對路徑、`//host`、`https://` 都被 422（`app/models.py:27-41`、`tests/test_validation.py:19-47`）。
8. **注入面**：SQLite 全部使用參數化查詢；`LIKE` 有 `ESCAPE` 且 `%`/`_`/`\` 皆轉義（`app/storage.py:120-128,162`）；`object_id` 僅作為 key/參數，無路徑拼接。
9. **架構**：`router → service → ObjectRepository(Protocol)` 分層落實；`create_app(repository=None)` 每次建新 repository（可注入），無模組級可變狀態；`tests/conftest.py` 每個測試一個新 app，T18 驗證互不影響。
10. **鎖**：service 的 `threading.Lock` 包住「查名 → 寫入」；repository 另有 `RLock`；取鎖順序固定 service→repo，無反向巢狀。
11. **測試品質**：不是只有 happy path；斷言多為精確值（預設向量、`Location`、204 空 body、envelope 鍵集合、時間格式 regex），且測試互不依賴。

## 分級發現

### Blocker

無。

### Major

**M1 — `extra="ignore"` 會默默吞掉拼錯的欄位，PUT 時造成靜默重設（資料遺失）**
`app/models.py:91`（`ObjectWrite`）、`app/models.py:47`（`Vec3`）

```json
PUT /api/v1/objects/{id}
{"name":"A","model_url":"https://x/m.glb","sclae":{"x":2,"y":2,"z":2}}
```

`sclae` 被忽略、`scale` 走 default → 回應 200 且 scale 被**重設為 1,1,1**。因為 PUT 的契約就是「未提供即重設」，客戶端打錯字不會得到任何錯誤，只會拿到被改壞的資料。`Vec3` 同理（`{"x":1,"y":2,"z":3,"w":9}` 會通過）。

建議：`ConfigDict(extra="forbid")`（Pydantic 會給 `extra_forbidden`，`_message_for` 再加一條中文訊息），或至少 PUT 對未知欄位回 422；補一條「未知欄位」測試。

**M2 — SQLite `replace()` 未處理唯一鍵衝突，併發改名會回 500 而非 409**
`app/storage.py:221-240`（對照 `create()` 的 `app/storage.py:191-219` 有處理）

service 的 409 檢查（`app/service.py:94-96`）在單 process 內被鎖保護，但 spec §6 已明言多 worker 需靠 DB 唯一約束；`name_key UNIQUE` 正是最後防線，而這裡的 `UPDATE` 沒有 `try/except sqlite3.IntegrityError`，跨 process 撞名會冒泡成 `internal_error` 500。另外 `rowcount == 0`（物件被併發刪除）時仍回 200 幽靈物件。

建議：`replace()` 比照 `create()`：`except sqlite3.IntegrityError → rollback → NameConflictError`；`cursor.rowcount == 0 → NotFoundError`；並補 SQLite 改名衝突測試。

**M3 — README 的 SQLite 啟動路徑在乾淨 checkout 直接失敗**
`README.md:37`、`app/storage.py:134-141`

`XR_DB_PATH=data\xr.db`，但 repo 內沒有 `data/` 目錄（`read`/`glob` 均確認不存在），程式也沒有 `mkdir`。`sqlite3.connect()` 不會建父目錄，會在 `create_app()` 期間丟 `OperationalError: unable to open database file`，FastAPI 根本起不來，且錯誤發生在 ASGI 啟動前、不經過錯誤 envelope。

建議：`Path(path).parent.mkdir(parents=True, exist_ok=True)`（並考慮 `XR_DB_PATH=":memory:"` 的特例），或在 README 明列 `New-Item -ItemType Directory data`；兩者都做更好。

**M4 — SQLite 後端只有一個 happy-path smoke test，spec 的核心行為完全未在 SQLite 驗證**
`tests/test_isolation.py:37-56`（唯一使用 `sqlite_client` 的測試）、`tests/conftest.py:47-54`

SQLite 是 README 對使用者公開的切換選項（`XR_DB_PATH`），但 409 建立/改名、404、PUT 重設、`q` 搜尋（含 `%`/`_` 轉義）、分頁排序、時間戳格式、名稱大小寫唯一，全部只在 in-memory 測過。M2 就是這個缺口直接放掉的 bug。

建議：把既有契約測試改成 parametrize/間接 fixture（同一批測試同時跑 in-memory 與 `tmp_path` SQLite），至少補：大小寫同名 409、改名 409 且原值不變、`q=%`、`limit/offset` 頁面、`created_at` 排序、時間格式。

**M5 — spec §6 的併發原子性沒有任何測試**
`app/service.py:71-113`（實作正確）、`tests/` 無對應測試

實作看起來正確（鎖內查名→寫入），但「25 條執行緒同時用同一名稱建立，只能 1 筆 201、其餘 409」這種 regression 一旦被改壞不會被發現；spec 把它列為架構承諾，卻沒有守門測試。

建議：`ThreadPoolExecutor` 併發 `POST` 同名（斷言 201 數 == 1、409 數 == n-1、`total == 1`），以及兩個物件互相改名為對方名稱（只能一方成功）。若之後啟用 SQLite，同一測試應一併跑 SQLite。

### Minor

**m1 — 直接依賴 `pydantic` 未宣告**
`requirements.txt:1-4`

`app/models.py` 直接 `from pydantic import ...`，但 requirements 只列 `fastapi`（transitive）。乾淨環境通常會解析到 v2，但若環境已有 pydantic 1.x 且滿足 FastAPI 的 `>=1.7.4,<3`，`pip install -r` 不會升級，啟動即 `ImportError`。建議 `pydantic>=2.7,<3`（順便釘住 `fastapi`/`starlette` 上限）。

**m2 — SQLite `list()` 的 COUNT 與 SELECT 不在同一交易，`total` 可能與 `items` 不一致**
`app/storage.py:164-173`

兩個 statement 之間若有其他 process 寫入，會出現 `total=26` 但頁面內容屬於舊快照。單 process 有 service 鎖不受影響，屬邊界問題。建議用 `BEGIN`（或單一 `SELECT ..., COUNT(*) OVER ()`）取得一致快照。

**m3 — 405 回應丟掉 `Allow` header，且錯誤碼不在契約表**
`app/main.py:73-88`

`JSONResponse` 沒帶 `exc.headers`，405 會缺 `Allow`（RFC 7231 要求）；`method_not_allowed` / `client_error` 不在 spec §4 的 code 表，屬於契約未定義的回應。建議 `headers=exc.headers`，並在 spec 補這兩個 code（或改回 `not_found` 以外的既有碼）。

**m4 — 404 訊息回顯原始 `object_id`**
`app/service.py:67,93,113`

`找不到物件：{object_id}` 會把使用者可控字串（可長達 KB、含控制字元）放進訊息，造成回應放大與日誌注入面。建議固定訊息（例如「找不到物件」）或截斷/轉義後再放入；若除錯需要，可放進 `details` 並限制長度。

**m5 — in-memory `find_by_name` 為 O(n)，大量建立退化為 O(n²)**
`app/storage.py:72-78`

每次 create/replace 都線性掃描全部物件；1 萬筆以上會明顯變慢（測試 25 筆無感）。可用 `dict[str, str]`（`name_key → id`）索引，並在 create/replace/delete 同步維護；或直接接受並在文件註明 in-memory 僅供測試/開發。

**m6 — 邊界與未覆蓋案例**
`tests/test_validation.py`、`tests/test_read_list.py`、`tests/test_errors.py`

未測：`q` 全空白（只測了空字串）、`offset` 超過 `total`（應 200 + 空陣列）、`model_url` 剛好 2048、`scale` 剛好 1000、`position` 剛好 ±1e6、Unicode casefold（如 `Straße`/`STRASSE`）、PUT 帶非法值（驗證共用 model，但 PUT 路徑未直接驗）、405 envelope、500 envelope。建議至少補「offset 超界」與「PUT 非法值」，其餘可用 parametrize 一次補齊。

### Nit

**n1** `app/service.py:33-38`：`stamp_after` 用**字串**比較時間。目前格式固定所以等價，但若未來匯入帶 `+08:00` 的資料（或 DB 被手工編輯）就會誤判單調性。建議解析成 `datetime` 再比較。
**n2** `tests/test_validation.py:16`：`field_part in detail["field"]` 是子字串斷言，`"name"` 也會匹配 `"model_name"`；建議改成 `detail["field"] == expected` 或 `startswith`。
**n3** `tests/test_read_list.py:11-15`：`_sort_contract` 複製了實作的排序邏輯，屬同義反覆；雖然下方另有 `timestamps == sorted(..., reverse=True)` 的獨立性質斷言，仍建議只保留性質斷言。
**n4** `app/models.py:47`：`Vec3` 的 `extra="ignore"` 讓多餘分量（`w`）通過，與 M1 一併改 `forbid` 較一致。
**n5** `app/routers/objects.py:68-71`：decorator 與 `Response` 都指定 204，重複；保留一處即可（建議 `Response(status_code=204)` + `response_class=Response`）。
**n6** `tests/conftest.py:20-54`：`app_factory`（`delenv XR_DB_PATH`）與 `sqlite_client`（`setenv`）共用同一個 `monkeypatch`，若同一測試同時請求兩個 fixture，結果取決於 fixture 初始化順序。目前無此用法，但屬潛在順序耦合。
**n7** 文件不一致：`reviewer.md:39` 指向不存在的 `docs/api-contract.md`（契約實際在 `docs/spec.md`）；`README.md:14` 連結的 `docs/reflection.md` 目前不存在；測試輸出有 `StarletteDeprecationWarning`（`httpx` + TestClient），未來 Starlette 版本可能移除，可考慮在 CI 抑制或升級。

## 建議的後續工作（依序）

1. **M1**：`extra="forbid"`（含 `Vec3`）+ 未知欄位測試；確認 PUT 打錯字會 422 而不是靜默重設。
2. **M2 + M4**：`SqliteObjectRepository.replace()` 映射 `IntegrityError → 409`、`rowcount == 0 → 404`，並把契約測試參數化到 SQLite（優先：同名 409、改名 409、`q` 轉義、分頁排序、時間戳格式）。
3. **M3**：`create_app` 建 DB 父目錄，或 README 加建立 `data/` 的指令；用乾淨虛擬環境照 README 走一次。
4. **M5**：加 threading 併發測試（同名建立、互相改名），可與 SQLite 參數化共用。
5. **m1**：requirements 直接釘 `pydantic>=2.7,<3`，讓 `pip install -r` 在任何環境都能得到 v2。
6. 其餘 minor/nit 排入 cleanup：405 `Allow`、404 訊息、COUNT/SELECT 一致性、邊界測試。
