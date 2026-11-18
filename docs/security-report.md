# XR 場景物件管理 API — 資安審查報告（OWASP Top 10: 2021）

| 項目 | 內容 |
| --- | --- |
| 審查對象 | `app/main.py`、`app/models.py`、`app/errors.py`、`app/service.py`、`app/storage.py`、`app/routers/objects.py` |
| 契約來源 | `docs/spec.md`（v1.0） |
| 審查者 | `team/security`（唯讀；僅寫本檔） |
| 審查日期 | 2026-11-18 |
| 基線驗證 | `py -m pytest -q` → **80 passed, 1 warning in 1.00s** |
| 結論 | **Critical 0 / High 3 / Medium 5 / Low 7**；本 API 目前**不具備上線條件**（無認證 + 無資源上限 + 任意 URL 注入） |

---

## 1. 執行摘要

1. 這個 API 的正確性與注入防護做得相當紮實（全參數化 SQL、`LIKE` 轉義、統一錯誤封套、不把 Pydantic 的 `input` 回吐），但**六個端點全部沒有任何認證/授權**，任何能連到 port 的人都能讀取、篡改、刪除整個場景，且規格書本身把認證列為「不做」（`docs/spec.md:10`）。
2. 最實際可利用的問題是**資源耗盡**：請求 body 沒有大小上限、物件數量沒有上限、沒有速率限制，單一未認證請求（或少量請求）即可讓單 process + `threading.Lock` 的服務 OOM 或長時間卡住（`app/main.py` 無任何 middleware／`app/storage.py:52` 無上限字典）。
3. 第三類問題是**資料完整性信任邊界**：`model_url` 只驗 scheme 與 host 是否存在，接受私有網段、內網主機、含帳密的 URL，且原樣存檔並回傳給會「自動載入 glTF」的 XR 客戶端；搭配 `extra="ignore"`（`app/models.py:91`）讓打錯欄位名的 PUT **默默把物件重設回原點**，是「以為改了其實沒改」的具體成因。

---

## 2. 攻擊面盤點

| 面向 | 事實 | 依據 |
| --- | --- | --- |
| 端點 | 6 個：`GET /healthz`、`GET/POST /api/v1/objects`、`GET/PUT/DELETE /api/v1/objects/{object_id}` | `app/main.py:50`、`app/routers/objects.py:27,43,54,59,68` |
| 輸入 | 全部是 JSON body + query（`limit`/`offset`/`q`）+ path（`object_id`）；無 multipart、無檔案上傳、無 cookie | `app/routers/objects.py:28-33`、`docs/spec.md:10` |
| 驗證層 | Pydantic v2 model validator（`AfterValidator` 驗 URL、`Field` 驗範圍）＋ `service` 內對 `q` 長度的補充驗證 | `app/models.py:21-41,44-98`、`app/service.py:50-61` |
| 認證/授權 | **完全沒有**（無 `Depends` 安全相依、無 API Key、無 middleware、無 CORS） | grep `app/` 僅命中 `Depends(get_service)`（`app/routers/objects.py:24`） |
| 錯誤輸出 | 統一 `{"error":{code,message,details}}`；422 只吐 `field`/`message`，不回 `input` | `app/errors.py:10-22,125-126`、`app/main.py:56-95` |
| 日誌 | **完全沒有** logging／audit／request id | grep `logging|logger|print(` 在 `app/` 無命中 |
| 儲存 | 預設 `InMemoryObjectRepository`（dict）；`XR_DB_PATH` 存在時切 `SqliteObjectRepository`（WAL） | `app/main.py:35-40`、`app/storage.py:48-96,131-141` |
| 併發 | 單 process `threading.Lock` + repository 內 lock；多 worker 需靠 DB 唯一約束 | `app/service.py:44`、`docs/spec.md:112-117` |
| 依賴 | `fastapi>=0.115.0`、`uvicorn>=0.30.0`、`pytest>=8.0.0`、`httpx>=0.27.0`（僅下界、無 lock、無 hash） | `requirements.txt:1-4` |

---

## 3. 風險總覽（A01–A10）

