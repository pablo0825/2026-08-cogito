# Cogito 全流程模擬：72f9f26

2026-09-02 執行，受測 commit `72f9f26`。**主要正常流程可以完成，但本輪確認三個流程卡關問題，不能判定整體已無問題。** 全套 361 項回歸測試通過；新增情境才暴露這些缺口。

本次只測試及保存報告，沒有修改 Cogito 產品程式、建立產品修正 commit 或推送。既有報告保持原樣。所有模擬的 Git 操作在隔離暫存 repositories 執行；核准及產品 Worker／Reviewer 身分為合成資料，並非真人核准或真實角色執行的行為評測。

## 已驗證的流程

| 項目 | 實際結果與證據 |
|---|---|
| Python 全套回歸 | 361 tests，50.293 秒，全部通過，無跳過；`unittest.log` |
| Feature、Change、Correction | 各以兩個相依 Slice，透過真正 CLI 完成準備、摘要確認、Package 核准、Start、兩波 Worker／checks／review／merge、post checks、finalize／report；全部 `accepted` |
| 人工驗收分支 | Feature post checks 後進入 `awaiting-human`，模擬核准後 `accepted` |
| 產品 check 故意失敗 | verification 拒絕，停在 `verifying`，未錯誤推進 |
| 最後驗證後修改產品 | finalize 拒絕，停在 `finalizing`，未錯誤 accepted |
| Maintenance | 真 CLI identifier rename、pre/post checks、唯一 final commit、`accepted`；詳見 CLI 報告 |
| Documentation、復原與修正 | 真 CLI 完成獨立審查、雙重 block/resume、human gate 及 `accepted`；92 項相關測試涵蓋 retry/replay 與三類修正，詳見 `recovery-audit.md` |
| 整合與交付路徑範圍修正 | 34 個 integration／finalization 相關測試通過，包含不合法整合的拒絕；`feature-integration-regression.log` |
| Git 快照時間戳修正 | 3 項同長同時間戳／linked worktree／staged 快照測試通過；原偶發 Maintenance review-fix 情境再跑 30 次皆通過；`snapshot-regression.log` |
| 非 object 事件修正 | 20 個真 CLI 案例皆 exit 2、結構化錯誤、無 traceback，events/cache/index 不變；`cli-behavior-summary.json` |

主代理六組 CLI 情境共保存 **586 次 CLI 呼叫**，不包含子代理與 unittest 內啟動的命令。精準測試與重跑包含全套回歸的重複案例，不能加總成額外獨立通過項目。主要情境與 final states 見 `main-scenarios.json`。

## 問題 1：P1，Maintenance 多任務無法提交第二個任務結果

位置：`cogito/scripts/cogito_run_store.py:275`、`:285`、`:287`。

合法 Mini Package 包含 `T-1 → T-2`，分別負責 `first.txt` 與 `second.txt`。同一個 Worker 依序執行，Package 核准、Start、lease 及第一個 Result 都成功。Maintenance 規定 final 前不建立產品 commit，因此第二個任務開始時仍有第一個任務的未提交修改。

- T-2 回報 `changed_paths=["second.txt"]`，被拒：`Agent Result changed_paths do not match its commit range`。
- 改成完整累積範圍 `["first.txt", "second.txt"]`，又被拒：`Agent Result exceeds its task path responsibility`。

原因是程式用 Start baseline 收集整個 checkout 的累積修改，卻要求這個集合等於單一任務的修改，並全部落在該任務的 paths。兩個合法任務的責任分離因此互相衝突，最終停在 `executing`，T-1 complete、T-2 running。

此問題由子代理及主代理各自執行重現。建議引入每個 Maintenance task 的開始／完成內容快照，以 task 增量驗證責任；另保留整體交付的 Package 範圍驗證。不能靠提前 commit 或讓每個 task 宣告所有路徑繞過限制。

證據：`recovery-multitask-probe.py`、`recovery-multitask-probe.log`、`recovery-multitask-independent.log`。

## 問題 2：P1，同一 Feature Slice 的多任務無法完成獨立審查

位置：`cogito/scripts/cogito_run_store.py:264`、`:272`、`:287`。

同一 Slice 的 `T-1 → T-2` 依序修改不同檔案、各自建立 commit。兩個 Implementer Results 與 controlled check 都通過，狀態進入 `reviewing`，但第一個任務的 Reviewer Result 無法被接受：

- 使用 T-1 原本完成的 head，被拒：`Agent Result commits are not bound to the leased worktree`，因 Slice worktree 已前進至 T-2 head。
- 使用目前 Slice head，被拒：`Agent Result exceeds its task path responsibility`，因 T-1 base 到最新 head 包含 T-2 的檔案。

