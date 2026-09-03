# Package 核准前的規劃修訂

本流程適用於 Package 尚未核准、實作尚未開始的修訂。採用同一個 run 的規劃輪次：需求、Boundary、候選文件快照、覆核與核准全部追加至 `.cogito/runs/<run-id>/events.jsonl`，不建立獨立修訂單，也不覆寫歷史。`state.json` 是可重建的快取。Package 核准後的契約變更改用 [Replanning](replanning.md)，不能以規劃輪次修改已核准契約。

## 影響判斷與確認

使用者提出「這次只做篩選，統計與匯出留到下次」時，Coordinator 先分析影響，說明改動與沿用理由。功能、範圍、驗收條件改變，或意思不明時，先釐清並確認新需求；只改實作安排，可直接準備新版，最後仍由使用者核准 Package。確認需求只表示理解正確，不授權開發。

確認要進入修訂後，先 `planning begin` 保存來源並立即停用舊候選核准，再改寫相關文件；不要等新方案完成才停用舊版。begin 本身不確認新需求。選擇的層級決定合法起點與可沿用內容：

| `level` | 情境 | 新一輪起點與必要處理 |
|---|---|---|
| `plan` | 功能、邊界、Spec、驗收不變，只調整實作安排 | 完整 Package 回到 `package-preparing`；Mini 回到 `preparing`。需求、Boundary、Spec、驗收必須沿用；Slice／路徑／source registry 不得變更。 |
| `boundary` | 需求、驗收不變，重分 Slice、責任或路徑邊界 | 回到 `boundary-analysis`，需求與驗收沿用，Boundary 重做；重新檢查 Spec／Plan／DAG。 |
| `requirements` | 功能、範圍、驗收改變，或需求仍需釐清 | 回到 `preparing`，重新準備並確認 Shared Understanding，再重做 Boundary 與受影響文件。 |

每次 impact 必須涵蓋 `requirements`、`boundary`、`spec`、`plan`、`dag`、`acceptance` 六項，逐項記錄 `reuse`／`redo` 及理由。無法確定不受影響時重新檢查，不能直接宣告沿用。程式會比對部分結構與 hash 是否符合 reuse 宣告；內容是否符合使用者意思、API 或驗收語意是否改變，仍由 Coordinator 與獨立 Reviewer 判斷。hash 只證明版本身分，不會判讀文字意義。

Mini Package 本版只支援 `plan` 層級且範圍不變的修訂。若 Maintenance／Documentation 發現需要改產品需求或邊界，不可在原 `kind` 下冒充完整 Feature 流程；停止並明確處理原 run 的取消與建立正確類型的新 run。尚未提供 same-run Mini 升級為 Feature 的操作。

## 建立新一輪

所有不同於目前候選的 Package 都先 begin，包括只改 Plan／Package 的修訂。相同候選重送可沿用既有操作規則；不同輸入不得使用同一 `action_id`。begin 的 `round` 是目前輪次，`candidate_hash` 是來源候選的 `package_hash`；成功後輪次遞增、candidate 清空，舊候選不能再核准。

以下是第 1 輪三項功能縮減為第 2 輪只做篩選的 begin payload；hash 請替換成 Gate 回傳的實值：

```json
{
  "round": 1,
  "candidate_hash": "<來源候選的64位hash>",
  "author_id": "planner-agent",
  "reason": "使用者要求本次只做篩選，統計與匯出延後。",
  "level": "requirements",
  "impact": {
    "requirements": {"disposition": "redo", "reason": "Included與Excluded改變。"},
    "boundary": {"disposition": "redo", "reason": "三個Slice縮減為一個。"},
    "spec": {"disposition": "redo", "reason": "重新確認只做篩選的規格。"},
    "plan": {"disposition": "redo", "reason": "移除統計與匯出的實作安排。"},
    "dag": {"disposition": "redo", "reason": "刪除延後功能的任務與依賴。"},
    "acceptance": {"disposition": "redo", "reason": "本次驗收只涵蓋篩選。"}
  }
}
```

```sh
python3 cogito/scripts/cogito_gate.py --repo <repo> planning begin --run-id <run-id> --input <begin.json> --action-id planning-begin-2
```

begin 需在原 Package delivery branch 執行，來源文件必須符合已保存快照。先保存來源再編輯新文件；可使用版本分開的文件路徑，方便保留與撤回。每個候選保存 Package JSON 及引用文件的精確 bytes，放在同一次候選事件中；沿用文件也綁入新版快照。

`requirements` 輪次的 `shared-understanding-ready` payload 必須帶 `planning_round`、新的 `shared_understanding_hash`，以及 `document: {"path": "...", "hash": "..."}`，Gate 檢查實際文件並保存 bytes。新的 `shared-understanding-confirmed` 帶相同 `planning_round`、最新 hash 與 `confirmed: true`，只可在使用者確實確認後提交。`boundary-complete` 也必須帶目前 `planning_round`。新版 Package 本身帶整數 `planning_round`，經原本的 `prepare-package` 驗證。

