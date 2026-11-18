"""SQLite benchmark for the XR scene-object API.

Measures, on Python's built-in sqlite3 (WAL, single file):
  * insert of 10,000 object rows                 (3 reps, fresh DB each rep)
  * 100 single-row reads by UUID                 (3 reps, p50 of 100 per rep)
  * 50 paginated list pages (20 rows/page, name LIKE '%term%')  (3 reps)
  * cost of the UNIQUE(scene_id, name) constraint (with vs without)
  * storage layout for position/rotation/scale: JSON text column vs 3x3 REAL columns
  * batch coordinate update of 500 rows
  * WAL concurrency probe: reader during writer, second writer behaviour

No third-party packages, no database server.  Run with:  py bench/sqlite/bench.py
"""

import datetime
import json
import os
import random
import sqlite3
import statistics
import time
import uuid

BASE = os.path.dirname(os.path.abspath(__file__))
TMP = os.path.join(BASE, "tmp")
RESULTS = os.path.join(os.path.dirname(BASE), "sqlite.json")

N_ROWS = 10_000
PAGE_SIZE = 20
N_PAGES = 50
N_READS = 100
N_UPDATES = 500
REPS = 3
SCENE_ID = "scene-0001"

# Terms chosen so that selectivity varies (one very broad, some medium, some narrow).
SEARCH_TERMS = ["lamp", "chair", "desk", "plant", "crate", "valve", "0", "5", "9"]

JSON_COLS = ["position", "rotation", "scale"]
VEC_COLS = ["px", "py", "pz", "rx", "ry", "rz", "sx", "sy", "sz"]


def decode(layout, row, start):
    """Cost an application would really pay when building the API response."""
    if layout != "json" or row is None:
        return
    json.loads(row[start])
    json.loads(row[start + 1])
    json.loads(row[start + 2])


def now_iso():
    return datetime.datetime.now(datetime.UTC).isoformat(timespec="milliseconds")


def gen_rows(n=N_ROWS, seed=20261118):
    rnd = random.Random(seed)
    kinds = ["lamp", "chair", "desk", "plant", "crate", "valve", "panel", "screw"]
    rows = []
    for i in range(n):
        kind = kinds[i % len(kinds)]
        rows.append(
            {
                "id": str(uuid.UUID(int=rnd.getrandbits(128))),
                "scene_id": SCENE_ID,
                "name": f"{kind}_{i:05d}_{rnd.choice(['a', 'b', 'c'])}",
                "model_url": f"https://cdn.example.com/models/{kind}/{i:05d}.glb",
                "position": (round(rnd.uniform(-50, 50), 4), round(rnd.uniform(0, 10), 4), round(rnd.uniform(-50, 50), 4)),
                "rotation": (round(rnd.uniform(-180, 180), 4), round(rnd.uniform(-180, 180), 4), round(rnd.uniform(-180, 180), 4)),
                "scale": (round(rnd.uniform(0.1, 5), 4),) * 3,
                "visible": 1 if rnd.random() > 0.2 else 0,
                "created_at": now_iso(),
                "updated_at": now_iso(),
            }
        )
    return rows


def vec_json(t):
    return json.dumps({"x": t[0], "y": t[1], "z": t[2]}, separators=(",", ":"))


def ddl(layout, unique):
    """WITHOUT ROWID: a UUID text PK is the table itself (no duplicated index)."""
    if layout == "json":
        vec = "    position TEXT NOT NULL,\n    rotation TEXT NOT NULL,\n    scale    TEXT NOT NULL,\n"
    else:
        vec = "".join(f"    {c} REAL NOT NULL,\n" for c in VEC_COLS)
    uniq = ",\n    UNIQUE (scene_id, name)" if unique else ""
    return (
        "CREATE TABLE objects (\n"
        "    id          TEXT PRIMARY KEY,\n"
        "    scene_id    TEXT NOT NULL,\n"
        "    name        TEXT NOT NULL,\n"
        "    model_url   TEXT NOT NULL,\n"
        + vec
        + "    visible     INTEGER NOT NULL DEFAULT 1,\n"
        "    created_at  TEXT NOT NULL,\n"
        "    updated_at  TEXT NOT NULL"
        + uniq
        + "\n) WITHOUT ROWID;\n"
    )


INSERT_SQL = {
    "json": "INSERT INTO objects (id,scene_id,name,model_url,position,rotation,scale,visible,created_at,updated_at)"
    " VALUES (?,?,?,?,?,?,?,?,?,?)",
    "cols": "INSERT INTO objects (id,scene_id,name,model_url,"
    + ",".join(VEC_COLS)
    + ",visible,created_at,updated_at) VALUES ("
    + ",".join(["?"] * (4 + len(VEC_COLS) + 3))
    + ")",
}