| # | 項目 | 判定 | 嚴重度 | 一句話依據 |
| --- | --- | --- | --- | --- |
| A01 | Broken Access Control | **applicable** | **High** | 6 個端點無任何認證；物件無擁有者概念，任何人可 CRUD 全部資料（`app/routers/objects.py:27-71`、`docs/spec.md:10`） |
| A02 | Cryptographic Failures | **applicable** | Medium | 應用層不做 TLS 強制、無 HSTS；README 的啟動指令是純 HTTP（`README.md:33`）；SQLite 檔/WAL 用預設權限建立（`app/storage.py:136-141`） |
| A03 | Injection | **mitigated** | Low（殘餘） | 全部 SQL 參數化、`LIKE` 有 `ESCAPE` 轉義（`app/storage.py:120-128,162-163,196-214,223-238`）；無 shell/eval/模板注入；殘餘僅 casefold/LIKE 語意差異（非安全） |
| A04 | Insecure Design | **applicable** | **High** | 無 body 大小上限、無物件數上限、無速率限制、`offset` 無上界、無樂觀鎖（`app/main.py`、`app/routers/objects.py:31`、`app/storage.py:52`） |
| A05 | Security Misconfiguration | **applicable** | Medium | `/docs`、`/redoc`、`/openapi.json` 預設開啟且無認證（`app/main.py:42-46`）；`Server: uvicorn` 未關（`README.md:33`）；無任何安全標頭 |
| A06 | Vulnerable & Outdated Components | **applicable** | Medium | 依賴只有浮動下界、無 lock/hash（`requirements.txt:1-4`）；宣告的下界允許落入已知 CVE 的 starlette 版本範圍（見 S-08） |
| A07 | Identification & Auth Failures | **not applicable** | — | 系統不存在任何身分機制（無密碼、無 token、無 session），無「可失敗的認證」；後果歸入 A01 |
| A08 | Software & Data Integrity Failures | **applicable** | **High** | 未信任的 `model_url` 未經 allowlist／雜湊即進入場景並下發給客戶端自動載入（`app/models.py:27-41`）；`/docs` 由第三方 CDN 載入 JS 且無 SRI（`app/main.py:42`） |
| A09 | Logging & Monitoring Failures | **applicable** | Medium | 無任何日誌；`Exception` handler 吞掉例外且不記錄（`app/main.py:90-95`）→ 事故無痕、500 靜默 |
| A10 | SSRF | **not applicable（server-side）** | Low（client-side） | 伺服器從不 fetch `model_url`，只做字串驗證與儲存（`app/models.py:27-38`）；下游 XR 客戶端會載入該 URL，風險併入 S-03 |

> 判定用語：`applicable` = 問題存在且需要處理；`mitigated` = 有對應控制且有程式碼依據；`not applicable` = 該類風險在此架構下沒有作用面。

---

## 4. 發現明細

### S-01（A01）未認證的完整 CRUD：任何訪客可讀寫刪整個場景 — **High**

**位置**
- `app/routers/objects.py:17`（`APIRouter(prefix="/api/v1")` 無 `dependencies=`）
- `app/routers/objects.py:20-24`（`get_service` 只注入 service，不做任何身分檢查）
- `app/routers/objects.py:43-71`（建立/讀取/取代/刪除全開）
- `app/main.py:42-54`（`FastAPI(...)` 無 `dependencies`、無 `add_middleware`）
- `docs/spec.md:10`（認證/授權明確列為「不做」）

**攻擊情境**
1. 服務以 `py -m uvicorn app.main:create_app --factory` 起在 `0.0.0.0:8000`（或放在內部網段被任意主機觸及）後，攻擊者 `GET /api/v1/objects?limit=100` 遞迴列舉即可 dump 整個場景（`total` 直接給總數，`app/routers/objects.py:35-40`）。
2. 攻擊者對每個 id 發 `DELETE`，或 `PUT` 把所有 `position` 改成 `{0,0,0}`／`visible:false`，場景在數秒內被清空或破壞，且**沒有任何日誌可追溯**（S-06）。
3. 因為無 `scene_id` 與擁有者模型（`docs/spec.md:192`），多租戶／多團隊共用一個部署時，A 團隊可讀寫 B 團隊的物件——這是教科書級的 IDOR/BOLA（OWASP API1）。

**嚴重度理由**：不是 RCE、不直接洩漏憑證，但對「場景資料」是完整的機密性＋完整性破壞，且利用門檻為 0（單一 curl）。

**修正建議（範例）**
```python
# app/security.py
import secrets
from fastapi import Depends, Security
from fastapi.security import APIKeyHeader
from .errors import AppError

_api_key = APIKeyHeader(name="X-API-Key", auto_error=False)

def require_api_key(key: str | None = Security(_api_key)) -> str:
    expected = settings.API_KEY           # 由環境變數注入，不寫死在 repo
    if not key or not secrets.compare_digest(key, expected):
        raise AppError("unauthorized", "未授權", 401)
    return key
```
```python
# app/routers/objects.py
router = APIRouter(
    prefix="/api/v1",
    tags=["objects"],
    dependencies=[Depends(require_api_key)],   # 讀寫都保護
)
```
長期依 `docs/spec.md:188` 改成 OAuth2 scope（`objects:read` / `objects:write`），並在 `SceneObject` 加 `owner_id`／`scene_id`，在 repository 查詢層就過濾（不要只在 service 判斷）。

---

### S-02（A04）無 body 大小上限 + 無物件數上限 + 無速率限制 → 未認證 DoS — **High**

**位置**
- `app/main.py:42-54`：沒有任何 middleware，因此沒有任何 `Content-Length` 檢查、併發限制或速率限制。
- `app/models.py:84-98`：`ObjectWrite` 沒有整體 payload 大小概念，只有個別欄位上限（`name` 120、`model_url` 2048）。
- `app/storage.py:52`：`self._items: dict[str, SceneObject] = {}` 無上限。
- `app/routers/objects.py:31`：`offset: Annotated[int, Query(ge=0)]` 無上界。
- `app/service.py:44`：全域 `threading.Lock`，寫入序列化 → 一個慢請求即可擋住所有寫入。