第二個任務的 review 可以成功，整體 closure 仍因缺少第一個任務的獨立 review 而被拒，停在 `reviewing`。被拒的 Reviewer Results 未改動事件。主代理已獨立重現；兩個 task 使用相同 Worker ID 的對照也有相同結果。前兩項列 P1 是因為合法的常見多任務配置無法完成，不代表本輪觀察到未核准交付或資料毀損。

建議把 Reviewer Result 綁到要審查的 Implementer Result／task commit range，並另驗證該範圍與目前 Slice head 的 ancestry 和最後驗證內容關係；不能取消獨立審查或整體內容驗證。

證據：`feature-multitask-probe.py`、`feature-multitask-probe.log`、`feature-multitask-independent.log`、`feature-multitask-evidence.tar.gz`；同 Worker 的對照結果見 `feature-audit.md`。

## 問題 3：P2，核准前錯型資料被凍結，後續 Package 無法準備

位置：`cogito/scripts/cogito_workflow.py:55`、`:58`，以及 Package 與既有確認／Boundary 的綁定驗證。

真 CLI 分別接受 `shared_understanding_hash=123`、`boundary.evidence="not-an-array"` 並前進。前者在摘要確認後、後者在 Boundary 完成後，皆可到 `package-preparing`。

- Package 保留錯型資料：被 Package contract validator 拒絕。
- Package 改成合法資料：因不等於已凍結的摘要／Boundary，被綁定驗證拒絕。
- 在此狀態重新送摘要或 Boundary event：非法轉移，被拒。
- `block → resume`：回到原本的 `package-preparing`，修正版 Package 仍被拒。

摘要在**確認之前**可以重新提交合法 hash；本次卡關的條件是錯型摘要已被確認，或錯型 Boundary 已完成。未觀察到錯誤核准或交付，但同一 run 無法透過已提供的正常修訂／resume 路徑繼續，需要取消重建或修正 runtime。

建議在寫入摘要與 Boundary event 前套用與 Package 一致的型別及內容驗證，保證拒絕時事件與狀態不變；若支援修復已存在的壞 run，需設計明確的合法復原流程，不應手改權威 events。

證據：`cli-behavior-commands.jsonl`、`cli-behavior-summary.json`、`cli-behavior-audit.md`。

## 範圍與限制

- 全套程式測試通過，不等於 14 個自然語言 Agent 行為 eval 通過。Grilling 品質、語意等價判斷、真實 Reviewer 品質、lazy adoption 等仍須獨立行為評測；逐項覆蓋見 CLI 稽核報告。
- Eval #11 對 human approval 前不得 merge 的期望，仍和既有 workflow 先 integration、再 post verification、再 awaiting-human 的順序矛盾；這是既有規格議題，本輪未修改，也不計為新 runtime 缺陷。
- mypy 未安裝，嘗試執行得到 `No module named mypy`；未宣稱靜態型別檢查通過。未執行額外 skill 格式驗證、外部服務或部署。
- 無法窮舉所有並行排程、程序崩潰時點或檔案系統差異。本輪確認的是以上具體情境，不能宣稱全部可能路徑無問題。

## 重現與保存

從 repository 根目錄執行：

```sh
python3 -m unittest discover -s cogito/tests -v
python3 -B cogito/evals/reports/2026-09-02-flow-simulation-current/recovery-multitask-probe.py
python3 -B cogito/evals/reports/2026-09-02-flow-simulation-current/feature-multitask-probe.py
```

`main-cli-evidence.tar.gz` 保存主流程腳本、逐次 CLI 參數及 stdout/stderr、events、runner evidence、Result、Project Graph 與測試 Git objects。`run_cli_simulation.py` 與 `fixture_cli.py` 亦另存於報告目錄；重跑時請複製到新的暫存資料夾，使用 `--source` 指向目前 repo，避免覆寫先前現場。封存內的 worktree 與 evidence 含原始絕對路徑，搬移封存不代表可直接 resume。

環境資料見 `environment.json`。本次三位子代理均在 10 分鐘內完成，沒有逾時或需要換人交接：

| 子代理 | UTC 開始／完成 | 報告工作段耗時 |
|---|---|---|
| Feature | 15:41:54 → 15:46:42 | 4 分 48 秒 |
| Recovery | 15:42:07 → 15:47:22 | 5 分 15 秒 |
| CLI／behavior | 15:42:16 → 15:47:48 | 5 分 32 秒 |

以上是各代理記錄的開始至報告完成時間；代理最終回覆也都已在 15:48:08 UTC 左右收齊，距最早派發不足 7 分鐘。CLI 子代理另外保存 68 次 CLI 呼叫，混合 Git 等命令共 110 筆；未加到主代理 586 次的數字中。

本輪優先待修項目是多任務責任／review 綁定，以及核准前的輸入驗證。
