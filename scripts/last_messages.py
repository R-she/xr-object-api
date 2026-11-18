import json
import os
import sqlite3
import sys

sid = sys.argv[1]
db = os.path.expanduser("~/.local/share/opencode/opencode.db")
con = sqlite3.connect(f"file:{db}?mode=ro", uri=True)
rows = con.execute(
    "select type, seq, data from session_message where session_id=? order by seq", (sid,)
).fetchall()


def texts(data):
    out = []
    stack = [data]
    while stack:
        cur = stack.pop(0)
        if isinstance(cur, dict):
            if cur.get("type") == "text" and isinstance(cur.get("text"), str):
                out.append(cur["text"])
            stack.extend(v for v in cur.values() if isinstance(v, (dict, list)))
        elif isinstance(cur, list):
            stack.extend(cur)
    return out


for typ, seq, raw in rows[-4:]:
    data = json.loads(raw)
    print(f"--- {typ} seq={seq} ---")
    body = texts(data)
    print("\n".join(body)[:2500] if body else json.dumps(data, ensure_ascii=False)[:1200])