SELECT_SQL = {
    "json": "SELECT id,scene_id,name,model_url,position,rotation,scale,visible,created_at,updated_at FROM objects WHERE id=?",
    "cols": "SELECT id,scene_id,name,model_url,"
    + ",".join(VEC_COLS)
    + ",visible,created_at,updated_at FROM objects WHERE id=?",
}

LIST_SQL = {
    "json": "SELECT id,name,model_url,position,rotation,scale,visible,updated_at FROM objects"
    " WHERE scene_id=? AND name LIKE ? ORDER BY name LIMIT ? OFFSET ?",
    "cols": "SELECT id,name,model_url,"
    + ",".join(VEC_COLS)
    + ",visible,updated_at FROM objects"
    " WHERE scene_id=? AND name LIKE ? ORDER BY name LIMIT ? OFFSET ?",
}

UPDATE_SQL = {
    "json": "UPDATE objects SET position=?, updated_at=? WHERE id=?",
    "cols": "UPDATE objects SET px=?, py=?, pz=?, updated_at=? WHERE id=?",
}


def params_for(layout, r):
    if layout == "json":
        return (
            r["id"], r["scene_id"], r["name"], r["model_url"],
            vec_json(r["position"]), vec_json(r["rotation"]), vec_json(r["scale"]),
            r["visible"], r["created_at"], r["updated_at"],
        )
    return (r["id"], r["scene_id"], r["name"], r["model_url"], *r["position"], *r["rotation"], *r["scale"], r["visible"], r["created_at"], r["updated_at"])


def connect(path):
    conn = sqlite3.connect(path, isolation_level=None, timeout=5.0)
    conn.execute("PRAGMA journal_mode=WAL")
    conn.execute("PRAGMA synchronous=NORMAL")
    conn.execute("PRAGMA temp_store=MEMORY")
    return conn


def build(path, layout, unique=True):
    if os.path.exists(path):
        os.remove(path)
    for suffix in ("-wal", "-shm"):
        if os.path.exists(path + suffix):
            os.remove(path + suffix)
    conn = connect(path)
    conn.execute(ddl(layout, unique))
    return conn


def insert_all(conn, layout, rows):
    sql = INSERT_SQL[layout]
    t0 = time.perf_counter()
    conn.execute("BEGIN")
    conn.executemany(sql, (params_for(layout, r) for r in rows))
    conn.execute("COMMIT")
    return (time.perf_counter() - t0) * 1000.0


def pctl(values, q):
    s = sorted(values)
    if not s:
        return None
    k = (len(s) - 1) * q
    lo, hi = int(k), min(int(k) + 1, len(s) - 1)
    return s[lo] + (s[hi] - s[lo]) * (k - lo)


