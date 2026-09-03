# 人工驗收退回

人工驗收退回使用同一 run 的專用流程；沿用既有 Technical Amendment、task lease／Agent Result、controlled runner、獨立審查與 finalization。使用者以自然語言提出回饋，Coordinator 記錄原意及分類理由，不要求使用者操作 JSON。

## 分類與結案授權

| 回饋 | 處理 |
|---|---|
| 改動局部、影響明確，例如錯字、按鈕位置或單一運算子錯誤 | 原 run 的人工修正 |
| 改變操作流程，或需要較大範圍的邏輯調整 | 整理 RP，核准變更方案後再實作 |
| 修正途中發現共用邏輯等影響擴大 | 立即停止推進並升級 RP，不等三輪用完 |
| 同批混合局部修正與變更 | 整批進 RP；只有使用者明確要求分批交付時才延後部分項目 |
| 「其餘都接受，這些修好即可」 | 保存本批條件式結案授權；修正、驗證及獨立審查通過後直接 finalizing |
| 只說「這裡改一下」，或明確尚未驗完 | 先修正，通過後回 awaiting-human，不推定其餘已接受 |

局部與變更的分類由 Coordinator 根據修改目的、影響及既有契約作成可追溯判斷；Gate 驗證完整分類與合法路由，不提供語意安全證明。修改行數或是否修改文件都不是唯一分界。已核准邊界內的 UI 局部調整，可同步更新合法 Spec／Plan；不得改寫 immutable Package、擴大路徑或藉此變更 Acceptance、公開行為契約、安全、資料或 DAG 邊界。位置調整即使需要同步更新畫面規格，也可依已確認的局部修正處理：保留原 Package，另存本輪文件新舊內容；超出局部呈現調整的產品契約變更仍走 RP。

`acceptance_complete` 與 `close_after_fixes` 都預設 false。兩者只能依使用者明確表達記錄；後者不能在前者為 false 時成立。授權綁定當時交付 HEAD、content tree、effective contract hash 及本批回饋 hash，只涵蓋本批有效項目。新增回饋使用新批次與新授權；轉 RP 後不得沿用舊授權結案。

修正進行中收到新回饋，也以 `human feedback` 保存新的批次。Gate 暫存該批並立即撤銷本輪自動結案授權；既有局部修正完成後回到 awaiting-human，`next` 提供待處理的原始回饋，Coordinator 依序用相同內容登錄與分類，不重問已說明的內容。尚有待處理回饋時，普通 human-approve 也不能結案。新增回饋若已明確涉及變更或影響擴大，Coordinator 立即升級 RP，不等原修正做完。

## 狀態與三輪額度

```text
awaiting-human
  -> human-feedback-triage
  -> human-correction
  -> human-correction-verifying
  -> human-correction-reviewing
  -> awaiting-human | finalizing -> accepted
```

`triage` 逐項分類為 `local`、`change` 或 `clarify`。未延後項目包含 change 時整批走 RP；需要釐清時先釐清修改目標並更新分類，不開始修正。不要為了判斷使用者是否驗完而停止已明確的局部修正：未表態就保留等待人工驗收的預設。

人工修正使用獨立 `human_corrections` 額度，同一 run 累計最多三輪，與開發 correction、review/fix 分開。每次成功 `human start` 開始實際修正時計一輪；登錄回饋、分類、相同 action 重送都不計次。分批回饋、換 Agent、resume 或重建快取不重設計數。驗證或審查未通過，仍留在對應階段；下一輪須先追加新的 Amendment 及明確修正 task，再重新 start，不能沿用已消耗的 Amendment。每輪重新完成 Implementer Result、正式 checks 與本輪獨立 Reviewer Result，不重用上一輪通過資料；人工退回即使是 Maintenance 也需要獨立審查。

三輪仍未通過時，停止自動修正並整理失敗原因、嘗試紀錄及下一步建議，交使用者決定。第三輪 verify 收到本輪正式失敗 evidence，或 review 有本輪未解決 findings 時，Gate 記錄 exhausted 並進 blocked；超額 start 也會阻擋。資料格式／綁定錯誤仍回報錯誤，不假造正式檢查失敗。Coordinator 不再繼續派工。普通 resume 不提供新額度。若額度已用完而使用者再提出局部回饋，也必須停止並回報，不能換批次取得三輪。

## CLI 範例

下例假設已在 `awaiting-human`，交付內容仍與正式 post-integration evidence 一致。每個 JSON 存成對應 UTF-8 檔案；每個有副作用的操作使用穩定 action ID，相同請求重送沿用原 ID。實際 task、Amendment、check 與 reviewer 輸入沿用 [Runtime Interface](runtime-interface.md) 及其 executable contracts。

使用者說：「其餘都接受，日期少算最後一天修好就結案。」`feedback.json`：

```json
{
  "id": "HF-001",
  "message": "其餘都接受，日期少算最後一天修好就結案。",
  "items": [{"id": "HI-001", "description": "日期篩選漏掉最後一天"}],
  "acceptance_complete": true,
  "close_after_fixes": true
}
```

```sh
python3 cogito/scripts/cogito_gate.py --repo <root> human feedback \
  --run-id <ID> --input feedback.json --action-id human-feedback-001
```

確認只是局部比較運算子問題後，`triage.json`：

```json
{
  "feedback_id": "HF-001",
  "assessments": [{
    "id": "HI-001",
    "disposition": "local",
    "reason": "漏用包含上界的比較運算子；影響限於既有篩選條件，不改流程與契約"
  }]
}
```

```sh
python3 cogito/scripts/cogito_gate.py --repo <root> human triage \
  --run-id <ID> --input triage.json --action-id human-triage-001
```

先用既有 `amend` 追加 `TA-001` 的修正任務及必要 checks，再以 `start.json` 開始：

