# Atomic 已驗證工作樹重驗修復

交付版本 5.0.1。移植後端專案 `91a64b23d077c294d8ea9304300386951784b4d5` 的 runner 修正與 7 項資格測試；該修正在後端由 `d870b52b5565c4702241aafbf3ff0bd2cbfbd0c6` 整合。本專案只取兩檔內容差異並調整路徑，沒有合併後端產品歷史。

## 問題與範圍

Atomic Run 返回 `verifying` 後，`next` 與正式 verification 已接受 `complete`／`verified` 工作樹，但 runner 只接受 `complete`。其他 Slice 修正造成 effective contract 改變時，仍為 `verified` 的工作樹可能需要新 evidence，卻無法執行提示提供的檢查。

修正僅讓 Atomic `verifying` 的 runner 同樣接受 `verified`。非 Atomic、其他階段、Task targeted check 與 delivery checkout 限制不變。歷史 evidence、Task Results、事件、hash 與公開回傳格式不變，不需資料遷移；正式驗證仍檢查目前內容與有效契約。未改清理提示、結案呈現或歷史工作樹盤點，也未建立共用資格框架。

既有 execution-policy.md 的正式驗證規則已要求綁定改變時重跑適用 checks；本次修復執行入口與該規則的不一致，未更改操作文件或 skill 指令。

## 自動化驗證

本輪 55 項針對性測試通過：

| unittest module | 通過數 |
| --- | ---: |
| test_verification_target | 7 |
| test_atomic_task_verification | 10 |
| test_next_operations | 13 |
| test_check_retry | 25 |

命令：

```sh
PYTHONPATH=cogito/scripts:cogito/tests python3 -m unittest test_verification_target test_atomic_task_verification test_next_operations test_check_retry -q
```

選測涵蓋修正的資格邊界、Atomic evidence／工作樹綁定、提示產生的 CLI 及共用資格判斷的 check recovery。隔離 Git fixture 的 runner 需要本機 `ps` 程序查詢，因此使用 sandbox escalation 執行。

新增串接回歸先完成兩工作樹的驗證，再對第一個 Slice 執行 review fix；第二個 Task 仍為 `verified`，舊 evidence 因契約改變而過期。測試實際執行 `next` 的 `run-check` argv，再執行新的 `verify` argv，確認回到 `reviewing`，並核對歷史 evidence bytes 與 Task Results 保留。此測試不宣稱覆蓋 `not_started` 重送。

實作前的串接 fixture 已在原 runner 重現工作樹資格拒絕。測試開發時曾加入 preflight recovery 斷言；既有策略會略過相同請求已有完成 evidence 的未啟動紀錄，因此移除不適用的斷言，保留直接執行提示的測試，未更改 recovery 政策。

`git diff --check` 通過。未跑全套回歸、CI 或 mypy；本次沒有型別介面變更。

## 獨立審查與限制

獨立子代理唯讀審查修正範圍、資格邊界及測試有效性；最終聚焦複查未發現阻擋問題。子代理未另跑測試。

未執行 skill 格式驗證、Agent 行為／閱讀模擬或真實使用者驗收。上述串接測試使用隔離 Git 與真實 CLI，不等同後端產品任務驗收。