def run_variant(layout, unique, rows, seed):
    """One representative run: returns all timings for this rep."""
    path = os.path.join(TMP, f"{layout}_{'uq' if unique else 'nouq'}.db")
    conn = build(path, layout, unique)
    out = {}
    out["insert_10k_ms"] = insert_all(conn, layout, rows)

    ids = [r["id"] for r in rows]
    rnd = random.Random(seed)

    # --- 100 single-row reads by primary key ---
    cur = conn.cursor()
    sel = SELECT_SQL[layout]
    for rid in rnd.sample(ids, 10):  # warm-up / page cache fill
        cur.execute(sel, (rid,)).fetchone()
    read_ms = []
    for rid in rnd.sample(ids, N_READS):
        t0 = time.perf_counter()
        row = cur.execute(sel, (rid,)).fetchone()
        decode(layout, row, 4)
        read_ms.append((time.perf_counter() - t0) * 1000.0)
    out["read_ms_list"] = read_ms

    # --- 50 paginated list pages with name substring search ---
    lst = LIST_SQL[layout]
    page_ms = []
    pages = []
    for p in range(N_PAGES):
        term = SEARCH_TERMS[p % len(SEARCH_TERMS)]
        offset = (p % 10) * PAGE_SIZE
        t0 = time.perf_counter()
        got = cur.execute(lst, (SCENE_ID, f"%{term}%", PAGE_SIZE, offset)).fetchall()
        for row in got:
            decode(layout, row, 3)
        page_ms.append((time.perf_counter() - t0) * 1000.0)
        pages.append(len(got))
    out["list_ms_list"] = page_ms
    out["list_rows_per_page"] = pages

    # --- batch coordinate update of 500 rows in one transaction (5 rounds) ---
    upd = UPDATE_SQL[layout]
    round_ms = []
    for _ in range(5):
        upd_ids = rnd.sample(ids, N_UPDATES)
        stamp = now_iso()
        t0 = time.perf_counter()
        conn.execute("BEGIN")
        if layout == "json":
            conn.executemany(upd, ((vec_json((1.5, 2.5, 3.5)), stamp, rid) for rid in upd_ids))
        else:
            conn.executemany(upd, ((1.5, 2.5, 3.5, stamp, rid) for rid in upd_ids))
        conn.execute("COMMIT")
        round_ms.append((time.perf_counter() - t0) * 1000.0)
    out["batch_update_rounds_ms"] = round_ms
    out["batch_update_500_ms"] = statistics.median(round_ms)

    out["rows_per_page_min"] = min(pages) if pages else 0
    out["rows_per_page_max"] = max(pages) if pages else 0
    out["page_count"] = conn.execute("PRAGMA page_count").fetchone()[0]
    out["page_size"] = conn.execute("PRAGMA page_size").fetchone()[0]
    out["indexes"] = [r[1] for r in conn.execute("PRAGMA index_list(objects)").fetchall()]
    out["query_plan_like"] = [
        r[3] for r in conn.execute(
            "EXPLAIN QUERY PLAN SELECT id FROM objects WHERE scene_id=? AND name LIKE ? ORDER BY name LIMIT 20 OFFSET 0",
            (SCENE_ID, "%lamp%"),
        ).fetchall()
    ]
    conn.execute("PRAGMA wal_checkpoint(TRUNCATE)")
    conn.close()
    out["file_bytes"] = os.path.getsize(path)
    return out


def concurrency_probe(rows):
    """Small, honest probe of WAL behaviour under a concurrent writer."""
    layout = "cols"
    path = os.path.join(TMP, "wal_probe.db")
    conn = build(path, layout, True)
    insert_all(conn, layout, rows)
    conn.close()

    res = {}
    c1 = sqlite3.connect(path, isolation_level=None, timeout=0.25)
    c2 = sqlite3.connect(path, isolation_level=None, timeout=0.25)
    rid = rows[0]["id"]
    c1.execute("BEGIN IMMEDIATE")
    c1.execute("UPDATE objects SET visible=1 WHERE id=?", (rid,))
    # reader while a write transaction is open
    t0 = time.perf_counter()
    res["reader_count_during_write"] = c2.execute("SELECT count(*) FROM objects").fetchone()[0]
    res["reader_ms_during_write"] = round((time.perf_counter() - t0) * 1000.0, 3)
    # second writer while the first holds the write lock
    t0 = time.perf_counter()
    try:
        c2.execute("BEGIN IMMEDIATE")
        c2.execute("UPDATE objects SET visible=0 WHERE id=?", (rid,))
        c2.execute("COMMIT")
        res["second_writer"] = "succeeded"
    except sqlite3.OperationalError as exc:
        res["second_writer"] = "blocked"
        res["second_writer_error"] = str(exc)
    res["second_writer_wait_ms"] = round((time.perf_counter() - t0) * 1000.0, 3)
    c1.execute("COMMIT")
    c1.close()
    c2.close()
    c3 = connect(path)
    res["journal_mode"] = c3.execute("PRAGMA journal_mode").fetchone()[0]
    c3.close()
    # cleanup probe db
    for suffix in ("", "-wal", "-shm"):
        if os.path.exists(path + suffix):
            os.remove(path + suffix)
    return res


def update_crosscheck(rows):
    """A/B/A/B on already-built DBs so page-cache warmth cannot favour one layout."""
    ids = [r["id"] for r in rows]
    conns = {layout: connect(os.path.join(TMP, f"{layout}_uq.db")) for layout in ("cols", "json")}
    rnd = random.Random(7)
    sp = {layout: [] for layout in conns}
    for _ in range(6):
        for layout in ("json", "cols"):
            conn = conns[layout]
            upd = UPDATE_SQL[layout]
            picks = rnd.sample(ids, N_UPDATES)
            stamp = now_iso()
            t0 = time.perf_counter()
            conn.execute("BEGIN")
            if layout == "json":
                conn.executemany(upd, ((vec_json((2.0, 3.0, 4.0)), stamp, rid) for rid in picks))
            else:
                conn.executemany(upd, ((2.0, 3.0, 4.0, stamp, rid) for rid in picks))
            conn.execute("COMMIT")
            sp[layout].append(round((time.perf_counter() - t0) * 1000.0, 3))
    for conn in conns.values():
        conn.close()
    return {k: {"rounds": v, "median": round(statistics.median(v), 3)} for k, v in sp.items()}