**攻擊情境**
1. **單請求 OOM**：`POST /api/v1/objects` 帶 200 MB 的 `{"name":"a","model_url":"https://a/" ,"pad": "<200MB 字串>"}`。Starlette 會 `await request.body()` 把整個 body 讀進記憶體，再由 `json.loads` 產生額外物件 → 瞬時數 GB RSS。因為 `extra="ignore"`（`app/models.py:91`），那個巨大欄位甚至不會被回報為錯誤，請求只是「成功或 422」。
2. **深度巢狀 CPU/RecursionError**：`position` 塞入 2000 層巢狀物件 → `json.loads` 觸發 `RecursionError`（非 `RequestValidationError`）→ 被 `app/main.py:90` 的 `Exception` handler 接住回 500，違反 `docs/spec.md:81` 的「JSON 格式錯誤 → 422」契約，且是一次 CPU 尖峰。
3. **無限物件**：腳本迴圈 `POST`（每次 < 2.5 KB）即可讓記憶體 repository 無上限成長；`GET /api/v1/objects` 每次都在**未取鎖的複製**上排序（`app/storage.py:59-66`），資料量越大，讀取越貴。
4. **慢速 body**：不帶 `Content-Length` 用 chunked 慢慢送，佔住 worker；單 process 部署時直接全站不可用。

**修正建議**
```python
# app/main.py —— 在 create_app 內
MAX_BODY_BYTES = 64 * 1024

@app.middleware("http")
async def guard_body_size(request: Request, call_next):
    cl = request.headers.get("content-length")
    if cl is not None and (not cl.isdigit() or int(cl) > MAX_BODY_BYTES):
        return JSONResponse(
            status_code=413,
            content=error_payload("payload_too_large", "請求內容過大", []),
        )
    return await call_next(request)
```
- 反向代理層再加硬上限（nginx `client_max_body_size 64k;`、`limit_req`；uvicorn `--limit-concurrency 100`）。
- repository 加上限：`MAX_OBJECTS = 10_000`，`create()` 超過即 `AppError("quota_exceeded", ..., 429)`。
- `offset` 補上界（例如 `Query(ge=0, le=100_000)`，`app/routers/objects.py:31`）。
- `q` 已經在 service 限 64 字元（`app/service.py:53-61`），這點是好的；但它在 query 解析後才檢查，超大 query string 仍先被 Starlette 解析，建議在 `Query(max_length=64)` 宣告（`app/routers/objects.py:32`）。

---

### S-03（A08／A10-client）`model_url` 無目的地政策與完整性驗證，且被下發給會自動載入的客戶端 — **High**

**位置**
- `app/models.py:27-41`：只檢查 `len<=2048`、`scheme in {http,https}`、`netloc` 非空。
- `app/service.py:79,100`：原樣寫入 `SceneObject.model_url`。
- `app/models.py:111`、`app/storage.py:106`：原樣回傳給任何呼叫者。

**實際接受、但應該拒絕的輸入（依程式碼路徑推導）**

| 輸入 | 結果 | 原因 |
| --- | --- | --- |
| `http://169.254.169.254/latest/meta-data/` | **接受** | scheme/host 都合法；雲端 metadata 端點（`app/models.py:34-37`） |
| `http://127.0.0.1:8080/admin` | **接受** | 同上，可當成「把內網位址寫進場景」的跳板 |
| `https://user:pass@cdn.example.com/m.glb` | **接受** | 只檢查 `netloc` 非空，未檢查 `username/password` → 憑證被存進 DB 並在回應中回吐 |
| `https://cdn.example.com/../../etc/passwd` | **接受** | 不做 path 正規化（對本 API 無害，但客戶端可能據此拼接資產路徑） |
| `file:///C:/Windows/win.ini` | 拒絕 | `scheme` 不在白名單（`app/models.py:34`）✅ |
| `javascript:alert(1)` | 拒絕 | 同上 ✅（已有測試 `tests/test_validation.py:23`） |
| `https://` | 拒絕 | `netloc` 空（`app/models.py:36`）✅ |
| `//evil.example/m.glb` | 拒絕 | scheme 為空 ✅ |
| `HTTPS://CDN.EXAMPLE.COM/m.glb` | **接受** | `urlsplit` 會 lowercase scheme，故大小寫繞過無效（正確行為） |

**攻擊情境**
XR 客戶端（WebXR / Unity / Three.js）拿到清單後通常**直接 loader.load(model_url)**。攻擊者（S-01：無需帳號）把自己控制的 `https://evil.example/chair.glb` 寫進共用場景，之後任何使用者打開該場景：
- 客戶端向攻擊者網域發出請求 → 洩漏使用者 IP、Referer、時間；
- 載入惡意 glTF/GLB（歷史上多個 parser 有記憶體破壞/DoS 問題），把「內容信任」外包給一個未驗證的第三方；
- 若客戶端有內網可達性，`http://169.254.169.254/...` 或 `http://192.168.x.x/` 就是 client-side SSRF（伺服器本身不 fetch，故 A10 server-side 不成立，但風險在下游實現）。

