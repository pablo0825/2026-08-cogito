# Implementation Workflow

用於執行已核准 Plan 的 implementation batches，並以風險相稱的檢查維持快速回饋。

## 開始條件

確認 blueprint、Spec、Plan 與 Commit Plan 皆已核准，工作樹沒有無法安全分離的重疊變更。完整讀取 [commit-workflow.md](commit-workflow.md) 一次；同一 continuous sequence 的每個 batch 不重讀，只有中斷恢復時以 `$cogito` 重新讀取。Blueprint 的 `approved -> in-progress` 在第一個成功的 implementation commit 中作為 lifecycle housekeeping 保存；第一個 commit 前中斷時，以 working tree 識別未提交工作，不留下單獨的狀態修改。

使用者明確要求開始 `continuous` Plan 時，授權涵蓋所有尚未完成的已核准 implementation batches、各 batch Required Verification、完整 AI Verification 與 Verification Documentation commit。授權不涵蓋 Plan 未列出的 remediation code；完整驗證發現程式問題時，先提出 Plan revision proposal，取得 revision 授權後才新增 fix batch，並重新核准。依 I1、I2、…、In 執行，不在 batches 間詢問。

## Batch 執行

每個 batch：

1. 檢查 working tree 與目前 batch 的核准 Files。
2. 只實作 Purpose 與 Scope 需要的變更。
3. 執行該 batch 的最小充分 Required Verification。
4. 檢查 diff、message、檔案與排除項目後建立一個 commit；第一個 implementation commit 同步包含 blueprint `in-progress` lifecycle housekeeping。
5. 依 commit workflow 在同一 commit 從 Plan 移除已完成 batch；只在對話回報 Commit ID 與結果，不在 Plan 或 Verification 建立 execution record。
6. 直接進入 Plan 中下一個已核准 batch。

Batch Required Verification 是該 commit 的必要條件；結果為 `failed` 或 `not-run` 時不建立該 batch commit。不要因期限、已投入工作或後續完整驗證而略過。

不得擴張 Scope、處理其他 Slice、自行回答需求問題、擴大重構、修改未核准檔案或建立隱藏 commit。範圍內問題可修正並重跑驗證；需要新增或重組 batch、修改 Spec／Plan／Integration Contract、處理範圍外失敗、分離重疊變更或取得人類決策時停止。

## Risk-based Required Verification

以修改風險選擇 batch 檢查，不固定對每批執行完整 suite：

| 修改類型 | 預設最小檢查 |
|---|---|
| 純文件 | `git diff --check` 與文件一致性 |
| 局部邏輯、schema、mapper、component | 對應 targeted tests；型別邊界改變時加 typecheck |
| 跨模組 contract、route、provider、共享狀態 | targeted tests＋typecheck；必要時加相關 integration test |
| dependency、build、Vite 或 TypeScript 設定 | build＋相關測試；build 已含相同 TypeScript project 時不重複 typecheck |
| browser flow 或 responsive behavior | targeted Playwright／browser inspection；必要時加對應 unit tests |

- 優先對修改檔案或相關模組執行 lint；完整 lint 留給最終 AI Verification。
- `build` 已涵蓋同一 TypeScript project 時，不在同一 batch 重複跑完整 typecheck，除非 Plan 說明不同設定或額外風險。
- Targeted checks 只提供 batch 信心，不取代所有實作完成後的完整 AI Verification。
- Plan 必須說明超出預設最小檢查的理由，避免複製固定 command 套餐。
- 可獨立審查的測試放在緊鄰實作的 test batch；測試是讓實作 commit 安全成立的必要部分時可以同批。

## Sequence 完成

最後一個 implementation commit 完成後完整讀取 [verification-acceptance-workflow.md](verification-acceptance-workflow.md) 並直接進入完整 AI Verification。依核准 Plan 的 `V-*` mappings 執行 `required` 與 `advisory` checks；`human` 留給 Human Integration／Acceptance。驗證開始後維持核准的 mapping、Gate 與 Applicability；發現 Plan 遺漏專案明定的 release gate 時，先提出 revision proposal，取得授權後修訂並重新核准 Plan；額外的非必要補充檢查記為 `advisory`。

缺少 `Implementation Execution` 的 legacy `per-batch` Plan 維持每批明確授權，commit 後停止。恢復時以 Plan 中第一個尚未完成 batch 為下一步，並用 Git history 確認已提交工作，不重做已提交 batch。
