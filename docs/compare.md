# 儲存方案比較：SQLite vs PostgreSQL vs MongoDB

> 產出方式：主 Agent 同時啟動 **3 個 `team/db-bench` 子代理**，各自只看一種方案、互不影響；
> 三者使用事先約定的同一份 JSON 結構回報，由主 Agent 彙整排序。
> 原始資料：[`bench/sqlite.json`](../bench/sqlite.json)、[`bench/postgresql.json`](../bench/postgresql.json)、[`bench/mongodb.json`](../bench/mongodb.json)。

## 0. 評估前提

- 資料形狀：物件 `id`(UUID)、`name`、`model_url`、`position/rotation/scale`(各 x/y/z)、`visible`、`created_at`、`updated_at`。
- 負載假設：單一場景 1 萬個物件、讀多寫少（約 9:1）、需要「名稱子字串搜尋 + 分頁」、「名稱唯一」、「座標批次更新」。
- 評分為 1–5 分的主觀 rubric，但**數據不得臆造**：只有 SQLite 能在本機實測，PostgreSQL 與 MongoDB 誠實標記 `measured: false`，以官方文件佐證機制。

## 1. 量測結果

| 方案 | 實測 | 10k 寫入 | 單筆讀 p50 | 分頁列表 p50 | 備註 |
| --- | --- | --- | --- | --- | --- |
| SQLite (WAL) | ✅ | 70.3 ms | 0.009 ms | 2.89 ms | Python 3.13.14 / SQLite 3.50.4，3 次重複；9 個 REAL 欄位版 |
| PostgreSQL | ❌ | — | — | — | 本機無服務；JSONB + GIN、MVCC、`UNIQUE` 由文件佐證 |
| MongoDB | ❌ | — | — | — | 本機無服務；文件模型、unique index、change streams 由文件佐證 |

SQLite 的兩個關鍵附帶量測：

- **唯一索引成本**：10k insert 由 52.3 ms → 70.3 ms（+34.3%），檔案 +740 KB；換來資料庫層保證名稱唯一。
- **併發探針**：寫入交易進行中，另一連線仍可 SELECT 1 萬筆（5.6 ms）；第二個寫入者在 257 ms 後收到 `database is locked` —— 單寫入者是硬限制，不是調參可解。

## 2. 評分與加權排序

**生產環境權重**（重視併發與資料庫層正確性）：

| 排名 | 方案 | XR 貼合 30% | 併發 25% | 維運 20% | 彈性 15% | 生態 10% | 加權總分 |
| --- | --- | --- | --- | --- | --- | --- | --- |
| 1 | PostgreSQL | 4 | 5 | 3 | 4 | 5 | **4.15** |
| 2 | MongoDB | 4 | 3 | 3 | 5 | 5 | **3.80** |
| 3 | SQLite | 4 | 2 | 5 | 3 | 4 | **3.55** |

**本作業階段權重**（單節點交付、零維運、可重現測試優先）：

| 排名 | 方案 | XR 貼合 25% | 併發 10% | 維運 35% | 彈性 15% | 生態 15% | 加權總分 |
| --- | --- | --- | --- | --- | --- | --- | --- |
| 1 | SQLite | 4 | 2 | 5 | 3 | 4 | **4.00** |
| 2 | PostgreSQL | 4 | 5 | 3 | 4 | 5 | **3.90** |
| 3 | MongoDB | 4 | 3 | 3 | 5 | 5 | **3.85** |

> 同一組分數，換一組權重就換一個冠軍——這正是比較表要附權重的原因。

## 3. 各方案重點

### SQLite（實測）

- **優點**：零外部服務、單檔備份；1 萬筆規模的單筆讀與分頁都在毫秒以下；WAL 支援一寫多讀；`UNIQUE(name)` 在資料庫層擋重複；9 個 REAL 欄位讓座標批次更新免讀-改-寫。
- **缺點**：只有單一寫入者（實測 `database is locked`）；`LIKE '%x%'` 無法走索引，資料量再大時排序與 OFFSET 成本線性惡化；無列級鎖、無 MVCC、無變更訂閱；多副本部署不可行。
- **判斷**：中小型、單節點、讀多寫少——甜蜜點。

### PostgreSQL（文件佐證，未實測）

- **優點**：MVCC 讓讀不擋寫；`UNIQUE(name)` 由唯一 B-tree 保證；JSONB 容納巢狀座標且可演進；`UPDATE ... FROM (VALUES ...)` 可一次更新整批座標。
- **缺點**：子字串搜尋需 `pg_trgm` + GIN，否則全表掃；服務、連線池、備份、autovacuum 都是額外維運；JSONB 沒有 schema 約束，驗證仍得靠 Pydantic/CHECK。
- **判斷**：多人同時編輯、需要交易一致性時的首選。

### MongoDB（文件佐證，未實測）

- **優點**：物件與文件 1:1，`position.x` 可單點更新；複合索引支援場景內分頁；change streams 可直接把座標變更推給 WebSocket 客戶端。
- **缺點**：非錨定 `$regex` 無法用一般索引，子字串搜尋要靠 Atlas Search（額外服務與費用）；沒有跨文件 SERIALIZABLE，併發編輯要自己做 version 樂觀鎖；change streams 與多文件交易都要求 replica set。
- **判斷**：欄位常演進、需要即時推送時的選擇，但要先接受搜尋與營運前提。

## 4. 決策：本階段用 SQLite，介面保留換庫空間

**選擇 SQLite**，理由按重要性排序：

1. **交付風險最低**：零外部服務，測試可完全重現；不需要在評分環境安裝資料庫。
2. **資料量與負載相符**：1 萬筆/場景的讀取與分頁實測都在毫秒級，遠低於互動延遲預算。
3. **正確性需求可由資料庫保證**：`UNIQUE(name)` 與交易足以支撐「名稱唯一 + 單筆寫入」的 CRUD。
4. **換庫成本被介面吸收**：規格把儲存藏在 `ObjectRepository` 介面後，API 層與測試不認識 SQL；未來要換 PostgreSQL 只改一個實作。

**本次交付的落地方式**：API 以同一介面的 `InMemoryObjectRepository` 驗證契約與測試（不把檔案 I/O 混進 API 行為），
`SqliteObjectRepository` 與其建表語句（9 個 REAL 欄位 + `UNIQUE(name)`）已在 `bench/sqlite/bench.py` 驗證過效能；
上線前把 `create_app()` 的 repository 換成 SQLite 實作即可，端點契約不變。

**什麼時候該換**：

| 觸發條件 | 換成 |
| --- | --- |
| 需要多個 API 實例／水平擴展 | PostgreSQL |
| 多人同時編輯同一場景、需要列級隔離與衝突重試 | PostgreSQL |
| 需要把變更即時推播給 WebXR 客戶端 | MongoDB（change streams） |
| 單節點、資料量 < 十萬、以讀為主 | 維持 SQLite |

## 5. 方法與限制

- **平行但獨立**：三個子代理各自只看一種方案，避免「先看到別人的結論」造成錨定；輸出格式事先約定，主 Agent 才能自動排序。
- **誠實標記**：只有 SQLite 有數字。PostgreSQL / MongoDB 的分數是架構特性推論，不是量測結果。
- **單機量測的偏差**：SQLite 數字來自本機 NTFS、暖機後的檔案，未含網路與容器 overhead；三個子代理同時執行也可能轻微影響時序，故取 3 次平均並記錄 p50/p95。
- **rubric 主觀性**：分數換一組權重就換排名，因此同時公布兩組權重；真正的選擇理由寫在第 4 節，而不是只看總分。
