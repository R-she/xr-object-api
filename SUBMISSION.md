# 繳交清單與操作說明

## 1. 繳交內容對照

| 要求 | 位置 | 狀態 |
| --- | --- | --- |
| `.opencode/agents/`（≥4 個專案子代理） | `.opencode/agents/team/`：architect、coder、tester、reviewer（另加 db-bench、security） | ✅ |
| 權限設計表與理由 | [`docs/permissions.md`](docs/permissions.md) | ✅ |
| `docs/spec.md` | [`docs/spec.md`](docs/spec.md) | ✅ |
| `docs/compare.md`（Part B） | [`docs/compare.md`](docs/compare.md) | ✅ |
| `tests/`（≥10 個測試全綠） | [`tests/`](tests/)：57 個測試函式 / 96 個案例，`96 passed` | ✅ |
| 反思報告（1–2 頁） | [`docs/reflection.md`](docs/reflection.md) | ✅ |
| 加分題：security 子代理 | [`docs/security-report.md`](docs/security-report.md)（OWASP Top 10） | ✅ |
| 執行過程截圖 | 需你在 OpenCode Desktop 自行截圖，清單見第 3 節 | ⬜ 待截圖 |
| GitHub repo 連結 | <https://github.com/R-she/xr-object-api>（4 個 commit 已推送） | ✅ |

## 2. 推送到 GitHub

Git 已安裝（`C:\Program Files\Git\cmd\git.exe`），本專案已完成 `git init` 與第一個 commit。
剩下的只有「建立遠端 repo 並 push」——這步需要你的 GitHub 帳號授權，我無法代做：

```powershell
# 1) 用瀏覽器開 https://github.com/new 建立空 repo（不要勾選 README/.gitignore）
#    名稱例如 xr-object-api

# 2) 回到這個資料夾（請開「新的」終端機，讓 git 進入 PATH）
git remote add origin https://github.com/<你的帳號>/xr-object-api.git
git push -u origin main
```

若想用 CLI 建立：`winget install --id GitHub.cli -e`，再 `gh auth login`、`gh repo create xr-object-api --public --source . --push`。

`*.db`、`bench/sqlite/tmp/`、`__pycache__` 已在 `.gitignore` 內，不會推上去。

## 3. 執行過程截圖清單

建議截這 4 張（皆為同一專案工作階段）：

1. **主 Agent 派工畫面**：本對話中「建立 team/architect…」與「同時啟動 3 個 db-bench」的訊息。
2. **子代理子 session #1**：`team/db-bench`（SQLite）—— 顯示它跑 `py bench/sqlite/bench.py` 與回報 JSON。
   - session：`ses_e11378c69ffeQSJMPC0bSQkBLe`
3. **子代理子 session #2**：`team/architect` 或 `team/tester` —— 顯示角色限定寫入範圍。
   - architect：`ses_e1149d82effe1cekqzCqoJFQ79`（可看到權限被拒的過程）
   - tester：`ses_e112bb71fffeo7Z5UEEPkA6Eo8`（可看到 96 passed）
4. **測試全綠畫面**：終端機執行 `py -m pytest -q` 的輸出。

> 子 session 可從左側工作階段列表依標題（例如「評估 SQLite 方案」）找到，或從主 Agent 的 subagent 訊息點開。

## 4. 一句話總結（給口試用）

> 三個 db-bench 子代理平行 59–145 秒完成三份評估，總輸出約 1.8 萬 token；
> 同一件事若序列執行約需 3 倍時間，且三份評估會塞進同一個 context。
> 真正的瓶頸不是並行，而是**角色交接**：architect 產不出檔案時，整條生產線會停擺。
