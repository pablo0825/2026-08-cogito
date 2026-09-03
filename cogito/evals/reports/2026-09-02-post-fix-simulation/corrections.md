# Maintenance 修正鏈重新模擬

本段開始 2026-09-02 14:56:24 UTC，完成 15:00:36 UTC，耗時 4 分 12 秒，低於 10 分鐘限制。所有變更與提交限於隔離演練 repository，未修改或提交 Cogito source，未再派子代理。所有執行程序已結束。

## 完整串連結果：accepted

腳本 `run-chain.py` 使用真 CLI 與 Git，依序執行：

1. 核准 Maintenance Mini Package，Start Gate，T-1 lease／implementation result。
2. controlled check 實際失敗，建立 TA-pre，technical correction 以未提交 snapshot 完成；HEAD 維持 Start HEAD，重新 check 通過。
3. 登錄不同 ID 的 Reviewer needs-fix 結果，review-fix-start，建立 TA-review 並新增 T-2，完成 lease／implementation result；snapshot completion，重新 check 通過。
4. Reviewer 對 T-1、T-2 各自提交通過結果，review-approved，integration 恰好一次。
5. 注入 post-integration 缺陷，controlled check 實際失敗；TA-post correction 仍使用 Start HEAD snapshot，直接返回 post-integration-verification，重新 check 通過。
6. 唯一 final commit 一起保存產品內容、Result、Graph，帶齊 TA-pre／TA-review／TA-post 三個 trailers，finalize／report 成功。

最終 commit：`7e5420c179b353b074575015dc3c659c1f4bcc0a`。相對 Start HEAD 的新 commit 數為 1；integration 事件數為 1；verification_corrections 為 2，review_fix_cycles 為 1。三個 completion 均保存有效 Git content_tree 與 working-tree 模式；Result 不含自身 commit，report 衍生的三個 amendment commit_id 均指向唯一 final commit。

證據：`cli-transcript.jsonl`（完整 CLI argv/stdout/stderr）、`chain-summary.json`、`report.json`、`chain-repo/.cogito/runs/DEV-resimulation-chain/events.jsonl`。前後比較可確認本次修正已消除先前 Maintenance correction 必須提前 commit 而不能單一提交結案的矛盾。

## 八項精準測試：8/8 通過

腳本 `run-targeted.py`，紀錄 `targeted-tests.log`；共 7.271 秒，0 failures、0 errors。

- 真 CLI：staged 越界 snapshot 拒絕。
- 真 CLI：untracked 越界 snapshot 拒絕。
- 真 CLI：提前 correction commit 拒絕。
- 真 CLI：final commit 缺 amendment trailer 拒絕。
- 真 CLI：多 amendment 只帶部分 trailer 拒絕。
- 真 CLI：即使內容已驗證，merge final commit 仍拒絕。
- Pure contract：Feature 與 documentation 不得套用 Maintenance working-tree amendment 紀錄。
- Pure contract：Feature 與 documentation 保留 commit 型 amendment 紀錄。

另以 `run-kind-retention.py` 補上兩種 kind 的真 CLI／Git 驗證：Feature 與 documentation 均在缺 trailer 的 correction-complete 拒絕且 events 不變；建立帶正確 trailer 的真 commit 並重新登錄 implementer result 後 completion 成功，保存 commit_id，未寫入 Maintenance 專用 completion_mode/content_tree。證據 `kind-retention-cli-log.json`、`kind-retention-summary.json`。此檢查範圍為 correction commit/trailer 路徑，沒有宣稱完整跑完兩種 kind 的 finalization。

測試腳本初版有兩個 fixture 設定問題，均修正後重跑：Feature worker allowed_paths 比 approved_paths 寬；既有 context("documentation") fixture 其實回傳 Maintenance，需要明確設定 kind 與 package_hash。這些是本次測試 scaffolding 問題，不是產品問題；最终脚本與保存的測試紀錄是通過版本。

## 仍存在的 P1：Maintenance 忽略 staged 路徑，造成誤拒與越界交付

已依主代理要求獨立 read-only 核對以下原始證據：

- `/tmp/cogito-resimulation-20260902/staged-maintenance/summary.json`：合法 note.txt 變更在 unstaged／mixed 時 Agent Result 成功，staged-only 時卻拒絕 `Agent Result changed_paths do not match its commit range`，拒絕時 events 不變。
- `/tmp/cogito-resimulation-20260902/staged-scope/cli-log.json`、repo 的 canonical Package、events 與實際 final Git diff：凍結 approved_paths 只有 note.txt，Agent Result 也只宣告 note.txt，卻在 accepted 的 final commit `bcb0062570a40e65c2f643291d8bf039b71fb554` 同時包含 unrelated.txt。真 Git diff、finalization-complete event、CLI accepted 結果均核對一致，不只依賴 summary。

根因位於 `cogito/scripts/cogito_run_store.py:270–278`：Maintenance 以 base..head 差異（單一提交前兩者相同），再聯集無 --cached 的 git diff 與 untracked 檔案，漏掉 index 相對 HEAD 的 staged-only 變更。因此合法 staged-only 檔案未被計入造成誤拒；未申報的 staged 越界檔案也未被路徑 guard 檢查。Controlled runner snapshot 仍包含 staged 內容，而 Maintenance finalization 只確保與已驗證 snapshot 一致，無法替這個遺漏補上授權邊界檢查，最終可接受越界交付。

這是同一根因的兩個影響，建議合併為一個 P1 問題。上列精準測試中的「staged scope 拒絕」驗證的是 correction-complete 的新 snapshot guard；它確實有效，但普通 Maintenance 主路徑若不進入 correction，不會使用該 guard，因此不能據此推論主路徑的 staged scope 已受保護。

建議修正方向：Maintenance Agent Result 路徑計算必須覆蓋 index、working tree 與 untracked 的完整變更，並維持與 runner/finalization snapshot 相同語意；新增合法 staged-only 與 staged 越界完整 accepted 路徑的回歸測試。本段沒有修改 source。

## 交接

工作已完成；無執行中 subprocess、無待接手的 agent。本段完成串連重驗與指定負面測試，並確認上述仍存在的 P1，請主代理納入封存報告。沒有因本段重驗而新增其他未證實問題。
