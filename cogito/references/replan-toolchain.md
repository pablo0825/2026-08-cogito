# RP 工具接軌

RP 停止後，專案內 `.codex/skills/cogito/` 的更新必須獨立提案、覆核及取得使用者核准。工具目錄不是永久例外；核准只適用於提案中的精確工具內容與 Git 綁定。工具核准不等於 successor Package 核准，也不授權修改產品。

## 支援範圍

- 一般工具接軌支援未核准 successor 的 RP：analyzing、reviewing、awaiting-approval、awaiting-decision。已寫入 `handoff-started` 的特定中斷點另使用下述 handoff repair。
- 支援新快照，以及尚未包含工具欄位的舊快照。舊工具必須仍可從原 Git trees 取得；沒有保存的舊 bytes 時拒絕接軌，不補造證據。
- 第一版固定工具根目錄為 `.codex/skills/cogito`。如果原產品、Worker 或契約範圍與此目錄重疊，不能以工具名義豁免。
- 新快照要求專案內工具的 regular files 完整出現在 Git content tree；被忽略的工具檔案會明確拒絕。Python `__pycache__` 為不執行的衍生快取，可由 Git 忽略；不能把產品檔案放入工具目錄當成快取。
- 未提交、已 stage、已提交的工具更新分別綁定。已提交更新只接受同 branch 的線性 tool-only 提交鏈；每個中間 commit 都檢查，拒絕 merge、產品修改後再還原，以及新控制文件混入提交。
- 未提交更新可先接軌並繼續規劃；在 **RP Package 核准前**，工具 HEAD／index／content 必須一致。否則先提交工具更新，再針對新 HEAD 提出新的工具接軌，不能等 handoff 時才處理 dirty checkout。

## 提案與覆核

將 JSON 輸入保存在 `.cogito/replans/<RP-ID>/drafts/` 或 successor 的 drafts 目錄。使用要承接的新版 Gate 執行；專案內工具與執行中的 scripts、workflow、VERSION 必須具有相同內容。接軌及接軌後的受保護 RP 操作必須透過每次全新啟動的 `cogito_gate.py replan` CLI；在原本長駐的 Python 程序直接呼叫 Store 會拒絕。CLI 在載入 Gate 模組前綁定來源，直接編譯原始碼並核對每個已載入 Cogito 模組，不讀取舊 bytecode。

工具提案輸入只有目的與身分；manifest 與相容性檢查由 Gate 產生，不能手填放行路徑：

```json
{
  "author_id": "tool-maintainer",
  "reason": "修復 RP runtime 快照並保留既有來源成果",
  "tool_root": ".codex/skills/cogito"
}
```

```sh
python3 .codex/skills/cogito/scripts/cogito_gate.py --repo . replan toolchain-propose --replan-id RP-001 --input .cogito/replans/RP-001/drafts/toolchain.json --action-id tool-propose-1
```

結果的 `toolchain_proposal` 包含原 snapshot hash、前次工具接軌 hash、新舊版本、三種 Git 視圖的路徑／mode／blob hashes、逐檔差異、提交鏈、執行程式與 workflow hash、候選 Package hash、相容性檢查及必要重驗清單。`toolchain_proposal_hash` 綁定整份提案。

獨立 Reviewer 必須檢查實際工具 diff、規則變更及重驗安排，不能只重複「compatible」。Reviewer 不得是提案作者：

```json
{
  "proposal_hash": "<toolchain_proposal_hash>",
  "reviewer_id": "independent-tool-reviewer",
  "findings": [],
  "assessment": {
    "events": "說明舊事件相容性與歷史保護的檢查結果",
    "contracts": "說明核准契約與有效契約未被擴大的依據",
    "projection": "說明事件重播及新舊投影的檢查結果",
    "workflow": "說明 workflow、validator 變更與相容性",
    "revalidation": "說明需要重新执行的 RP 與 successor 驗證"
  }
}
```

```sh
python3 .codex/skills/cogito/scripts/cogito_gate.py --repo . replan toolchain-review --replan-id RP-001 --input .cogito/replans/RP-001/drafts/tool-review.json --action-id tool-review-1
```

實際使用者同意精確 hash 後，才執行：

