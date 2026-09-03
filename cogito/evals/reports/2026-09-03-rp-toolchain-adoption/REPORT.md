# RP 工具接軌實作與驗證

日期：2026-09-03。基底為 `537b40629ab95017cc3ab991171244a66e25a273` 加上本次工作目錄修改；受測實作與新增測試的 SHA-256 見 `implementation.json`。

結果：**87 項 RP 與 planning 互通測試，277.058 秒，全部通過。** 型別檢查仍有與未修改 HEAD 完全相同的 6 個既有錯誤，詳見下方。

## 已完成的行為

新增 RP 限定的 `toolchain-propose`、`toolchain-review`、`toolchain-approve`、`toolchain-reject`。工具提案由 Gate 建立精確 manifests、差異及相容性檢查；獨立 Reviewer 與使用者核准分開記錄，不能藉此核准 successor Package 或產品修改。

新快照另存工具 binding；舊快照從保留 Git trees 取得舊工具內容。原 snapshot、來源成果、Package 與事件不覆寫。核准後的有效工具／HEAD 由追加事件定義，RP 回 analyzing，舊 RP 提案與覆核失效但歷史保留。相同 action ID 的重播不會再清除後續新提案。

工具 HEAD、index、content 與實際檔案分別核對；提交接軌要求同 branch 的線性 tool-only 歷史，逐個 commit 檢查。工具與產品／契約／Worker scope 重疊會拒絕。接軌不提供整個目錄的永久豁免，核准後任何工具變動都須新提案。

正式接軌及其後的受保護 RP 步驟使用每次新啟動的 CLI。入口在載入 Gate 模組前取樣來源，直接編譯來源而不讀取舊 bytecode，並核對每個已載入 Cogito 模組的實際來源 hash。長駐程序的直接 Store 呼叫不能代替此執行邊界。

## 與 FS-038／FS-043 對應的模擬

測試使用真實暫存 Git repository、Worker、事件記錄及公開 CLI。來源 fixture 的產品核准、工具覆核、使用者同意都為合成測試資料，沒有核准真實專案。

- 新／舊 snapshot，各自測試 unstaged、staged、committed 工具差異；未核准時拒絕，精確接軌後可以重新提出 RP proposal。
- committed 工具接軌之後，正常 RP propose → review → approve → handoff 成功；successor 進入 executing，原 Worker 與 snapshot 不變。
- 舊快照、既存候選、工具之後才提交：工具接軌保留候選原 hash 與事件，舊 baseline 明確拒絕；以正常 planning 新輪次更新 baseline、重新準備候選與覆核後，成功完成 RP handoff。
- 未提交接軌可繼續規劃，但 RP Package approval 在發布核准事件前拒絕；提交後另做工具接軌，清除舊 RP proposal，再正常更新候選。
- 產品混改、產品修改後又還原的中間提交、工具核准後漂移、index 改變、工具目錄內的凍結產品文件、任意工具根目錄、stale hash、自我覆核、待審工具案期間的產品核准及核准後階段的工具提案都拒絕。
- 工具否決不授權檔案變更，原有效 binding 保留；恢復原工具內容後可依正常流程保留來源暫停。
- 向暫存安裝放入 timestamp／size 有效但內容不同的舊 bytecode，CLI 仍執行當前原始碼。
- 在工具核准事件已 append 後注入 state cache 寫入失敗；同 action ID 重試恢復成功，無重複事件，snapshot 不變。

新增測試包含 18 個 Git／CLI 行為測試及 15 個純契約／事件投影測試；多個方法另含新舊快照與惡意輸入子案例。它們納入同一次 RP 相關回歸執行，不重複計為額外行為評估數字。先前問題重現的 9 個隔離模擬另保存在 `../2026-09-03-rp-toolchain-blocker/`。

## 重跑方式與限制

```sh
python3 -B -m unittest discover -s cogito/tests -p '*replan*.py' -v
PYTHONPATH=cogito/scripts:cogito/tests python3 -B -m unittest test_planning_rp_interop -v
```

本次將上述兩組合成單一 unittest suite，完整結果保存在 `regression.log`。fixture 的受控 runner 需要 OS 程序查詢，本次在允許 `ps` 的執行環境完成。回歸范围為所有名稱含 replan 的測試，加上 planning/RP 互通；不是整個 repository 的全部測試。

另外執行 mypy **1.20.2** 與 `cogito/mypy.ini`：目前工作目錄及隔離的未修改 HEAD 都回報 `cogito_projection.py` 同樣的 6 個既有型別錯誤，輸出逐字一致，沒有新增診斷。見 `mypy-current.log`、`mypy-baseline.log`；不能將本次型別檢查宣稱為通過。CLI 說明可列出新增操作，`git diff --check` 通過。

第一版仍限定 `.codex/skills/cogito`、未核准 successor 的 RP，且所有承接工作必須 rerun 驗證。工具檔案必須能從原快照建立證明；不支援補造未保存的舊工具。新增工具事件需要支援此協定的 Gate，舊版 Gate 不具備向前相容讀取能力。

本次只修改 Cogito 開發 repository 與暫存測試資料；未部署工具至 pointsReview，未修改或核准真實 FS-038／FS-043 的流程狀態。正式使用步驟、提案 JSON、核准與否決規則見 `cogito/references/replan-toolchain.md`。