```json
{"amendment_id": "TA-001"}
```

```sh
python3 cogito/scripts/cogito_gate.py --repo <root> human start \
  --run-id <ID> --input start.json --action-id human-start-001
```

修正任務在 delivery checkout 串行執行，完成派工及 Implementer Result 後，`complete.json`：

```json
{
  "feedback_id": "HF-001",
  "amendment_id": "TA-001",
  "commit_id": "<current-delivery-HEAD>",
  "resolved_item_ids": ["HI-001"],
  "summary": "已修正日期上界並補上最後一天的回歸檢查"
}
```

`commit_id` 必須換成實際 HEAD；一般 kind 的修正 commit 含 `Cogito-Amendment: TA-001` trailer。Maintenance 保持 Start Gate HEAD，提交未提交內容快照，直到唯一 final commit 才提交產品內容及全部 trailers。

```sh
python3 cogito/scripts/cogito_gate.py --repo <root> human complete \
  --run-id <ID> --input complete.json --action-id human-complete-001
```

若本輪需要同步更新 Package 引用的 Spec／Plan，可在 completion 加入 `document_updates: [{"path": "docs/spec.md", "reason": "配合已確認的按鈕位置調整"}]`。Gate 保存各文件新舊 bytes/hash；不能改 Package 或宣告其他路徑。若文件在最後 Implementer Result 之後提交，中間 commit 只能修改已宣告文件，最後修正 commit 仍需 Amendment trailer。所有文件更新都必須在本輪驗證前完成，Reviewer 需檢查文件與局部調整相符。

在當前 delivery 內容上使用 `run-check` 執行全部適用 post-integration checks；以每份 evidence 的實際路徑重複傳入 `--evidence`：

```sh
python3 cogito/scripts/cogito_gate.py --repo <root> human verify \
  --run-id <ID> --evidence <evidence-path> --action-id human-verify-001
```

驗證後指派不同 Agent 逐修正 task 審查，登錄本輪 Reviewer Results，再讓 Gate 推導結果：

```sh
python3 cogito/scripts/cogito_gate.py --repo <root> human review \
  --run-id <ID> --action-id human-review-001
```

上述授權、內容、checks 與 review 都有效時進 `finalizing`，仍須完成既有 final commit／`finalize` 才算 accepted。若 feedback 未指定兩個結案欄位，完全相同的修正流程會回 `awaiting-human`。明確接受目前版本時使用 `human-approve`；不能拿歷史核准代替本次有效授權。

## 混合回饋與升級

例如本批有錯字 `HI-001`、按鈕位置 `HI-002`、自動查詢 `HI-003`，預設評估為 local、local、change，整批進 RP。若使用者明確說「先修前兩項，自動查詢下次做」，可記錄：

```json
{
  "feedback_id": "HF-002",
  "assessments": [
    {"id": "HI-001", "disposition": "local", "reason": "按鈕錯字"},
    {"id": "HI-002", "disposition": "local", "reason": "核准範圍內的位置調整"},
    {"id": "HI-003", "disposition": "change", "reason": "自動查詢改變操作流程"}
  ],
  "deferred_item_ids": ["HI-003"],
  "split_authorized": true,
  "split_reason": "使用者明確要求先交付前兩項，自動查詢留待後續"
}
```

這只授權分批，不自行授權結案；仍依本批 acceptance_complete／close_after_fixes 判斷。後續項目保留在事件歷史，不假裝已解決，也不自動啟動未核准的變更。

修正中發現其實影響多個頁面的共用日期邏輯時，以 `escalate.json` 記錄：

```json
{"reason": "日期處理位於共用模組，影響其他頁面；停止局部修正，改走 RP 分析與核准"}
```

```sh
python3 cogito/scripts/cogito_gate.py --repo <root> human escalate \
  --run-id <ID> --input escalate.json --action-id human-escalate-001
```

此操作登錄 blocked 並停用局部修正路徑；它不會替 Coordinator 終止外部 Worker 或程序。Coordinator 立即停止新派工，以實際執行介面停止／收尾現有執行者，再依 [Replanning](replanning.md) 登錄 executor、stop receipts 及現場快照。不得把 blocked 當成所有程序已停止的證據。普通 resume 不能解除已升級的人工作業；RP 在保存、影響分析、獨立覆核及使用者核准後，才交給 successor。

源自人工驗收的 RP 必須將重新人工驗收要求交接到 successor，即使新版 Package 沒有適用的 HI／HA／hotspot predicate，也不能跳過。方案核准只表示同意怎麼改；變更實作、測試與獨立審查完成後，仍回人工驗收。舊 run、舊授權及事件保持不變。

## 恢復與能力界線

以 `next`／`resume` 和 append-only 事件恢復階段、當前回饋及 run 累計輪數，不能手改 state 或計數器。每個 Gate 會核對適用的內容與證據綁定；修正後追加未驗證內容不能靠舊 checks、舊 review 或舊人工核准結案。舊 run 沒有條件式結案授權時不推定有授權，已結案歷史也不改寫。

Gate 能驗證分類是否完整、是否具備分批／結案宣告、額度、狀態、工作完成及證據綁定；不能證明自然語言確實授權、分類在產品語意上正確，或任意外部程序已停止。Coordinator 必須忠實保存使用者原意、檢查實際差異並維護真實執行者對應，不能用 JSON boolean 取代這些責任。

## 取消與撤回變更

人工驗收期間取消、放棄 RP 或改為保留／恢復成果，使用 [成果處置](dispositions.md)。原任務取消不代表功能已移除；Agent 分析並提案，使用者審核後由關聯任務執行。明確撤回變更要求且原成果可恢復時，重新驗證後回人工驗收，既有直接結案授權不沿用；修正額度不重設。
