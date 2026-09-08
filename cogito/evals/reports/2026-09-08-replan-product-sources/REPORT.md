# RP 核准產品來源修補

交付版本：`4.4.1`。移植後端專案提交 `b70a3d3` 的產品來源分類修補，並補強無法由 Git 快照保存的來源保護。此次為 Cogito repository maintenance，未修改後端專案或其正式 run。

## 問題與結果

舊 `_runtime()` 對所有 source registry 文件核對規劃時 hash，導致已核准修改的產品文件在 RP stop 時被誤判為漂移。現在從有效 Package（包含合法 Amendments）取得 `approved_paths`：產品來源可保存核准實作後的內容；Spec／Plan、Shared Understanding 與未核准修改的來源仍核對原 hash，契約身分優先。

產品來源仍列入 protected paths。略過舊 hash 前，另比對目前檔案的 Git blob 與 executable mode，確認 content tree 確實保存它。Git-ignored untracked、從 index 移除而被忽略、skip-worktree 隱藏內容或 mode 變化均拒絕；不自動 stage、不更動使用者 index。已核准刪除以檔案與樹均缺席表示，停止後重新出現的未追蹤忽略檔案也會拒絕。

停止後沿用現有 index／content tree 比對；原 Package、事件與 evidence 不改寫。未新增事件 schema、流程狀態、核准步驟或快照格式，也未恢復退役 RP 格式。

## 自動化驗證

- 修補前：移植的 8 個分類案例有 5 個因產品來源 hash 漂移失敗，重現原問題；修補後原 8 個通過。
- 測試移植改用 `GitTestCase`／`init_repo()`，隔離個人 Git 設定、hooks 與簽章。分類 fixture 仍以 mock 提供 source run projection；實際 Package／Amendment 驗證、Git、RP 事件、快照與比對不 mock。
- 另新增完整 source 事件案例：兩個 Atomic Tasks 實作、checks、獨立 Reviewer 合成結果、整合，再進 RP begin／stop／重送；保存核准產品現值及原 Package／evidence，拒絕停止後只改 index 的內容漂移。此為隔離產品案例，不是後端 FS-041 的驗收。
- 相關範圍共 33 個不同測試最終通過：`test_replan_runtime_sources`、`test_replan_runtime_snapshot`、`test_replan_runtime_human_e2e`、`test_atomic_replan`、`test_replan_handoff_tool_repair`。最初組合 29 tests 有 1 個新增案例的錯誤文字斷言不符，已修正；補強後組合 32 tests 有 1 個 handoff 案例因測試期間修改工具而偵測到 hash 漂移。在程式固定後重跑該案例與最終來源測試，共 14 tests 通過，包含最後新增的 mode 案例；重跑數不重複累加。
- mypy 1.20.2：`cogito/mypy.ini` 指定的 27 source files 通過；這不是對所有 RP 模組的完整型別檢查。使用既有離線 uv 環境，未新增 runtime dependency。
- `git diff --check` 通過。未執行全套 regression，未執行或宣稱 CI 通過；選測涵蓋來源分類、目前與歷史快照保護、事件重播、人工驗收交接與工具中斷恢復。

## 獨立審查與文件模擬

獨立子 Agent 發現並實際重現兩項移植原碼缺口：ignored/untracked 產品未進快照、skip-worktree 可隱藏 executable mode 變化。主 Agent 修正並新增回歸；子 Agent 分別重跑分類與 mode 聚焦案例，最終兩項均消除，沒有剩餘必要修正。

子 Agent 另以核准產品修改、契約文件變更、停止後漂移三個情境試讀更新的 `replan-snapshots.md`。分類與拒絕規則清楚；這是合成 Agent 決策／靜態閱讀模擬，不是實際 Gate 執行或使用者核准。實際 Git／Gate 測試另列於上節。

未修改 SKILL frontmatter 或 agent metadata，未重跑 Skill 格式驗證。