**修正建議**
```python
# app/models.py
import ipaddress
from urllib.parse import urlsplit

ALLOWED_MODEL_HOSTS = {"cdn.example.com", "assets.example.com"}   # 由設定注入

def _check_model_url(value: str) -> str:
    if len(value) > MODEL_URL_MAX_LENGTH:
        raise ValueError(f"model_url 長度不可超過 {MODEL_URL_MAX_LENGTH} 個字元")
    parts = urlsplit(value)
    if parts.scheme not in {"http", "https"}:
        raise ValueError("model_url 僅允許 http 或 https")
    if parts.username or parts.password:
        raise ValueError("model_url 不可包含帳號或密碼")
    host = (parts.hostname or "").rstrip(".").lower()
    if not host:
        raise ValueError("model_url 必須包含 host")
    try:
        ip = ipaddress.ip_address(host)
    except ValueError:
        ip = None
    if ip is not None and (ip.is_private or ip.is_loopback or ip.is_link_local or ip.is_reserved):
        raise ValueError("model_url 不可指向內部網段")
    if host not in ALLOWED_MODEL_HOSTS:
        raise ValueError("model_url 的網域不在允許清單")
    return value
```
另外：回應加 `model_sha256` 欄位（載入前驗雜湊），並在客戶端把模型載入放進 sandbox/獨立 origin；`docs/spec.md:10` 已把「模型格式驗證」排除，但「URL 目的地政策」屬於本 API 該做的。

---

### S-04（A04／A08）`extra="ignore"` 讓打錯的欄位名被默默吞掉，PUT 因此把物件重設回預設值 — **Medium**

**位置**
- `app/models.py:91`：`model_config = ConfigDict(extra="ignore")`（`ObjectWrite`，POST 與 PUT 共用）
- `app/models.py:47`：`Vec3` 同樣 `extra="ignore"`
- `app/models.py:95-98`：`position/rotation/scale/visible` 都有 default → 缺席即套預設
- `app/service.py:97-107`：`replace()` 完全由 `payload` 重建，不讀舊值

**為什麼是真問題（不是通用清單）**
PUT 是「完整取代」，規格要求未提供的欄位重設（`docs/spec.md:59`，並由 `tests/test_update_put.py:80-105` 證明會重設）。因為 `extra="ignore"`，**拼錯的鍵在驗證階段就被丟掉**，於是「打錯字」與「刻意省略」在伺服器眼中完全一樣：

```json
PUT /api/v1/objects/{id}
{"name":"Chair","model_url":"https://cdn.example.com/c.glb",
 "positon":{"x":9,"y":9,"z":9},   // 少一個 i
 "visble": false}                 // 少一個 i
```
預期（使用者認知）：物件移動到 (9,9,9) 並隱藏。
實際：`200 OK`，`position` 變成 `{0,0,0}`、`visible` 變成 `true` —— 物件「跳回原點並重新出現」，而客戶端收到 200 不會有任何警示。在 XR 編輯器裡，這就是「以為改了其實沒改，而且原本的位置被洗掉」。

同理 POST 帶 `"scal":{"x":2,...}` 會回 201 但存成 `{1,1,1}`；`Vec3` 內打錯 `"xx"` 也會被忽略，只報缺 `x`。

**嚴重度理由**：需要使用者打錯字才會觸發，但後果是靜默的資料毀損，且 PUT 的「重設」語意把傷害放大。

**修正建議**
```python
# app/models.py
class Vec3(BaseModel):
    model_config = ConfigDict(extra="forbid")

class ObjectWrite(BaseModel):
    model_config = ConfigDict(extra="forbid")
```
Pydantic 會回 `extra_forbidden`，錯誤封套會指出欄位路徑；再補一條 `errors.py` 的訊息映射讓它好讀：
```python
# app/errors.py:_message_for
if kind == "extra_forbidden":
    return "未知欄位（請檢查欄位名稱是否拼錯）"
```
若擔心破壞相容性，至少對 PUT 用 `extra="forbid"`、POST 維持 `ignore`，並在文件標明。

---

### S-05（A05／A08）`/docs`、`/redoc`、`/openapi.json` 公開，且 Swagger UI 從第三方 CDN 載入 JS — **Medium**

**位置**
- `app/main.py:42-46`：`FastAPI(title=..., version=...)` 未指定 `docs_url=None, redoc_url=None, openapi_url=None`。
- `README.md:39`：把 `http://127.0.0.1:8000/docs` 當作對外說明。

