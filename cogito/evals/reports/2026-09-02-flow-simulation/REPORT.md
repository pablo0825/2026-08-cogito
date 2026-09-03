# Cogito 流程模擬紀錄

2026-09-02（Asia/Taipei）。受測 commit：`116e87a8257c565ca14ce843abb009ffd2b81bae`。

**正常流程可以結案，但確認 4 個可重現問題，不能判定全部流程沒有問題。** 原有 281 項回歸測試全部通過；額外操作演練發現核准前修訂與 Maintenance 修正的流程缺口，以及 CLI 的長 JSON 解析問題。本次只新增演練報告與證據，未修改產品原始碼、未在原專案 commit 或 push。

本次使用 3 位子代理：回歸測試、流程文件／runtime 審核、CLI 恢復探針。每位均在 10 分鐘內完成，無需更換接手。主代理負責 CLI 端到端演練與交叉確認。回歸代理約 90 秒、流程審核代理 4 分 14 秒，恢復探針代理亦在 4 分鐘內結束。

**實際執行範圍**

| 演練 | 結果 | 證據與範圍 |
|---|---|---|
| 完整回歸測試 | 281/281 通過，19.049 秒 | 34 個測試模組；[完整 log](unittest.log) |
| 兩個相依 Feature Slice | `accepted` | 107 次真實 CLI 呼叫、30 筆事件、三次 controlled checks |
| 適用 Human Gate | 模擬核准後 `accepted` | 110 次 CLI 呼叫、31 筆事件；有先停在 `awaiting-human` |
| 錯誤產品內容 | 正確拒絕 verify | 實際 check exit 1，事件與狀態不因失敗的 verify 改寫，停在 `verifying` |
| 最後驗證後夾帶修改 | 正確拒絕 finalize | 回報 `final commit changes unverified content`，停在 `finalizing` |
| 三種核准前階段 block/resume | 通過 | 連續 block 保留來源；resume 回原狀態；相同 action ID 不重複寫事件 |
| Maintenance 修正到結案 | 重現流程衝突 | 實際 CLI 的修正及後續 checks 成功，但 finalization 拒絕 |
| 摘要／Package 修訂 | 重現兩處無合法續接路徑 | 新 action ID 仍拒絕；詳見下列問題 |
| 長 inline JSON | 重現解析錯誤 | 254 bytes 成功、274 bytes 失敗；相同 10 KB 內容用檔案路徑成功 |

正常 Feature 流程實際走過 `preparing → awaiting-shared-confirmation → boundary-analysis → package-preparing → awaiting-package-approval → start-gate → executing → verifying → reviewing → integrating`，完成第一個 Slice 後回 `executing` 執行相依 Slice，最後 `post-integration-verification → finalizing → accepted`。上游尚未整合時，下游 lease 被正確拒絕。重送相同 implementation/review action 未新增重複事件。

自動結案 final commit：`d83892a92e543ced43a511135291b290f13db2ec`。Human Gate 演練 final commit：`2c64a90390e255cfbb9fd4ee1afb59bdaac0f6e1`。這些 commit 均在隔離測試 repository，不屬於 Cogito 原始碼 repository。

**確認的問題，依修正優先順序排列**

1. **P1：Package 等待核准後，修訂草稿無法重新送核准。** 首次 `prepare-package` 進入 `awaiting-package-approval` 後，修改尚未核准的 `stop_conditions`，以新 action ID 再 prepare 會得到 `Package preparation is not legal in the current state`；直接 approve 新草稿則得到 `approved Package differs from the Gate-validated candidate`。正常 resume 只回原狀態，沒有重新準備 candidate 的入口。這與文件要求「草稿有變動時重新驗證並確認核准」矛盾。位置：`cogito/scripts/cogito_run_store.py:188`、`:532`，`cogito/workflows/cogito-v3.json:17`。建議新增受控的 candidate 修訂操作與事件，保持已核准 Package 不可變；不要放寬 hash 比對。

2. **P1：Maintenance 修正成功後無法依既定規則結案。** 首次 controlled check 失敗後，新增 `TA-1`、進入 correction、修正內容；以 Start HEAD 提交 correction-complete 被拒，因缺少 `Cogito-Amendment` trailer。建立修正 commit 後可完成 correction、重新驗證、審查豁免、整合及 post verification。然而再提交 Result/Graph，總 commit 數變成 2，finalize 回報 `Maintenance must finalize as one commit from the Start Gate head`。這是修正要求與單一提交規則衝突。位置：`cogito/scripts/cogito_run_store.py:398`、`cogito/scripts/cogito_finalization.py:126`。建議明確支援 Maintenance 的未提交快照修正，再於 final commit 一次保存；或在進入修正前提供合法升級流程。

