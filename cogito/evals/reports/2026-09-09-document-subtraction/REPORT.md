# 文件減法整理與閱讀檢查

本次依使用者確認的四批方案，重組操作文件並減少維護副本。基準 commit 為 `18c34d425ccc5788c5886285e42362bdd8fedafd`，版本維持 `4.4.3`；沒有修改 Python runtime、workflow、契約、Agent metadata 或測試。閱讀範圍調整用於揭露既有前提與按需查閱，不變更操作授權、執行順序或相容性政策，因此按文件維護政策不升版。

## 完成範圍

| 批次 | 修改與規則落點 | 檢查結果 |
|---|---|---|
| 1 | Bootstrap 保留採納原則，準備／提交回到主流程；README 改為簡介及入口，獨有內部相容性資料移至 Runtime Internals | 既有專案準備與維護入口兩個合成閱讀情境通過。校正 README 引用不存在的 `evals/evals.json`；獨立檢查未發現規則遺失 |
| 2 | executor 登錄時機移到正常派工；RP 保留實際停止、憑據及保存 | 外部 Worker 首次派工與 API 變更停止兩個情境通過；核對 register-executor CLI flags |
| 3 | Amendment 共通邊界前置；兩種 path amendment 入口共用覆核／撤回／重送，保留各自 Task 與 finding 差異 | executing 漏檔、首次 review-fix 漏檔、未完成修正 Task 再漏檔且封存失敗三個情境通過；核對相關 CLI flags |
| 4 | Runtime 集中共通介面，checks 與 inventory 詳細操作回到主責文件；SKILL 按流程小節及前提閱讀，人工修正使用精確引用 | 四組合成情境檢查發現一個專用 receipt 連結落點缺口，主代理修正後獨立聚焦複核通過 |

Runtime 不再另列一份 SKILL 流程路由表。正常派工不需先讀 RP 才知道 executor 登錄時機；review-fix 的路徑覆核不再引用一個開頭限定 executing 的整節。保留人工修正的 Maintenance review、每輪驗證、提交方式與結案授權例外；Spec／Plan templates、stage commits、finalization、DP 及 RP snapshots／toolchain 未改動。

## 獨立閱讀評估

每批使用無父任務歷史的新子代理，僅給合成情境、目前 SKILL 與 repo 路徑。先記錄閱讀順序及決策，再核對指定 diff；不提供預期答案、不讀歷史報告作答案。主代理核對回報並實作修正，子代理不修改文件。

第四批情境及實際判讀：

- Task-finish 成功後依 next 選操作；run-check 的 ok／CLI 0 不代替 check_status，failed evidence 不可宣告完成。
- 啟動前拒絕以原 ID／輸入重送；started 無完整 evidence 維持未知結果；正式 check-preparation-failed 依 Gate 提示綁新 replacement，保留 transient 額度與原 marker。
- Maintenance 人工退回且未驗完：依修改目的及契約分類；local 時保持 Start Gate HEAD，以未提交快照完成，執行本輪全部適用 post-integration checks 與獨立 review，再回 awaiting-human。
- Accepted cleanup 重試保留原 finalize 參數及 action ID；accepted Slice inventory 只提供歷史事實，不能代替新 Package 的適用性分析，也不能 resume accepted run 開發。

發現與修正：成功的 task-finish／帶 Amendment review-fix receipt 細節曾只留在維護者文件，正常連結卻指向失敗恢復段。已在 Runtime 的正常結果判讀段保留專用 receipt 欄位與 finding-only 一般 receipt；恢復連結明確限定部分失敗。原評估者只針對此 finding 複讀最新版，確認已解決，沒有重算為新的完整情境測試。

以上是 11 個合成閱讀情境／情境組與 diff 保留檢查，不是真實 Gate 執行、controlled evidence、使用者驗收或 Agent 準確率基準。代理數與 ID 不構成本產品的正式 Gate review evidence。

## 文件與介面檢查

