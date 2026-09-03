# 核准前範圍修訂：候選與共識／Boundary 綁定實測

- 日期：2026-09-03。
- 版本：`7a6b2b02ccc8a9b6852dfd89327007672379a478`。
- 未找到適用的 AGENTS.md。只讀產品程式；只新增本目錄 `binding-*` 證據。所有 Gate 狀態、Git commit 與模擬核准均在自動清除的暫存 repo，沒有修改真實專案 run。
- 執行 `python3 -B cogito/evals/reports/2026-09-03-preapproval-audit/binding-probe.py` 可重跑。原始命令／返回碼／狀態保存在 `binding-output.log`。2 個 probe 通過，耗時 0.988 秒。

## 結論

使用者指出的「只改草稿不能取代重新確認共識／重做 Boundary」有具體證據支持。Gate 會阻擋直接换掉已確認的共識 hash 或已記錄 Boundary；但沒有檢查新版 Spec/Plan/Slice/DAG 與舊共識／Boundary 的語意是否一致。因此，若作者保留舊綁定欄位，只改下游內容，機器 Gate 會接受。這不是舊候選 hash 保護失效，也不是 hash 碰撞；這是語意失效與重新規劃流程缺口。

另外，實檔 Spec hash 的漂移是到 Start Gate 才擋下：核准本身仍成功。因此「舊文件不能被核准」與「舊文件不能被執行」目前是兩種不同保證。

## Probe 1：三功能縮成只做篩選

可重跑程式 `binding-probe.py:27`。

1. 暫存 repo 的真實共識文件寫明「本次需完成篩選、完成統計、JSON 匯出三功能」，使用其實際 SHA-256 記錄共識並模擬確認。
2. Boundary 記錄 `split-required`，理由明確列出 B、C、D 三項獨立責任。初版 Package 有三個 Slice、三個任務，分別綁定實際 Spec/Plan hash。
3. 初版 `prepare-package` 成功，進入 `awaiting-package-approval`。
4. 把候選的共識 hash 改成另一個值，`prepare-package` 返回 2：`Package is not bound to the confirmed Shared Understanding`。
5. 把候選 Boundary 理由改成「只做篩選，其餘延期」，`prepare-package` 返回 2：`Package is not bound to the recorded Boundary Gate result`。
6. 重新從初版複製：移除 C、D Slice 和任務，將 B 的 Spec/Plan 改成「只做篩選，統計匯出延期」，更新真實文件 hash；共識 hash 與 Boundary 保持初版值。
7. 新版 `prepare-package` 返回 0；舊版 `approve` 返回 2：`approved Package differs from the Gate-validated candidate`；新版 `approve` 與 `start` 均返回 0，最後 `executing` 只剩 B。
8. 事件中仍只有一次 `shared-understanding-confirmed` 和一次 `boundary-complete`，沒有重新確認或 Boundary 重算事件。

範圍：此 probe 刻意模擬作者沿用舊共識識別值而改下游草稿；它證明 Gate 缺少此種保護，**不代表 Coordinator 一定會在正常操作時自行犯此錯誤**。沒有派出 Worker 或產生實作。

程式依据：

- `cogito/scripts/cogito_run_store.py:220` 比較共識 hash，`:222` 比較完整 Boundary JSON，`:227` 允許等待核准時再提交候選。
- `cogito/scripts/cogito_contracts.py:145` 至 `:163` 驗證 Slice 形狀、ID、文件欄位、責任路徑，沒有把 `split-required` 與具體 Slice 數量／舊 Boundary 理由或共識語意交叉驗證。
- `cogito/scripts/cogito_run_store.py:744` 保證只能核准目前候選 hash，此保護實測正常。

## Probe 2：prepare 後 Spec 原檔變動

可重跑程式 `binding-probe.py:91`，採用既有 `PackageRevisionTests.fixture`。

1. 建立有效 Feature Package 並 prepare。
2. 修改 `docs/spec.md` 實檔，候選內仍保留原 hash。
3. 用原候選 `approve`，返回 0 並進入 `start-gate`。
4. `start` 返回 2：`Package content hash drifted: docs/spec.md`。

程式依據：

- `cogito/scripts/cogito_run_store.py:206` 的 prepare 與 `:723` 的 approve 驗證候選結構、綁定和候選 hash，不讀 Spec/Plan 實際內容。
- `cogito/scripts/cogito_run_store.py:781` 至 `:786` 在 Start Gate 校驗 Spec/Plan 與 source registry 的實檔 hash。

因此沒有證明 stale Spec 可繞過 Start Gate，反而確認其會阻止開始實作；但目前核准前的一致性驗證與重新規劃恢復仍可改善。