3. **P2：摘要等待確認時，使用者修訂無法更新摘要 hash。** `shared-understanding-ready(hash A)` 後再提交 hash B，回報 `event 'shared-understanding-ready' is not legal from state 'awaiting-shared-confirmation'`；block/resume 後重試亦失敗。文件要求更新摘要後繼續等待確認，但 workflow 沒有修訂轉移，後续 Package 又必須綁定舊 hash。位置：`cogito/workflows/cogito-v3.json:13`、`cogito/scripts/cogito_projection.py:168`。建議新增摘要修訂事件或合法返回準備階段的操作，保留原始歷史。

4. **P2：合法長 inline JSON 被誤判為超長檔名。** `_json_arg()` 在 JSON parse 前呼叫 `Path(value).is_file()`；本機 Python 3.12/macOS 對較長字串拋出 `Errno 63: File name too long`。274 ASCII bytes 的合法 JSON 即被拒絕。相同 10014 bytes JSON 寫入檔案後傳路徑可以通過，確認不是 guard 或內容驗證問題。位置：`cogito/scripts/cogito_gate.py:18`。暫時可改用 `--payload-json <JSON檔案路徑>`；修正應先辨識／解析 inline JSON，再處理檔案路徑。實際長度門檻依環境而異。

前三個流程缺口目前沒有在同一 run 中依文件直接完成的續接路徑。本次保留拒絕現場，沒有改寫 events/state、放寬 guards 或重寫 Git 歷史來使其看似通過。負向演練刻意停在被拒絕的位置；命令失敗不代表 runtime 自動進入 `blocked`。

另有一個**評測規格矛盾**：`evals/evals.json` 情境 11 要求 Human Gate approval 前不得 merge，但正式流程先整合、再 post verification、最後才做 Human Gate。建議釐清為「未經 Human Gate approval 不得 finalize/accepted」，或明確指出是在說較早的 Package approval。此項不是 runtime 故障，也不納入上述 4 項。

**證據、重跑方式與限制**

環境為 macOS 26.5.2 arm64、Python 3.12.10、Git 2.50.1。測試 repositories 隔離個人 Git 設定，關閉 hooks 與簽章。原始工作樹在執行前乾淨。

- [機器可讀總結](summary.json)：每個 CLI 情境的最終狀態、事件種類、預期拒絕與 commit。
- [完整證據封存](evidence.tar.gz)：包含重現腳本、CLI argv/stdout/stderr、原始事件與 evidence、隔離 Git repositories、子代理報告。
- [流程審核](flow-audit.md)、[恢復與 JSON 探針](recovery-audit.md)、[回歸測試交接](regression.md)。
- [摘要／Package 修訂紀錄](flow-revisions-log.json)、[Maintenance CLI 結果](maintenance-correction-log.json)、[恢復摘要](recovery-summary.json)。

完整回歸可在原專案根目錄重跑：

```sh
python3 -m unittest discover -s cogito/tests -v
```

CLI 演練使用現有 `test_feature_e2e.py` 的兩 Slice fixture，將狀態操作改成獨立 `cogito_gate.py` subprocess，並保留 repositories。封存內的 `run_cli_simulation.py` 與 `fixture_cli.py` 可複製到另一個新的輸出目錄，再執行：

```sh
python3 /新的輸出目錄/run_cli_simulation.py --source /Cogito專案路徑 --scenario happy-path
```

另外支援 `human-gate`、`failed-product`、`unverified-final`；腳本拒絕覆寫既有情境 repository。恢復探針 `recovery/probe.py` 接受另一個空目錄作為輸出參數。其他重現腳本保存本機的原始絕對路徑，搬到不同環境需先調整。封存的 Git worktree 管理資料與 evidence 也保留原始路徑，適合查證；移動封存不等於可直接 resume，應重新執行腳本。

Maintenance 首次 CLI 轉接演練曾因漏傳 `review_exemption` 請求而被正確要求 Reviewer；這是演練轉接器的遺漏，未列為產品 bug。修正轉接請求後，在新的 `maintenance-cli-confirmed` repository 完整重跑，確認本文所列的 finalization 衝突。原紀錄一併保留。

本次 Shared Understanding confirmation、Package approval、Human Gate approval 及 Implementer/Reviewer identity 都是明確的**合成測試資料**，不是實際使用者核准或真實不同 Agent 執行同一 Feature 的證據。三位真實子代理負責測試與查核，不等於 fixture 裡的 worker/reviewer。Grilling 的自然語言品質、Spec/Plan 的產品語意及所有 14 個 Agent eval 情境沒有逐一實跑；不可把本文當成完整 Agent 行為評測通過紀錄。Feature CLI 正常路徑沒有 Amendment；correction、review-fix 等其他支線的既有回歸 coverage 不代表每一條都另外做過 CLI 端到端演練。

文件要求的 mypy 指令已嘗試，但環境回報 `No module named mypy`，因此型別檢查未執行；skill 格式驗證亦未執行。上述缺項未計入 281 個通過測試。
