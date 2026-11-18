import os
import sqlite3
import time

db = os.path.expanduser("~/.local/share/opencode/opencode.db")
con = sqlite3.connect(f"file:{db}?mode=ro", uri=True)
con.row_factory = sqlite3.Row

rows = con.execute("""
    select id, parent_id, title, agent, model,
           tokens_input, tokens_output, tokens_reasoning,
           tokens_cache_read, tokens_cache_write, cost,
           time_created, time_updated, time_busy, time_idle
    from session_v2
    order by time_created
""").fetchall()

fmt = lambda ms: time.strftime("%H:%M:%S", time.localtime(ms / 1000)) if ms else "-"
print(f"{'agent':<16} {'start':<9} {'end':<9} {'dur':>6} {'in':>8} {'out':>7} {'reason':>7} {'cache_r':>9} {'cache_w':>8} {'cost':>7}  title")
total_in = total_out = 0
for r in rows:
    dur = (r["time_updated"] - r["time_created"]) / 1000
    inp = r["tokens_input"] or 0
    out = r["tokens_output"] or 0
    total_in += inp
    total_out += out
    print(f"{(r['agent'] or '-'):<16} {fmt(r['time_created']):<9} {fmt(r['time_updated']):<9} "
          f"{dur:6.0f}s {inp:8d} {out:7d} {(r['tokens_reasoning'] or 0):7d} "
          f"{(r['tokens_cache_read'] or 0):9d} {(r['tokens_cache_write'] or 0):8d} "
          f"{(r['cost'] or 0):7.4f}  {r['title']}")
print(f"\ntotal input={total_in} output={total_out} sum={total_in + total_out}")

print("\nmessages:", con.execute("select count(*) from session_message").fetchone()[0])
for r in con.execute("""
    select session_id, type, count(*) n from session_message group by 1,2 order by 1,2
"""):
    print(dict(r))
