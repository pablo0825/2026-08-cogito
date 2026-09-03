# 方案 A：分階段提交與人工驗收模擬

從專案根目錄執行：

```sh
python3 cogito/evals/reports/2026-09-03-stage-delivery/simulate.py
```

此程式在臨時 Git repository 中實際呼叫公開 RunStore Gate，建立真實 commits，並啟動受控 Python 檢查。執行環境需要允許受控 runner 查詢程序（`ps`）。成功後才寫入 `simulation.json`；失敗會回傳非零退出碼，既有報告不代表失敗的重跑成功。

兩個情境都走過人工退回、局部修正、重新檢查、獨立 reviewer 身分、等待人工、明確同意及最後結案。Feature 先保存 Shared Understanding、Boundary、Package 三筆 commit，實作與修正分開提交，整合採 fast-forward。Maintenance 先保存 Package，Start Gate 之後維持唯一產品 commit。

`simulation.json` 是實際執行結果，保存各階段狀態、commit IDs、斷言結果及結案摘要。這些 IDs 來自已清除的臨時 repositories，供比對單次流程使用，不是此專案的開發 commits。

人工回饋、同意與 reviewer 回覆都是明確標示的合成測試資料。這項模擬驗證流程、版本綁定與提交規則，不代表真正使用者已驗收產品，也不宣稱完成自然語言理解或真人 UI 體驗評測。

對應回歸測試：

```sh
python3 -m unittest discover -s cogito/tests -p 'test_stage_delivery_acceptance.py' -v
```
