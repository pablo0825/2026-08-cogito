# 路徑重用整合驗證

日期：2026-09-09。交付版本：4.4.4。

## 來源與範圍

整合 `2025-06-pointsReview-backend` 中 `6004180`、`08466f6`、`a82a707` 的 Cogito 修正（後端 merge commit `736e0f9`）。使用者已同意修改；本次為 Cogito repository 維護，未啟動新的 Cogito Run。

修正本輪 review-fix Task 無法補列已完成同 Slice 路徑，以及 executing Task 無法補列原 Package 已核准、已整合前置 Slice 路徑的問題。前置路徑若同時為精確 `read-only-source`，仍承認原核准修改範圍。停止 executor、獨立 scope review、原 Package／Task／Result／evidence 不變等既有要求保留。

整合時另修正不存在 Slice ID 的 `KeyError`、從 DAG `edges` 推導前置關係，並統一路徑授權與 delivery binding 的雙向 overlap 判定。新增 Git 測試使用 `GitTestCase`／`init_repo()`。

## 自動化測試

以下為本次實際執行結果，不是後端歷史報告。從 repository root 使用 `python3 -m unittest discover -s cogito/tests -p '<pattern>'`；多組測試的彙整執行使用同一個 unittest discover API。Git／程序流程測試在允許 `ps` 檢查測試程序身分的環境執行。

| Pattern | 數量 | 結果 |
| --- | ---: | --- |
| `test_*path_reuse.py` | 40 | 通過 |
| `test_path_reuse_flow.py` | 3 | 通過 |
| `test_path_amendment*.py` | 22 | 通過 |
| `test_review_path_amendment.py` | 6 | 通過 |
| `test_batched_review_correction.py` | 2 | 通過 |
| `test_amendment_dependencies.py` | 7 | 通過 |
| `test_effective_scope_consumers.py` | 4 | 通過 |
| `test_contract_materialization.py` | 6 | 通過 |
| `test_action_replay.py` | 18 | 通過 |
| `test_event_payload_compatibility.py` | 3 | 通過 |
| **合計** | **111** | **通過** |

選測覆蓋路徑契約、直接／間接前置、原始與有效核准範圍區別、凍結來源／hotspot、owner 狀態、Git ancestry、proposal/review CLI、事件重送與重建、executor 封存恢復、目前內容重新驗證，以及原 Package／Task／evidence 不變。前置流程測試完成後續 Slice 整合及 post-verification，審查修正流程測試完成修正與獨立 Reviewer Result 登錄。這些為自動化 fixture 中的 Gate 執行，不是對真實產品的人類驗收。

另以 mypy **1.20.2** 執行 `python3 -m mypy --config-file cogito/mypy.ini`：27 source files 通過。工具安裝在暫存目錄，未加入產品依賴。文件相對路徑、`amend-paths`／`propose`／`review` CLI help 與 `git diff --check` 均已檢查。

## 獨立檢查與適用限制

- 獨立子代理完成程式審查，未發現阻擋交付的 scope 或歷史 replay 問題。
- 獨立子代理完成 focused reading simulation，涵蓋本輪修正、前置重用、拒絕條件、停止與覆核順序、歷史保留。此結果是依文件推演的 agent 決策，不代表實際生產執行或人類驗收。
- 兩種重用例外不自動疊加：前置重用後的審查修正應在新 Task 的完整 `paths` 直接列入既有有效範圍；既有修正 Task 再漏列該檔案仍須遵守共通限制。
- 未執行無關的全量 regression、獨立 skill 格式 validator、真實產品 agent 行為評估或 CI；不聲稱這些檢查已通過。

## 相容性

CLI 輸入不變，原 Package 與 amendment JSON 不改寫，effective hash 仍由原核准 Package hash 與原始 amendments 計算。新前置 proposal 增加 `predecessor_deliveries` 綁定，review 與 replay 比對 owner delivery heads 及目標 baseline；未涉及前置重用的既有 proposal 不要求新增此欄位。無資料遷移，不復活退役格式。舊版不具備新重用規則，不保證降版後能讀取新增的重用事件。
