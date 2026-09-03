# Cogito 復原／Mini Package 模擬稽核

本子代理於 2026-09-02 15:42:07 UTC 開始，於 15:47:22 UTC 完成主要驗證與報告（5 分 15 秒）；沒有再派子代理，未修改產品程式。讀取 SKILL.md、execution-policy.md 與 runtime-interface.md 作為受測規格，沒有啟動正式產品開發流程。Git 操作全在臨時 repository，使用隔離的 Git config 與停用 hooks/signing；報告與重現腳本留在本目錄。

## 結果

92 項既有相關測試全部通過；額外獨立 CLI 模擬的 documentation＋human gate＋double block/resume 完整走到 accepted。獨立 Maintenance 多 task 探測找到 1 個真實流程缺陷：已核准的串行、不同責任路徑任務會卡在第二個 Implementer Result。

### [P1] Maintenance 多 task 累積 dirty paths 與單一 task 責任範圍衝突

位置：`cogito/scripts/cogito_run_store.py:275-288`，尤其 285 的完整路徑比對與 287 的 task 路徑責任比對。

最小重现：從專案根目錄執行：

```sh
python3 -B cogito/evals/reports/2026-09-02-flow-simulation-current/recovery-multitask-probe.py
```

1. Maintenance Mini Package 核准 `first.txt`、`second.txt`。
2. T-1 責任路徑只有 `first.txt`，T-2 只有 `second.txt`；合法 DAG edge 是 T-1 → T-2。
3. prepare、approve、start 均通過；T-1 lease、running、修改 `first.txt`、提交 Result、complete 均通過。
4. T-2 lease、running、修改 `second.txt`，HEAD 遵守 single_commit 政策保持 Start HEAD。
5. T-2 回報自己更動的 `changed_paths=["second.txt"]`，收到 `Agent Result changed_paths do not match its commit range`。
6. T-2 改為完整回報 `changed_paths=["first.txt","second.txt"]`，收到 `Agent Result exceeds its task path responsibility`。
7. run 維持 executing，T-1=complete、T-2=running，無合法 Result 可以讓 T-2 完成。

證據：`recovery-multitask-probe.log`。主代理已獨立重跑確認。

根因：Maintenance 為了維持最後唯一 commit，以相同 baseline 計算整個 checkout 累積的 staged/unstaged/untracked path。第二個 task 的 actual_paths 也包含上一 task 的路徑；之後又要求所有 actual_paths 都屬於第二 task。這不是不合法 package，也不是嘗試擴張路徑。

建議：lease 時記錄 task 開始的工作樹 snapshot，Result 以該 snapshot 的變動驗證當次 task 的責任範圍，同時另行檢查全工作樹是否仍在 Package approved_paths。需保留 staged/unstaged/untracked 與 rename 的完整安全檢查，不能直接忽略非 task path。新增至少兩個不同路徑串行 maintenance task 的回歸測試；同樣檢查新增不同路徑 amendment task 的情境。

## 獨立 CLI 完整模擬

重跑方式：

```sh
python3 -B cogito/evals/reports/2026-09-02-flow-simulation-current/recovery-documentation-human.py
```

此腳本利用既有 CLI 呼叫器，但 scenario 與斷言獨立編寫。建立 documentation package、README 格式調整與 deterministic check，凍結一個 applicable human predicate。實際走過：

`preparing → awaiting-package-approval → start-gate → executing → blocked → blocked → executing → verifying → reviewing → integrating → post-integration-verification → awaiting-human → finalizing → accepted`。

- double block 保留原本 executing 來源；resume 回到 executing，transient_retries=1 沒有重設。
- documentation 申請 Maintenance review exemption 被正確拒絕，之後以不同 reviewer 的逐 task Result 完成獨立審查。
- pre/post 都執行 controlled runner，使用各次 action 真正落盤事件指定的 evidence。
- applicable predicate 正確進入 awaiting-human；尚未 human-approve 時直接 finalize 被拒，且事件檔不變。
- 人工核准以模擬 CLI 指令輸入；之後原子提交 Result／Project Graph 並成功 accepted；這是臨時資料的模擬核准，不代表取得真實產品授權。
- 最終 22 個事件，human-review-required 與 human-approved 各 1 個。report 回傳 accepted、checks passed、獨立 reviewer、human required/approved 與 final commit。

完整輸出：`recovery-documentation-human.log`。臨時 repository 結束後清除，因此 log 中的 Git IDs／evidence 路徑僅為該次模擬資料；腳本可重建。

Harness 除錯紀錄：早期草稿把 Reviewer requested_transition 填為 integrating；正確值應為 review-approved。另一草稿以排序後 evidence dict 的最後項目選取新 evidence，導致選中前一驗證輪次並收到 `evidence predates the current verification cycle for C-doc`。兩項都已修正，最終用全新臨時 repo 重跑通過，不列為產品缺陷。前次 log 被後次重跑覆蓋；原錯誤曾在工具輸出出現，本文保留原因與結果。

## 既有測試與覆蓋

| 測試命令 | 數量 | 結果 | 記錄 |
|---|---:|---|---|
| `python3 -B -m unittest discover -s cogito/tests -p 'test_maintenance*.py' -v` | 21 | OK，10.515 秒 | recovery-maintenance-tests.log |
| `python3 -B -m unittest discover -s cogito/tests -p 'test_action_replay.py' -v` | 17 | OK，4.381 秒 | recovery-replay-tests.log |
| `PYTHONPATH=cogito/tests:cogito/scripts python3 -B -m unittest test_block_recovery test_approval_recovery test_runner_termination test_correction_rules test_finalization_rules test_process_capture test_runner_evidence test_capture_failures -v` | 54 | OK，2.276 秒 | recovery-other-tests.log |

覆蓋已實際執行的行為：

- Maintenance 前／後 integration correction 完成、只產生唯一 final commit、所有 amendment trailer、content_tree、Result 摘要。
- Maintenance review-fix 新增 task、實作結果、工作樹修正 snapshot、重新 controlled checks，返回 reviewing。
- 不合法 early commit、錯誤 branch、超界 staged/untracked paths、漏 trailer 與 snapshot 竄改的拒絕。
- 完成 action 在狀態前進後重播不重執行；action 同 ID 但不同輸入／不同命令的拒絕。
- runner evidence 已發布而事件未記錄，重送補登事件且外部計數器只有一次；事件已記錄後失敗，也不再執行 check。
- check 已開始但 evidence 未完整發布時，結果視為 unknown，拒絕自動重跑；同 action 併發執行只跑一次。
- approval 在事件前失敗的 rollback、事件後失敗保留正式 approval、未知 outcome 保留現場，以及 cache 缺失／损壞重新投影。
- process stdout/stderr EOF 後仍等待程序；timeout、輸出上限、termination degraded 與 cleanup failure 正確 fail closed。

以上是本子代理負責範圍，不替代全專案測試總數，也不宣稱所有失敗復原組合已窮舉。