如果一輪尚未產生候選，使用者又改變方向，可以再次 `planning begin` 開下一輪。查詢目前輪次與來源候選 hash，記錄新的影響判斷；未完成輪次仍留在事件中，不將它當成可核准候選。未完成輪次只能維持或提高影響層級，不能把尚未落成候選的需求變更改稱為 plan／boundary 而跳過處理；要降低層級，先完成目前候選，或經使用者決定撤回修訂。若已產生候選，下一輪以該候選為來源。

## 比較、覆核與核准

```sh
python3 cogito/scripts/cogito_gate.py --repo <repo> planning history --run-id <run-id>
python3 cogito/scripts/cogito_gate.py --repo <repo> planning compare --run-id <run-id> --from-round 1 --to-round 2
```

history 提供保存的 Package 與文件內容；UTF-8 文件輸出解碼後的 `text`，其他內容保留 Base64。compare 使用保存的快照，列出變更欄位的完整 before／after 與文件 diff，不以目前磁碟檔案取代舊版本。尚無候選的未完成輪次不能當作候選比較。

Coordinator 向使用者呈現修改原因、新舊範圍、邊界、驗收與成本差異，以及哪些內容沿用／重做。另一位 Agent 必須先讀完整新舊內容，檢查一致性、影響判斷及沿用依據。覆核 payload：

```json
{
  "round": 2,
  "proposal_hash": "<Gate目前planning.proposal_hash>",
  "reviewer_id": "independent-reviewer",
  "findings": [],
  "assessment": {
    "consistency": "說明需求、Boundary、Spec／Plan、DAG及驗收如何相符。",
    "impact": "說明本次修改已完整反映，以及影響層級是否正確。",
    "reuse": "說明各項沿用內容仍適用的依據。"
  }
}
```

```sh
python3 cogito/scripts/cogito_gate.py --repo <repo> planning review --run-id <run-id> --input <review.json> --action-id planning-review-2
python3 cogito/scripts/cogito_gate.py --repo <repo> approve --run-id <run-id> --package <package-v2.json> --action-id approve-v2
```

第二條命令只在使用者明確核准所呈現的新版後執行。`proposal_hash` 綁定輪次、完整候選快照與修訂請求；Reviewer ID 不得等於 author ID，未解決 findings 不可進入核准。ID 不同是結構檢查，Coordinator 仍需確保實際獨立覆核。核准事件綁定同一 proposal；候選、文件或輪次變動後不得沿用舊覆核。覆核後要修改候選，先開始下一輪，再準備並覆核。

若此 run 是有效 `RP-*` 的 successor，它在 Package 核准前也可使用規劃輪次。planning review 完成不代表 RP 已核准：將最新候選放入 RP 提案，依 RP 的 propose／review／approve 完成使用者授權與後續 handoff，不得用普通 `approve` 繞過 RP 限制。RP status 若回報 `proposal_stale`，表示舊提案不再對應 successor 候選，需重新 propose／review／approve，不能核准舊提案。

## 撤回與中斷恢復

使用者不接受新版時保持修訂狀態，不能自動恢復舊候選。明確決定撤回後，提交 `planning withdraw`：

```json
{"round": 2, "authorized": true, "reason": "使用者明確撤回本次修訂，要求恢復原方案等待核准。"}
```

```sh
python3 cogito/scripts/cogito_gate.py --repo <repo> planning withdraw --run-id <run-id> --input <withdraw.json> --action-id planning-withdraw-2
python3 cogito/scripts/cogito_gate.py --repo <repo> planning recover --run-id <run-id>
```

withdraw 檢查來源文件、政策與 delivery 狀態仍有效才恢復來源候選；不自動覆寫檔案、不抹除本輪事件，也不代表核准開發。若曾在同一路徑修改來源檔，必須先核對並處理原檔漂移，不能僅設 `authorized: true` 強行恢復。

recover 從同一 journal 還原目前輪次及下一步，檢查已綁定文件、候選與 delivery 狀態。確認過且仍有效的需求不重複詢問；未完成步驟繼續準備。分支、HEAD 或已綁定文件不符時停止並回報，Coordinator 釐清矛盾後再繼續；錯誤不等於自動寫入 `blocked`。尚未保存為正式快照的草稿內容，仍需 Coordinator 檢查，不能因 recover 成功就宣稱所有語意一致。事件已落盤而快取寫入失敗時，以相同 `action_id` 與原輸入重送，不追加重複事件。

## 舊資料限制

歷史初版可能只有 candidate hash，或文件當時不在磁碟而未形成完整快照。begin 需提供 `source_package`，其 hash 必須符合記錄，並提供所有對應 hash 的原文件，才能補存來源候選快照，供 history／compare 查閱。找不到原文件時停止，不能以現在的新內容倒填舊版。歷史共識若只有 hash 而沒有文件路徑，只能如實保留 hash；不假造原文。新的 requirements 輪次則必須提供可驗證的摘要文件。

## 各輪階段提交

啟用階段提交的 run，每輪重新確認摘要、通過 Boundary 後都各自 commit；尚有 checkpoint 未完成時不能開始下一輪或撤回。只有 Gate 登記的 checkpoint commits 可推進 planning 的 delivery HEAD；其他 HEAD 變動仍視為漂移。撤回保留已建立的 commits，不 reset 或 amend 歷史；恢復的正式文件隨後續核准的 Package checkpoint 保存。流程見 [Stage Commits](stage-commits.md)。
