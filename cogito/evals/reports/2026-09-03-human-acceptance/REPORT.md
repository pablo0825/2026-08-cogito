# 人工驗收專用流程：實作與模擬驗收

日期：2026-09-03。依使用者選定的方案二，在同一 run 與事件歷史中增加人工驗收專用分類、修正、驗證及審查階段。

## 實作結果

- 人工回饋完整保存原意、問題清單、分類及理由；局部修正保持原 run，混合變更預設整批進 RP。只有明確拆批授權才能延後項目，已分類的變更不能直接改稱局部修正。
- 未明確表示驗收完成時，修正與審查完成後回 awaiting-human；只有本批明確授權「其餘接受、修好即可」才能直接 finalizing。仍須既有 final commit／finalize 通過才 accepted。
- 授權綁定回饋及交付版本。修正中收到新回饋會保存待處理批次並撤銷舊結案授權；待處理項目不會被普通 human-approve 忽略。
- 人工修正與開發修正額度分開，同一 run 人工修正累計最多三輪。第三輪正式檢查或審查失敗立即 blocked；超額 start 也停止。分批、重播、恢復或換 Agent 不重設。
- 每輪使用新 Amendment／task；重試仍需覆核前輪尚未完成審查的工作，不能只看最新新增的小任務。修正派工在 delivery checkout 串行執行。
- 正式證據必須屬本輪、目前 effective contract 及內容；optional-only checks 也要驗證真實性與成功結果。拒絕 Implementer Result 之後的額外未登錄內容及舊審查。
- 局部 Spec／Plan 調整保存新舊精確 bytes/hash，原 Package 不變；未宣告或任意文件修改遭拒。所有文件更新都在最後檢查前完成。
- Maintenance 保留原 Start HEAD 與工作樹快照，直到唯一 final commit 才提交；Feature 也經真實 final Gate 結案。
- 影響擴大立即停止流程，實際外部程序仍由 Coordinator 停止。RP successor 取得重新人工驗收要求，即使新 Package 的一般 human predicates 為空也不能自動略過。

## 提交分組

1. `d189aa9`：人工回饋與額度的純規則、對應單元測試。
2. `677815e`：專用 workflow／Gate、證據與結案綁定、RP 承接，以及真實 Git 回歸測試。
3. 操作文件與本報告、可重跑模擬器及實際輸出另行提交。

## 模擬結果

在第二筆實作提交後重跑真實 CLI，五個情境全部符合預期，原始結果見 `simulation.json`：

| 情境 | 實際結果 |
|---|---|
| 其餘已接受、局部修好即可 | accepted，含實際 final commit 與結案驗證 |
| 尚未驗收完成 | 修正及審查後回 awaiting-human |
| 同批局部＋變更 | route=change，局部 start 被拒，下一步準備 RP |
| 修正中影響擴大 | blocked，普通修正流程不能繼續 |
| 開發修正 2 輪＋人工修正 3 輪 | 計數各自保持 2／3，第四輪人工修正 blocked |

RP successor 重新驗收、文件修訂到 accepted、第三輪失敗立即停止、修正途中新回饋撤銷授權等，另由真實 Git 整合測試驗證。

## 驗證紀錄

- 最終全套：**480 tests passed，150.502 秒**，見 `regression.log`。
- 人工驗收專用集合：**31 tests passed，40.422 秒**，見 `acceptance.log`。
- 提交後重跑真實 CLI 模擬：**5／5 通過**，見 `simulation.json` 與 `simulation.log`。

文件相對連結與 `git diff --check` 通過。mypy 無法執行：環境回報 `No module named mypy`，本次不宣稱型別檢查通過。

## 模擬界線與分工

這些是實際 Git／CLI／受控程序的流程驗證；分類與 Reviewer 回覆由 fixture 明確提供，未將其宣稱為真實 Agent 理解任意自然語言或評判 UI 品質的行為評測。Gate 驗證版本、範圍、身分對應及證據；Coordinator 仍負責正確理解使用者意圖、判斷影響與確認實際獨立審查。

代理分批負責純規則、整合審查、實際流程測試、文件、模擬及後續邊界測試，同時最多三位子代理。每批均在八分鐘內交接；同一審查代理兩次工作的累計時間也未達十分鐘。整合、修正及 commit 由主代理完成。

重新執行方式見 [README](README.md)；正式操作協定見 [人工驗收退回](../../../references/human-acceptance.md)。