**攻擊情境**
1. 未認證的 `GET /openapi.json` 洩漏完整內部契約（欄位、邊界值、錯誤碼），讓 S-02／S-03 的 payload  crafting 變得零成本。
2. `/docs` 的 HTML 內含指向 `cdn.jsdelivr.net` 的 `swagger-ui-bundle.js`／CSS，**沒有 SRI**。任何能影響該 CDN（或使用者網路上的中間人／企業 proxy）的人，都能在 API 的 origin 內執行任意 JS，直接呼叫未認證 API 讀寫場景。

**修正建議**
```python
app = FastAPI(
    title="XR Scene Object API",
    version="1.0.0",
    lifespan=_lifespan(repository),
    docs_url=None if os.environ.get("XR_ENV") == "prod" else "/docs",
    redoc_url=None,
    openapi_url=None if os.environ.get("XR_ENV") == "prod" else "/openapi.json",
)
```
若非要在 prod 提供文件，改成自架 swagger-ui 靜態檔（同源）＋掛在 `require_api_key` 之後。

---

### S-06（A09）完全沒有日誌，500 例外被靜默吞掉 — **Medium**

**位置**
- `app/main.py:90-95`：`@app.exception_handler(Exception)` 直接回固定訊息，**沒有 `logger.exception(...)`**（Starlette 註冊了 `Exception` handler 後，`ServerErrorMiddleware` 不再輸出 traceback）。
- 全 `app/` 無 `logging` 匯入（grep 無命中）。
- `app/service.py:67,93,113`：`NotFoundError` 把使用者輸入的 `object_id` 直接拼進 message，但因為沒有日誌，這條線索也不會被留下。

**攻擊情境**
S-01 的刪除風暴、S-02 的 OOM 迴圈、S-03 的惡意 URL 注入，在本服務上**都不會留下任何紀錄**：沒有 request log、沒有 4xx/5xx 計數、沒有速率異常告警、沒有 `X-Request-ID`（`docs/spec.md:191` 已列為後續）。事故發生時無法回答「誰在什麼時候刪了什麼」。

**修正建議**
```python
import logging, uuid
logger = logging.getLogger("xr.api")

@app.middleware("http")
async def request_id(request: Request, call_next):
    rid = request.headers.get("x-request-id") or uuid.uuid4().hex
    request.state.request_id = rid
    response = await call_next(request)
    response.headers["X-Request-ID"] = rid
    logger.info("%s %s -> %s rid=%s", request.method, request.url.path,
                response.status_code, rid)
    return response

@app.exception_handler(Exception)
async def handle_unexpected(request: Request, exc: Exception) -> JSONResponse:
    rid = getattr(request.state, "request_id", "-")
    logger.exception("unhandled error rid=%s path=%s", rid, request.url.path)
    return JSONResponse(
        status_code=500,
        content=error_payload("internal_error", "伺服器發生未預期錯誤",
                              [{"field": "request_id", "message": rid}]),
    )
```
寫入類操作（POST/PUT/DELETE）建議記 `object_id`、結果碼、來源 IP；**不要**記完整 body（會把 `model_url` 裡的帳密寫進日誌）。

---

### S-07（A02）傳輸層與儲存檔案的機密性沒有被處理 — **Medium**

**位置**
- `README.md:33`：`py -m uvicorn app.main:create_app --factory --reload` —— 純 HTTP、無 `--ssl-keyfile`，且 `--reload` 是開發模式。
- `app/main.py`：無 `HTTPSRedirectMiddleware`、無 HSTS。
- `app/storage.py:136-141`：`sqlite3.connect(path)` + WAL，未收緊檔案權限。

**攻擊情境**
場景資料（含 S-03 提到可能被塞進 URL 的帳密）以明文 HTTP 傳輸，同網段可被動嗅探／竄改（改 `position` 或 `model_url` 的回應）；SQLite 檔在共用主機上以預設 umask 建立，其他本機使用者可讀。

**修正建議**
- 由反向代理終結 TLS，並在 app 加 `HTTPSRedirectMiddleware` + `Strict-Transport-Security: max-age=63072000; includeSubDomains`。
- 啟動參數移除 `--reload`，加 `--no-server-header`、`--proxy-headers --forwarded-allow-ips`。
- SQLite：`os.chmod(db_path, 0o600)`（POSIX）／在 Windows 限制 ACL；`XR_DB_PATH` 指向非 web 根目錄。

---

### S-08（A06）依賴只有浮動下界、無 lock/hash；宣告的下界可落入已知 CVE 版本 — **Medium**

**位置**：`requirements.txt:1-4`

```
fastapi>=0.115.0
uvicorn>=0.30.0
pytest>=8.0.0
httpx>=0.27.0
```