```sh
python3 .codex/skills/cogito/scripts/cogito_gate.py --repo . replan toolchain-approve --replan-id RP-001 --proposal-hash <toolchain_proposal_hash> --approver-id <user-identity> --action-id tool-approve-1
```

`approver-id` 是稽核身分欄位，不是驗證使用者身分的登入機制。與其他 Gate 一樣，操作者須確實取得使用者決策，不可把欄位值或測試的合成同意當成授權。

若不採用待核准的工具提案，可明確否決：

```sh
python3 .codex/skills/cogito/scripts/cogito_gate.py --repo . replan toolchain-reject --replan-id RP-001 --proposal-hash <toolchain_proposal_hash> --reason '覆核發現相容性問題' --action-id tool-reject-1
```

否決僅追加紀錄、解除待審工具提案的流程限制，保留前次已核准工具基準，不修改或還原檔案。未獲核准的工具／產品差異仍會被正常來源檢查阻擋。可以另提修正後的工具方案；若選擇回復舊工具內容，須有該檔案操作的明確授權，並使用能讀取新事件協定的 Gate 處理後續狀態。

## 接軌後續接

核准追加單一 `toolchain-approved` 事件，原始 snapshot 與所有事件保持不變。RP 回到 analyzing，清除目前有效的 RP proposal／review／approval 引用，歷史版本仍在 journal。相同 action ID 重送只回放結果，不再清除後續新提案。

工具核准不會改寫 successor Package。若候選仍綁定舊 HEAD，使用既有 `planning begin` 建立新一輪，保留需求、邊界、成果及文件，將 `baseline_commit` 設為已接軌的有效 HEAD，再 prepare-package、獨立 planning review。不得直接覆寫既有候選或沿用舊 hash。若候選已綁定該 HEAD 且仍有效，可直接準備新的 RP proposal。

接著正常 replan propose → review → approve → handoff。新的 RP proposal 綁定工具接軌 hash。第一版一律要求 `validation: rerun`，成果仍可 retain／adapt，但不採用舊工具下的驗證證據。產品、原 Worker、契約、歷史、工具實際內容仍在每個受保護步驟重新核對；工具再次變動必須另開工具接軌提案。

## Handoff 中斷後的工具修復

這個流程只接受 `handing-off`、successor 仍為 `start-gate`、沒有 transfer plan／receipt、source 尚未 superseded，且 Graph 仍是停止版或核准版。修復必須已完整提交，提交鏈只能改 `.codex/skills/cogito/`；HEAD、index、content 三份工具 manifest 必須相同。Mini successor 仍受 RP handoff 的 dedicated Worker 限制。

依序使用 `handoff-tool-propose`、`handoff-tool-review`、`handoff-tool-approve`（或 `handoff-tool-reject`）。參數格式與一般 toolchain 操作相同。提案額外綁定停止快照、原產品 proposal／approval、`handoff-started`、source／successor event、Package、Graph 與空 transfer journal。Reviewer 必須與 author 不同，核准必須引用精確 proposal hash。

核准只追加 `runtime_toolchain` binding；RP 維持 `handing-off`，原產品提案、覆核、核准及 handoff intent 全部保留。之後用原 handoff action ID 重送 `handoff`，Gate 重新驗證原核准的 immutable Start artifact；successor 後續須重跑全部必要 checks，不沿用舊 evidence。pending repair 期間不得開始 successor、移植成果或完成 handoff。`replan status` 在待審查時提示獨立審查，在待核准時提示取得精確 proposal hash 的人工核准；核准或拒絕後恢復該階段的下一步提示。拒絕不會自動授權仍留在工作區的工具差異。

## 相容性與恢復

Gate 實際重播來源／successor／RP 事件、驗證來源及候選契約、比對有效契約、載入 workflow 並驗證原快照、產品與 Worker。這些檢查證明保存資料可由新版工具讀取與驗證；不能自動證明任意 validator 語義修改安全，仍須獨立覆核與使用者核准。

工具接軌包含新增的 RP 事件型別。尚未實作此協定的舊版 Gate 不支援讀取這些事件；不能在接軌後直接退回舊 Gate。中斷後先查看 replan status，再以原 action ID 與相同輸入重試；不得刪除事件、手改 state 或覆寫原 snapshot。