- 19 份 active Markdown（SKILL、README、17 份 references）的 122 個相對連結及標題 anchors 已由臨時檢查程式核對；不包含歷史報告的所有連結。程式排除 fenced examples，再比對本地路徑及中文／英文標題 slug。
- `git diff --check` 通過。
- 下列公開 subcommand 的 `--help` 均成功，與本次文件使用的參數相符：`replan register-executor`、`amend-paths`、`review-fix-start`、`slice-inventory`、`retry`、`transition`。這些只查 CLI 介面，沒有建立 run 或提交 Gate action。
- Skill format：`quick_validate.py cogito` 通過。最初系統 Python 缺少 PyYAML，改用既有暫存依賴後成功，沒有安裝或修改專案依賴。

格式驗證實際命令：

```sh
PYTHONPATH=/private/tmp/cogito-readability-20260906/validator-deps python3 /Users/pablo/.codex/skills/.system/skill-creator/scripts/quick_validate.py cogito
```

執行環境為本地 macOS，Python `3.12.10`。本次沒有執行 unittest、完整 regression、mypy、CI 或 Gate 端到端模擬：變更限定文件重組，使用路徑／介面／diff 與閱讀評估檢查；沒有以歷史測試通過宣稱目前版本已驗證。

## 文字量觀察

以下以 UTF-8 解碼後的 Python `len(text)` 計數，包含 Markdown 與換行，不是 tokens。

| 文件 | 修改前字元 | 修改後字元 | 差額 |
|---|---:|---:|---:|
| `SKILL.md` | 4,920 | 4,989 | +69 |
| `README.md` | 6,901 | 1,450 | -5,451 |
| `references/execution-policy.md` | 21,503 | 22,817 | +1,314 |
| `references/human-acceptance.md` | 7,099 | 7,172 | +73 |
| `references/package-authoring.md` | 6,361 | 7,086 | +725 |
| `references/project-bootstrap.md` | 809 | 809 | +0 |
| `references/replanning.md` | 8,342 | 8,236 | -106 |
| `references/runtime-interface.md` | 10,796 | 6,569 | -4,227 |
| `references/runtime-internals.md` | 1,712 | 5,106 | +3,394 |
| 19 份 active Markdown 合計 | 103,783 | 99,574 | -4,209 |

Runtime 首次必讀範圍為開頭至「停止條件與狀態操作」末尾，共 5,009 字元；後續固定操作恢復及其他查詢按需閱讀。Execution Policy、Package Authoring 與 Runtime Internals 接回相關細節，因此個別文件增加；沒有新增操作文件。這些數字不證明 token、耗時或錯誤率下降。

## 最終文件綁定

下表為本次修改文件的 SHA-256；報告自身不納入。未變更文件以基準 commit 對照。

| 文件 | SHA-256 |
|---|---|
| `SKILL.md` | `10b6f6e13199c99867684da18ca4551882d07b66b4c526874e53783bf3095c04` |
| `README.md` | `cb88d26066f2b624b1b9cc5745dcc0bd6d6e4d9f2f32397f9c9fc3f7d5fddaa0` |
| `references/execution-policy.md` | `b63d4151c1ffad9a4c07084abcbef50b2d13cde1e00fba81959190e6886b00c7` |
| `references/human-acceptance.md` | `af6e77dba04d3c60c8d96da04833ccaf726f0a9c16b44cf34a6829bad7c26aed` |
| `references/package-authoring.md` | `b8a1db423dde299d2fba8a7c646bedf60cb5bd856912120b85dfa4e7bf22c258` |
| `references/project-bootstrap.md` | `1ce1bc682a7a7f869d5b9f718bbd2bea8a2b9ded67302edef15470053eda8cad` |
| `references/replanning.md` | `21cba1e254d8c850f31a2c0c2f7d6b27c016c871336050134875f851757fc7f6` |
| `references/runtime-interface.md` | `e97c39e5d119bcf1a0ea72d18fa3e91805b0f513340ddd817e153b3f8cdd03cc` |
| `references/runtime-internals.md` | `8a263329e5929d743c25796c9ecbc5127756e652260b6abd8484fd344cc9f48a` |
