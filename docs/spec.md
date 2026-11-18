# XR 場景物件管理 API — 規格書

> 狀態：v1.0（Tech Lead 定稿，作為 coder / tester 的唯一契約來源）
> 技術棧：Python 3.13、FastAPI、Pydantic v2、pytest；儲存位於 `ObjectRepository` 介面之後。

## 1. 範圍

**做**：管理 XR 場景中 3D 物件的 REST API（建立、讀取、列表、完整更新、刪除），含輸入驗證、統一錯誤格式、分頁與名稱搜尋。

**不做**（本版明確排除）：認證/授權、多場景與權限模型、檔案上傳、模型格式驗證（只驗 URL）、即時同步/WebSocket、審計日誌、軟刪除。

## 2. 資料模型

物件（SceneObject）回應欄位：

| 欄位 | 型別 | 必填 | 規則 |
| --- | --- | --- | --- |
| `id` | string | 回應 | UUID4 字串，伺服器產生 |
| `name` | string | ✅ | 去頭尾空白後長度 1–120；**全域唯一**（不分大小寫） |
| `model_url` | string | ✅ | 絕對 URL，scheme 僅 `http`/`https`，需有 host，長度 ≤ 2048 |
| `position` | Vec3 | ❌ | 預設 `{x:0,y:0,z:0}`；單位公尺；每個分量為有限值且介於 −1e6 與 1e6 之間 |
| `rotation` | Vec3 | ❌ | 預設 `{x:0,y:0,z:0}`；單位**度**（Euler，XYZ 順序）；各分量 \|v\| ≤ 360000 |
| `scale` | Vec3 | ❌ | 預設 `{x:1,y:1,z:1}`；每個分量 **> 0** 且 ≤ 1000 |
| `visible` | boolean | ❌ | 預設 `true` |
| `created_at` | string | 回應 | UTC ISO-8601，毫秒精度，結尾 `Z` |
| `updated_at` | string | 回應 | 同上；任何成功更新都會變動 |

`Vec3` 物件必須同時提供 `x`、`y`、`z` 三個數值；`NaN`、`Infinity` 一律拒絕（422）。
名稱唯一性以 `casefold()` 比較：`"Chair"` 與 `"chair"` 視為衝突。

## 3. 端點契約

基礎路徑 `/api/v1`。

| 方法 | 路徑 | 用途 | 成功 | 失敗 |
| --- | --- | --- | --- | --- |
| GET | `/healthz` | 健康檢查 | 200 `{"status":"ok"}` | — |
| GET | `/api/v1/objects` | 列表（分頁＋名稱搜尋） | 200 `{items,total,limit,offset}` | 422 |
| POST | `/api/v1/objects` | 建立 | 201 + `Location` | 409、422 |
| GET | `/api/v1/objects/{object_id}` | 單筆 | 200 | 404 |
| PUT | `/api/v1/objects/{object_id}` | 完整取代 | 200 | 404、409、422 |
| DELETE | `/api/v1/objects/{object_id}` | 刪除 | 204（無 body） | 404 |

### 3.1 列表參數

| 參數 | 型別 | 預設 | 規則 |
| --- | --- | --- | --- |
| `limit` | int | 20 | 1–100，超出 → 422 |
| `offset` | int | 0 | ≥ 0，超出 → 422 |
| `q` | string | 無 | 去空白後 1–64 字元；對 `name` 做不分大小寫子字串比對；空字串或全空白視同未提供 |

排序固定為 `created_at` 降冪、`id` 升冪（保證分頁穩定）。`total` 是**過濾後**的總數。

### 3.2 PUT 語意

完整取代：

- `name`、`model_url` 必填，缺任一 → 422。
- `position`、`rotation`、`scale`、`visible` 未提供時**重設為預設值**（不是保留舊值）。
- `id`、`created_at` 不變；`updated_at` 更新。
- 名稱與**其他**物件衝突 → 409；與自己相同（大小寫不同也算）→ 允許，並以新名稱儲存。

## 4. 錯誤格式

所有錯誤（含 422、404、409、500）都回傳：

```json
{
  "error": {
    "code": "name_conflict",
    "message": "物件名稱已被使用",
    "details": [{"field": "name", "message": "已存在同名物件"}]
  }
}
```

| HTTP | `code` | 情境 |
| --- | --- | --- |
| 404 | `not_found` | 路徑不存在，或 `object_id` 不存在 |
| 409 | `name_conflict` | 名稱重複（建立或改名） |
| 422 | `validation_error` | 欄位驗證失敗、參數越界、JSON 格式錯誤 |
| 500 | `internal_error` | 未預期例外；訊息固定，不洩漏堆疊或路徑 |

`details` 一律是陣列（可為空）。422 的每個項目為 `{"field": "<點路徑，如 scale.y>", "message": "<原因>"}`。

## 5. 架構與介面

```
app/
  main.py             create_app(repository=None) -> FastAPI；例外處理器
  models.py           Vec3、ObjectCreate、ObjectReplace、ObjectResponse、ListResponse
  errors.py           AppError(code, message, details, status) 與子類
  storage.py          ObjectRepository(Protocol) + InMemoryObjectRepository
  service.py          ObjectService：唯一性、時間戳、分頁、PUT 重設語意
  routers/objects.py  端點與查詢參數驗證
```