**依據與推理**
- 只有下界，**沒有上界、沒有 lock file、沒有 `--require-hashes`** → 每一次 `pip install -r requirements.txt` 都可能得到不同版本；本機實際解析到的 pytest 是 **9.2.0**（見 `tests/__pycache__/*.cpython-313-pytest-9.2.0.pyc`），而下界寫 8.0.0，證明「宣告」與「實際」已經脫鉤。
- FastAPI 0.115.0 的 `install_requires` 允許 `starlette>=0.37.2,<0.41.0`；**Starlette 0.37.x–0.39.x 落在 CVE-2024-47874（multipart/form-data 每個 part 無上限緩衝 → DoS）的影響範圍**，修補在 0.40.0。本專案的 `requirements.txt` **沒有** `python-multipart`，且沒有任何端點使用 `request.form()`／`UploadFile`（`docs/spec.md:10` 明確排除檔案上傳），因此**目前不可達、不可利用**；但只要有人日後加一個上傳端點，這條路徑就會打開。
- 反向的風險也成立：`>=` 讓「已修補」與「未修補」無法從檔案判斷，弱點掃描器只能回報「未知版本」。

**修正建議**
```text
# requirements.in（人類維護）
fastapi==0.121.2
uvicorn[standard]==0.38.0
httpx==0.28.1
pytest==9.2.0
```
```bash
pip-compile --generate-hashes -o requirements.txt requirements.in
pip install --require-hashes -r requirements.txt
```
並在 CI 加 `pip-audit -r requirements.txt`（此處不執行，僅建議）。

---

### S-09（A05）`Server: uvicorn` 與框架版本指紋 — **Low**

**位置**：`README.md:33`（未加 `--no-server-header`）；`app/main.py:42-46` 未自訂 header。
**情境**：回應標頭直接告訴攻擊者後端是 uvicorn（搭配 `/docs` 的 HTML 可再確認 FastAPI/Swagger 版本），讓 S-02 的 payload 更精準。
**修正**：`uvicorn ... --no-server-header`，並在反向代理統一改寫 `Server`；同時加上 `X-Content-Type-Options: nosniff`、`Referrer-Policy: no-referrer`、`Content-Security-Policy: default-src 'none'`（API 回應不需要任何外部資源）。

---

### S-10（A04）`offset` 無上界、深度巢狀 JSON 回 500 而非 422 — **Low**

**位置**：`app/routers/objects.py:31`（`Query(ge=0)` 無 `le`）；`app/main.py:90-95`（`Exception` handler 把 `RecursionError` 收成 500）。
**情境**：`GET /api/v1/objects?offset=1000000000` 在 SQLite 需要掃過整個索引；`POST` 帶 2000 層巢狀 `position` 會得到 500（違反 `docs/spec.md:81` 契約），且是可重複觸發的 CPU 成本。
**修正**：`offset: Annotated[int, Query(ge=0, le=100_000)]`；在 `_lifespan` 前加 body 深度/大小防護（S-02），並把 `RecursionError` 明確映射為 422 `validation_error`。

---

### S-11（A08）名稱未做 Unicode 正規化，可用零寬／雙向字元偽造同名物件 — **Low**

**位置**：`app/models.py:21-24`（只做 `strip_whitespace`、長度）；唯一性用 `casefold()`（`app/storage.py:73,186`、`docs/spec.md:29`）。
**情境**：`"Chair"` 與 `"Cha\u200bir"`（零寬空格）或 `"Ch\u0430ir"`（西里爾 `а`）在 `casefold` 下不相等 → 可建立兩個「看起來一樣」的物件；`"Evil\u202Egnp.exe"` 這類 RTL override 會讓 UI 顯示的順序與實際字元相反。因為名稱會原樣出現在 JSON 並被 XR 管理介面渲染（S-01：任何人都能寫），可用於誘導使用者操作錯誤物件。
**修正**
```python
import unicodedata

def _check_name(value: str) -> str:
    value = unicodedata.normalize("NFKC", value)
    if any(unicodedata.category(ch) in {"Cc", "Cf"} for ch in value):
        raise ValueError("name 不可包含控制字元或雙向文字字元")
    if not 1 <= len(value) <= 120:
        raise ValueError("name 長度必須為 1–120 個字元")
    return value
```
並以 `unicodedata.normalize("NFKC", name).casefold()` 作為唯一性鍵（`name_key`）。

---

### S-12（A05）錯誤訊息回吐使用者輸入；`object_id` 長度無限制 — **Low**

**位置**：`app/service.py:67,93,113`（`f"找不到物件：{object_id}"`）、`app/errors.py:53-58`（`f"已存在同名物件：{name}"`）。
**為什麼只是 Low**：回應 `Content-Type: application/json`（由 `main.py:58-61` 的 `JSONResponse` 保證），瀏覽器不會 sniff 成 HTML，`/docs` 也不把回應插進 DOM → **不是 XSS**。但任何把 `error.message` 當 HTML 顯示的第三方客戶端就會變成反射式注入；且路徑參數無長度上限，`GET /api/v1/objects/<100KB>` 會把 100KB 原樣回吐（放大係數 ~1、成本低，仍是不必要的行為）。
**好消息（已緩解）**：422 的 `details` 只輸出 `field`/`message`，**沒有** Pydantic 預設會帶的 `input` 值（`app/errors.py:125-126`），所以超大或敏感的輸入不會被回吐；`_message_for` 也把大部分 Pydantic 訊息改寫成固定中文（`app/errors.py:89-119`）。
**修正**：訊息改為不含輸入（`"找不到資源"`），需要除錯時把 id 放進 `details` 並配合 S-06 的 `X-Request-ID`；path 參數加 `max_length=36` 並驗證 UUID 格式。另注意 `_message_for` 的 fallback `return msg`（`app/errors.py:122`）在 Pydantic 改版新增錯誤型別時會直接把原始英文訊息外露，建議 fallback 改成固定字串。

