# Package 核准前重新規劃：實測報告

日期：2026-09-03。受測版本：`7a6b2b0`。結論：問題存在，且除了缺少合法回退路徑，也觀察到沿用舊共識／Boundary 的語意一致性缺口。

本次只驗證，未修改產品程式、工作流程或真實專案的 run／Graph，未 commit。所有模擬核准、取消、Start Gate 與 Git 操作均發生在可拋棄的暫存 repository。兩位子代理分別驗證狀態轉移及契約綁定，均在 10 分鐘內完成；主代理補測歷史重建與獨立 run 的限制。

## 主要結果

| 情境 | 實測結果 | 意義 |
| --- | --- | --- |
| 等待 Package 核准時重新提交共識／確認共識 | CLI 拒絕：event not legal | 無法回到必要的需求確認階段 |
| 同階段重新提交 Boundary | CLI 拒絕：event not legal | 無法重做並登錄新的邊界分析 |
| block 後 resume | 回到 awaiting-package-approval；候選 hash 不變 | 恢復原階段，沒有回退規劃功能 |
| 對未核准來源使用 RP begin | 拒絕：run has no approved Package | 上輪新增的核准後承接流程不涵蓋此案例 |
| 候選帶入新的共識 hash 或新的 Boundary | prepare-package 拒絕不符合既有紀錄 | 有上游身分綁定，但沒有合法更新上游的路徑 |
| 三功能改為只做篩選，更新 Spec／Plan hash，但保留舊共識／Boundary | prepare、approve、start 全部成功 | Gate 不會自行證明語意相容，也未攔住此範圍縮減與舊紀錄的矛盾 |
| 同一 run 發布新版候選後核准舊候選 | 拒絕：differs from the Gate-validated candidate | 最新候選 hash 保護正常 |
| 刪除狀態快取，再重建、重送舊 prepare action | 保持新版候選，journal 不變 | 一般候選的重建及 action 重播保護正常 |
| prepare 後修改 Spec 實檔而不更新候選 | approve 成功；start 拒絕 content hash drifted | 實檔一致性檢查在開始前攔住，不等於核准階段已驗證文件一致 |
| 另開獨立新 run 重新準備候選 | 舊 run 不變，舊候選仍可核准 | 新 run 不自動代表舊 run 的替代版本 |
| 模擬使用者明確取消舊 run，再開新 run | 舊 run cancelled、不可核准；新 run 可以重新準備 | 人工重開可行，但不是自帶關聯、失效規則與交接復原的正式修訂流程 |

## 具體案例

起始共識文件明確寫著「篩選、完成統計、JSON 匯出均為本次必要範圍」，Boundary 是 split-required 並列出三項責任，候選包含 B、C、D 三個 Slice 與三項任務。

使用者要求只做篩選後，有兩種觀察：

1. 如實替換共識 hash 或 Boundary，Gate 拒絕；嘗試重新進入確認／Boundary 階段也拒絕，正常修改卡住。
2. 保留舊共識 hash 與 Boundary，只刪除 C、D 的 Slice／任務，修改篩選 Spec／Plan 為「只做篩選，其他延後」並更新文件 hash，Gate 卻允許進入 executing。

第二種是診斷探針，並非建議操作方式。沒有繞過使用者 Package 核准、竄改事件或偽造 hash；探針在暫存環境顯式呼叫 approve。缺口是新的 Package 即使被核准，仍能引用內容不一致的舊共識／Boundary，並且沒有新的共識確認或邊界事件。

## 歷史與復原的界線

現有事件是追加保存，候選 hash 與 action request fingerprint 可重播，拒絕的轉移不會污染原 journal。這些保護已有實測證據，不能說 Cogito 完全沒有歷史或復原能力。

但 package-ready 事件的 payload 只有 `package_valid` 與 `candidate_package_hash`；Gate 不在此事件封存完整候選內容或要求修訂理由。如果呼叫方覆寫舊草稿，僅靠此候選事件不能重建原文。現有機制也沒有本次所需的規劃輪次、上游變更所導致的下游失效、跨 run 替代關係，以及相應的中斷恢復流程。

## 證據與驗證範圍

- [狀態轉移報告](transitions-report.md)、[13 次 CLI 操作結果](transitions-results.json)、[可重跑探針](transitions-probe.py)。
- [契約綁定報告](binding-report.md)、[CLI 完整輸出](binding-output.log)、[兩個可重跑探針](binding-probe.py)。
- [歷史／獨立 run 結果](recovery-results.json)、[三個可重跑探針](recovery-probe.py)。
- 現有回歸：`test_package_revisions.py` 3 項通過（2.663 秒）、`test_shared_revisions.py` 5 項通過（1.992 秒）。
- 本次新增診斷：binding 2 項通過，recovery 3 項通過；transitions 腳本各斷言通過。未宣稱重跑整套產品測試，亦未測所有故障交錯。

重跑命令（專案根目錄）：

```sh
python3 -B cogito/evals/reports/2026-09-03-preapproval-audit/transitions-probe.py
python3 -B cogito/evals/reports/2026-09-03-preapproval-audit/binding-probe.py
python3 -B cogito/evals/reports/2026-09-03-preapproval-audit/recovery-probe.py
python3 -B -m unittest discover -s cogito/tests -p 'test_package_revisions.py' -v
python3 -B -m unittest discover -s cogito/tests -p 'test_shared_revisions.py' -v
```

程式定位：

- `cogito/workflows/cogito-v3.json:13`：前置準備只向前，Package 等待階段只有候選自循環與核准。
- `cogito/scripts/cogito_run_store.py:206`：候選準備、共識 hash／Boundary 精確比對及候選事件內容。
- `cogito/scripts/cogito_run_store.py:723`：核准綁定候選 hash。
- `cogito/scripts/cogito_run_store.py:869`：resume 只能使用 blocked_from。
- `cogito/scripts/cogito_replan_store.py:75`：RP begin 先讀取已核准 Package。
- `cogito/scripts/cogito_projection.py:205`：候選、共識及 Boundary 的事件投影。

本次沒有選定或實作新的架構。後續設計至少需要明確表達修改層級、保留舊規劃歷史、讓受影響下游失效、重新確認必要共識，並將新版核准綁定到同一輪規劃成果。