```python
class ObjectRepository(Protocol):
    def list(self, *, limit: int, offset: int, q: str | None) -> tuple[list[SceneObject], int]: ...
    def get(self, object_id: str) -> SceneObject | None: ...
    def find_by_name(self, name: str) -> SceneObject | None: ...   # casefold 比對
    def create(self, obj: SceneObject) -> SceneObject: ...
    def replace(self, obj: SceneObject) -> SceneObject: ...
    def delete(self, object_id: str) -> bool: ...
    def clear(self) -> None: ...
```

- `SceneObject` 是內部資料類（dataclass 或 Pydantic model 皆可），與 API 的 request/response model 分離。
- `create_app()` 每次呼叫都建立**新的** repository，測試之間互不影響；`repository` 參數供測試注入。

## 6. 併發策略

- `ObjectService` 內持有一把 `threading.Lock`，**建立、取代、刪除**在鎖內完成「查名 → 寫入」，保證名稱唯一檢查與寫入是原子的。
- 讀取（列表/單筆）不取鎖，直接讀取目前快照。
- 時間戳在鎖內產生，確保 `updated_at` 單調不倒退。
- 已知限制：單一 process 內的鎖；多 worker 部署需改用資料庫唯一約束（見 `docs/compare.md`）。

## 7. 範例

建立：

```bash
curl -i -X POST http://127.0.0.1:8000/api/v1/objects \
  -H "Content-Type: application/json" \
  -d '{
    "name": "Chair-01",
    "model_url": "https://cdn.example.com/models/chair.glb",
    "position": {"x": 1.5, "y": 0, "z": -2},
    "rotation": {"x": 0, "y": 90, "z": 0},
    "scale": {"x": 1, "y": 1.2, "z": 1}
  }'
```

```json
{
  "id": "6f5c1f2e-6f3a-4d0e-9d1a-2b8c7e4a1f30",
  "name": "Chair-01",
  "model_url": "https://cdn.example.com/models/chair.glb",
  "position": {"x": 1.5, "y": 0.0, "z": -2.0},
  "rotation": {"x": 0.0, "y": 90.0, "z": 0.0},
  "scale": {"x": 1.0, "y": 1.2, "z": 1.0},
  "visible": true,
  "created_at": "2026-11-18T12:00:00.000Z",
  "updated_at": "2026-11-18T12:00:00.000Z"
}
```

列表：`GET /api/v1/objects?q=chair&limit=10&offset=0`

```json
{"items": [ /* ... */ ], "total": 1, "limit": 10, "offset": 0}
```

錯誤：

```json
{"error": {"code": "validation_error", "message": "請求資料驗證失敗",
 "details": [{"field": "scale.y", "message": "scale 分量必須大於 0"}]}}
```

## 8. 測試案例清單（tester 逐條實作，至少 12 條）

| # | 案例 | 預期 |
| --- | --- | --- |
| T01 | `GET /healthz` | 200 `{"status":"ok"}` |
| T02 | 建立最小物件（只給 name、model_url） | 201；position/rotation 為 0、scale 為 1、visible true；有 `Location` |
| T03 | 建立完整物件後單筆讀取 | 200；欄位值與送出值一致、時間格式以 `Z` 結尾 |
| T04 | 同名建立（含大小寫不同） | 409 `name_conflict`；集合內仍只有 1 筆 |
| T05 | 建立非法 `model_url`（`ftp://`、`javascript:`、相對路徑） | 422 `validation_error`，details 指向 `model_url` |
| T06 | `scale.y = 0` 或負數 | 422；`visible` 非布林亦 422 |
| T07 | 名稱為空、全空白、121 字元 | 422 |
| T08 | PUT 完整更新 | 200；`updated_at` 變動、`created_at` 不變 |
| T09 | PUT 省略 `scale` | 200；scale 重設為 `{1,1,1}`（不是保留舊值） |
| T10 | PUT 缺 `name` 或 `model_url` | 422 |
| T11 | 將 A 改名為 B 的名稱 | 409 `name_conflict`，A 維持原名 |
| T12 | DELETE 後再 GET | 204 → 404 `not_found` |
| T13 | 列表分頁：建立 25 筆，`limit=10&offset=20` | 回 5 筆、`total=25`、排序符合 `created_at` 降冪 |
| T14 | `q` 搜尋不分大小寫 | 只回符合子字串的物件，`total` 為過濾後數量 |
| T15 | `limit=0`、`limit=101`、`offset=-1` | 422 |
| T16 | 操作不存在的 id（GET/PUT/DELETE） | 404 `not_found` |
| T17 | 驗證錯誤格式 | 回應符合 `{"error":{code,message,details[]}}` |
| T18 | 兩個 app 實例互不影響 | 各自建立同名物件皆成功 |

## 9. 後續演進

1. **持久化**：以 `SqliteObjectRepository` 實作同一介面（`docs/compare.md` 已驗證 schema 與效能），環境變數切換。
2. **認證與授權**：API Key 起步，之後改 OAuth2 scope（`objects:read` / `objects:write`），並記錄 `updated_by`。
3. **樂觀鎖**：回應加 `version`/`ETag`，PUT/DELETE 支援 `If-Match`，避免多人同時編輯互相覆蓋。
4. **批次操作**：`POST /api/v1/objects:batch` 以單一交易更新多個座標，降低 WebXR 大量拖曳的往返成本。
5. **可觀測性**：結構化日誌、`/metrics`、每個請求的 `X-Request-ID`。
6. **多場景**：新增 `scene_id` 與 `UNIQUE(scene_id, name)`，端點改為 `/scenes/{id}/objects` 並保留舊路由做相容。