---

### S-13（A04）SQLite `replace()` 未處理 `IntegrityError` → 多 worker 下 409 變成 500 — **Low**

**位置**：`app/storage.py:221-240`（`UPDATE` 無 try/except）對比 `app/storage.py:216-218`（`create` 有接 `IntegrityError` → 409）。
**情境**：`name_key` 是 `UNIQUE`（`app/storage.py:105`）。`ObjectService._lock` 只在**單 process** 內有效（`docs/spec.md:117` 自述此限制）。兩個 worker 同時 PUT 成同一個名字時，service 的 `find_by_name` 都看到「沒有衝突」，第二個 `UPDATE` 撞唯一約束 → 未捕捉的 `sqlite3.IntegrityError` → 走 `main.py:90` 回 500 `internal_error`，而契約要求 409 `name_conflict`（`docs/spec.md:41`）。同理 `database is locked` 也會變 500。
**修正**：`replace()` 包 `try/except sqlite3.IntegrityError: rollback; raise NameConflictError(obj.name)`；並在部署文件寫明「多 worker 一律用 SQLite/Postgres，不可用 in-memory」。

---

### S-14（A04）數值欄位為 lax 模式，字串 `"1.5"` 會被接受 — **Low**

**位置**：`app/models.py:49-51,55-69`（`float` 未設 `strict=True`）。
**情境**：`{"scale":{"x":"2","y":1,"z":1}}` 會被 Pydantic 轉成 `2.0` 並回 201。測試只涵蓋 `"not-a-number"`（`tests/test_validation.py:189`）。這讓「客戶端送錯型別」變成靜默成功，掩蓋上游 bug（與 S-04 同類的「以為改了其實沒改」）。
**修正**：`model_config = ConfigDict(extra="forbid", strict=True)`，或 `Field(strict=True, ...)`；`visible` 已經是 `StrictBool`（`app/models.py:98`），作風一致。

---

### S-15（A05）`XR_DB_PATH` 為任意檔案路徑，且無啟動期檢查 — **Low**

**位置**：`app/main.py:35-40`。
**情境**：任何能設定環境變數的人可讓服務在任意路徑建立 SQLite 檔（覆寫/佔位攻擊）；若部署時誤指到 web 根目錄，DB 可被靜態伺服器直接下載。目前無目錄建立、無權限檢查、無「必須是絕對路徑」驗證。
**修正**：啟動時驗證 `Path(db_path).is_absolute()`、父目錄存在、檔案權限 `0o600`，並在 log 印出（不含敏感內容）實際使用的儲存體類型。

---

## 5. 已驗證／未能驗證的項目（誠實揭露）

### 5.1 工具權限阻擋（依角色規則立即停止，未換路徑重試）

| 嘗試 | 結果 |
| --- | --- |
| `py -c "import fastapi, starlette, ...; print(version)"` | **Permission denied: shell**（角色白名單只允許 `py -m pytest*`，見 `.opencode/agents/team/security.md:19-21`、`docs/permissions.md:29`） |
| `glob` 讀 `site-packages` 的 `*.dist-info/METADATA` | **Permission denied: external_directory** |
| `py -m pytest -q` | ✅ 允許：**80 passed, 1 warning in 1.00s** |

因此**「用 `py -c` + `TestClient` 自建 payload」這條路不可行**（`py -c` 與任何暫存腳本都會被拒；也不被允許寫入 `tests/`）。以下改用兩條合法證據來源：(a) 剛剛實際執行、且涵蓋多數 payload 的既有測試；(b) 由上而下的程式碼路徑推導（Pydantic 與 Starlette 的行為在這些路徑上是決定性的，非猜測）。

### 5.2 三類必測輸入的結果