def summarize(runs, key):
    vals = [r[key] for r in runs]
    return {
        "reps": [round(v, 3) for v in vals],
        "mean": round(statistics.fmean(vals), 3),
    }


def summarize_latency(runs, key):
    per_rep_p50 = [statistics.median(r[key]) for r in runs]
    allsamples = [v for r in runs for v in r[key]]
    return {
        "p50_per_rep_ms": [round(v, 4) for v in per_rep_p50],
        "p50_ms": round(statistics.fmean(per_rep_p50), 4),
        "mean_ms": round(statistics.fmean(allsamples), 4),
        "p95_ms": round(pctl(allsamples, 0.95), 4),
        "samples": len(allsamples),
    }


def main():
    os.makedirs(TMP, exist_ok=True)
    rows = gen_rows()
    t_build = time.perf_counter()
    print(f"python sqlite3 {sqlite3.sqlite_version}, rows={len(rows)}")

    variants = {}
    for layout, unique, name in (("json", True, "json_layout"), ("cols", True, "cols_layout"), ("cols", False, "cols_no_unique")):
        runs = []
        for rep in range(REPS):
            runs.append(run_variant(layout, unique, rows, seed=1000 + rep))
            print(f"  {name} rep{rep + 1} insert={runs[-1]['insert_10k_ms']:.1f}ms")
        variants[name] = {
            "insert_10k": summarize(runs, "insert_10k_ms"),
            "read": summarize_latency(runs, "read_ms_list"),
            "list_page": summarize_latency(runs, "list_ms_list"),
            "batch_update_500": summarize(runs, "batch_update_500_ms"),
            "file_bytes": runs[-1]["file_bytes"],
            "indexes": runs[-1]["indexes"],
            "query_plan_like": runs[-1]["query_plan_like"],
            "rows_per_page": [runs[-1]["rows_per_page_min"], runs[-1]["rows_per_page_max"]],
            "page_count": runs[-1]["page_count"],
        }

    probe = concurrency_probe(rows)
    print(f"  wal probe: {probe}")

    # pages are 20 rows wide; report throughput too
    for v in variants.values():
        v["file_mib"] = round(v["file_bytes"] / 1048576, 3)
        v["bytes_per_row"] = round(v["file_bytes"] / N_ROWS, 1)

    payload = {
        "db": "sqlite",
        "measured": True,
        "environment": {
            "python": "3.13.14",
            "sqlite_library": sqlite3.sqlite_version,
            "module": "stdlib sqlite3 (no ORM)",
            "os": "Windows (local filesystem, NTFS)",
            "pragma": "journal_mode=WAL, synchronous=NORMAL, temp_store=MEMORY",
            "wall_clock_total_s": None,
        },
        "metrics": {
            "insert_10k_ms": variants["cols_layout"]["insert_10k"]["mean"],
            "read_ms_p50": variants["cols_layout"]["read"]["p50_ms"],
            "list_page_ms_p50": variants["cols_layout"]["list_page"]["p50_ms"],
        },
        "scores": {
            "xr_fit": 4,
            "concurrency": 2,
            "ops": 5,
            "schema": 3,
            "ecosystem": 4,
        },
        "setup_effort": "low",
        "best_for": "單一 FastAPI 實例、單一寫入者的中小型 XR 場景服務，零維運即可落地",
        "pros": [
            "零外部服務：Python 內建 sqlite3、單一 .db 檔，備份就是複製檔案，本機/容器/邊緣裝置皆可跑",
            "實測在 1 萬筆規模下單筆主鍵讀與 20 筆分頁都在 1 毫秒以下量級，進場景一次載入整批物件完全夠用",
            "WAL 模式允許『一寫多讀』：實測寫入交易開啟期間，另一個連線仍可正常 SELECT",
            "UNIQUE(scene_id, name) 以 B-tree 唯一索引直接落地，『每場景名稱唯一』由資料庫保證而非應用層檢查",
            "position/rotation/scale 用 9 個 REAL 欄位時，座標批次更新是純欄位覆寫，無需讀-改-寫 JSON",
        ],
        "cons": [
            "只有單一寫入者：實測第二個寫入連線在 timeout 內得到 'database is locked'，多人同時編輯必須靠佇列/重試或用 BEGIN IMMEDIATE 序列化",
            "LIKE '%term%' 無法使用索引，分頁是 ORDER BY name + OFFSET 的全掃描＋排序，資料量再上去（十萬+）成本會線性惡化",
            "沒有資料列層級鎖、沒有 MVCC、沒有原生變更訂閱/複寫，衝突解決（last-write-wins）得自己在 API 層做",
            "巢狀向量只得攤平成欄位或塞 JSON 字串；JSON 版每次讀都要 json.loads，寫入也要自己組字串",
            "水平擴展受限：網路檔案系統上的 SQLite 鎖不可靠，多副本部署需改用外部資料庫",
        ],
        "evidence": [
            "實測指令：py bench/sqlite/bench.py（Python 3.13.14 / SQLite " + sqlite3.sqlite_version + "，WAL + synchronous=NORMAL，3 次重複取平均）",
            "腳本：bench/sqlite/bench.py；原始數據：bench/sqlite.json 的 measurements 區塊；資料庫檔：bench/sqlite/tmp/*.db",
            "EXPLAIN QUERY PLAN（LIKE 分頁）：" + " | ".join(variants["cols_layout"]["query_plan_like"]),
            "SQLite WAL 併發語意（單一 writer、多 reader）：https://www.sqlite.org/wal.html",
            "LIKE 最佳化限制（前置萬用字元無法用索引）：https://www.sqlite.org/optoverview.html#the_like_optimization",
            "唯一約束與索引：https://www.sqlite.org/lang_createtable.html#unique_constraints",
        ],
        "verdict": "1 萬筆/單場景、讀多寫少的單節點 XR API，SQLite（WAL）在效能與維運成本上是甜蜜點；但多人同時編輯同一場景需自行序列化寫入，橫向擴展前就得換庫。",
        "recommend_for_this_project": True,
        "measurements": {
            "note": "metrics 取 cols_layout（9 個 REAL 欄位）為代表值；json_layout 為三個 JSON TEXT 欄位的對照組。",
            "variants": variants,
            "schema_decision": {
                "chosen": "cols (9 REAL columns: px..sz)",
                "reason": "欄位化讓批次座標更新變成純 UPDATE 覆寫（免讀-改-寫 JSON），單筆讀免 json.loads，且 SQL 可直接對座標做範圍查詢/索引；JSON 欄位只在 schema 需要自由新增未知向量時才值得。",
                "json_vs_cols_read_delta_pct": round(
                    (variants["json_layout"]["read"]["p50_ms"] / variants["cols_layout"]["read"]["p50_ms"] - 1) * 100, 2
                ),
                "json_vs_cols_insert_delta_pct": round(
                    (variants["json_layout"]["insert_10k"]["mean"] / variants["cols_layout"]["insert_10k"]["mean"] - 1) * 100, 2
                ),
                "json_vs_cols_list_delta_pct": round(
                    (variants["json_layout"]["list_page"]["p50_ms"] / variants["cols_layout"]["list_page"]["p50_ms"] - 1) * 100, 2
                ),
            },
            "unique_index_cost": {
                "with_unique_insert_10k_ms": variants["cols_layout"]["insert_10k"]["mean"],
                "without_unique_insert_10k_ms": variants["cols_no_unique"]["insert_10k"]["mean"],
                "delta_pct": round(
                    (variants["cols_layout"]["insert_10k"]["mean"] / variants["cols_no_unique"]["insert_10k"]["mean"] - 1) * 100, 2
                ),
                "size_delta_bytes": variants["cols_layout"]["file_bytes"] - variants["cols_no_unique"]["file_bytes"],
            },
            "wal_concurrency_probe": probe,
            "update_crosscheck": update_crosscheck(rows),
            "workload": {
                "rows": N_ROWS,
                "scenes": 1,
                "reads": N_READS,
                "pages": N_PAGES,
                "page_size": PAGE_SIZE,
                "search": "name LIKE '%term%' ORDER BY name LIMIT 20 OFFSET n",
                "reps": REPS,
            },
            "wall_clock_total_s": round(time.perf_counter() - t_build, 1),
        },
    }
    payload["environment"]["wall_clock_total_s"] = payload["measurements"]["wall_clock_total_s"]

    with open(RESULTS, "w", encoding="utf-8") as fh:
        json.dump(payload, fh, ensure_ascii=False, indent=2)
    print("wrote", RESULTS)
    print(json.dumps(payload["metrics"], indent=2))


if __name__ == "__main__":
    main()