| # | 輸入 | 結果 | 證據類型 |
| --- | --- | --- | --- |
| 1 | 超長 `name`（121 字元）、空白 name | **422 `validation_error`，`field` 指向 `name`** | ✅ 實測（`tests/test_validation.py:78-92`，本次 80 passed 的一部分） |
| 1b | `scale.y = NaN / Infinity / -Infinity`（raw JSON token） | **422，`finite_number` → 「必須是有限數值」** | ✅ 實測（`tests/test_validation.py:166-181`） |
| 1c | `model_url` 超過 2048 字元 | **422** | ✅ 實測（`tests/test_validation.py:39-47`） |
| 2 | `javascript:alert(1)`、`https://`（無 host）、`//cdn...`、`models/x.glb`、`ftp://` | **422，`field` = `model_url`** | ✅ 實測（`tests/test_validation.py:19-37`） |
| 2b | `file:///etc/passwd`、`file:///C:/Windows/win.ini` | **422**（`urlsplit` 得到 scheme `file` → 不在白名單） | 程式碼推導（`app/models.py:34`；與已實測的 `ftp://` 走同一分支，故可信度高） |
| 2c | `http://169.254.169.254/...`、`https://user:pass@cdn/...` | **201 接受（這是 S-03 的缺陷）** | 程式碼推導（`app/models.py:34-37` 只驗 scheme/netloc） |
| 3 | 未知欄位 `nmae` / `positon` / `visble` | **被 `extra="ignore"` 丟棄；`nmae` 造成 422「必填欄位 name」，`positon`/`visble` 造成 200 但值被重設為預設** | 程式碼推導（`app/models.py:91` + `app/models.py:95-98` + `app/service.py:97-107`；「省略即重設」已由 `tests/test_update_put.py:80-105` 實測證明，打錯字與省略在驗證後無差別） |
| 4 | `__proto__` 鍵（prototype pollution 嘗試） | **無效**（Python `dict`/Pydantic 無 prototype 概念，且 `extra="ignore"` 直接丟棄） | 語言層事實 |

### 5.3 錯誤輸出與標頭

| 檢查 | 結果 | 依據 |
| --- | --- | --- |
| 500 是否洩漏 traceback/路徑 | **不會**：固定字串「伺服器發生未預期錯誤」，`details: []` | `app/main.py:90-95`、`app/errors.py:92-95` |
| 422 是否回吐 `input` 值 | **不會**：只回 `field`/`message` | `app/errors.py:125-126` |
| 404/405 是否走統一封套 | 是（`not_found` / `method_not_allowed`） | `app/main.py:73-88` |
| `Server` 標頭 | **會**出現 `uvicorn`（啟動指令未關閉） | `README.md:33` |
| CORS | **完全未設定**（無 `CORSMiddleware`）→ 不存在 `*` + credentials 的誤配置；瀏覽器預設阻擋跨源讀取。代價：未來若加 `allow_origins=["*"]` **且** `allow_credentials=True` 就會立刻變成漏洞 | grep `CORSMiddleware|add_middleware` 在 `app/` 無命中 |
| `Location` 標頭 | **相對路徑**（`/api/v1/objects/{id}`）→ 不會被 `Host` header 注入汙染 | `app/routers/objects.py:50` |
| 安全標頭（HSTS/nosniff/CSP） | **全部沒有** | `app/main.py:42-54` |
| SQL 注入 | **已緩解**：全部 `?` 參數化；`q` 走 `LIKE ... ESCAPE '\'` 且 `%`/`_`/`\` 都被轉義 | `app/storage.py:120-128,160-163,176-189,191-246` |

---

## 6. 這個 API 上線前必做的 5 件事

1. **補上認證與物件級授權**（S-01）：`APIRouter(..., dependencies=[Depends(require_api_key)])` 起步，並在資料模型加 `owner_id`/`scene_id`，在 repository 查詢層過濾；`healthz` 以外不留任何匿名端點。
2. **設下資源護欄**（S-02）：64 KB body 上限 middleware + 反向代理 `client_max_body_size`／`limit_req` + `MAX_OBJECTS` 配額 + `uvicorn --limit-concurrency`；`offset` 補 `le`。沒有這一項，單一 curl 就能讓服務倒下。
3. **建立 `model_url` 目的地政策**（S-03）：scheme 白名單之外，加 host allowlist、拒絕私有/loopback/link-local IP、拒絕含帳密的 URL；回應加雜湊供客戶端驗證；客戶端在獨立 origin/sandbox 載入模型。
4. **把「靜默錯誤」變成「大聲錯誤」**（S-04、S-06）：`ObjectWrite`/`Vec3` 改 `extra="forbid"`（至少 PUT），並補結構化日誌、`X-Request-ID`、`logger.exception` 於 500 handler；否則打錯字與惡意操作都無痕。
5. **收緊部署組態與供應鏈**（S-05、S-07、S-08）：prod 關閉 `/docs`/`/redoc`/`/openapi.json`（或保護）、`--no-server-header`、移除 `--reload`、加上 HSTS/nosniff/CSP、以 TLS 對外；依賴改成 `==` + hash lock（`pip-compile --generate-hashes`）並納入 `pip-audit`。

---

## 7. 附錄：本次審查的嚴重度統計

| 嚴重度 | 數量 | 編號 |
| --- | --- | --- |
| Critical | 0 | — |
| High | 3 | S-01、S-02、S-03 |
| Medium | 5 | S-04、S-05、S-06、S-07、S-08 |
| Low | 7 | S-09、S-10、S-11、S-12、S-13、S-14、S-15 |

**整體判定**：`app/` 的**輸入驗證與注入防護品質高於平均**（參數化 SQL、LIKE 轉義、嚴格錯誤封套、不回吐 input），但**邊界防護（認證、資源上限、內容信任）為零**。三者皆為 High，且都可在不改動任何業務邏輯的前提下、以 middleware／依賴注入／一行設定修補。
