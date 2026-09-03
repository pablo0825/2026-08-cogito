# 取消與成果處置

`DP-*` 是獨立於原 run 與 RP 的成果處置紀錄。原任務取消與成果處置完成分別呈現；取消不代表已移除功能，也不代表保留成果已通過驗收。

## 已確認的決策

1. 使用者取消後，先停止執行者，保存 committed、staged、working-tree 成果，再取消原任務並釋放其執行佔用。未整合成果不再自動整合。
2. Agent 分析已整合內容、相依影響與必要驗證，提出移除方案，經獨立覆核後由使用者審核。修改由另開的正式 run 執行。
3. 等待審核期間，會修改或依賴待處置內容的任務暫停；已知不受影響的任務可繼續。Agent 必須說明範圍及語意相依，不能只依檔案路徑宣告無影響。
4. 否決移除方案後，原任務仍取消，Agent 修訂方案，受影響工作繼續暫停。
5. 改為保留時先檢查完整性，提出保留及必要補修方案。補修使用關聯任務並完成必要驗收。
6. 放棄 RP 後先暫停。只有明確撤回原變更要求，且原契約與成果可恢復，才恢復原任務。已完成的人工來源重新驗證後回人工驗收。
7. 新方案已產生修改時，先保存現況，再提出恢復方案，由使用者審核後執行與驗證；不改寫歷史。

## 狀態與權責

```text
stopping -> analyzing -> reviewing -> awaiting-approval -> executing -> completed
                         ^                |
                         |--- analyzing <-| reject
executing -> pausing -> analyzing -> reviewing ...
```

`begin` 先保存停止意圖並限制派工；`stop` 確認 registry 內執行者均已停止，連續比對快照，再以可重送步驟完成取消及 Graph 釋放。外部 Agent 的停止憑據使用既有 `replan register-executor`／`executor-receipt` 介面，憑據不是任意的 `stopped: true`。

從 RP 建立 DP 時，預設保留原 run 暫停；快照涵蓋 source、successor、尚未完成登錄的 transfer worktrees。RP 轉為 `disposition` 終態，歷史 transfer receipts 保留。原 RP 不再繼續 handoff。已核准或部分執行的方案撤回也使用此入口。

原 run、已放棄的 successor、被新方案取代的 follow-up 不能藉普通 `resume` 繼續。恢復原契約由專用 DP Gate 驗證；原 run 已取消時必須另開任務。恢復不重設任何修正額度。

## 操作

下列 `--authorized`／`--human-accepted` 僅能在使用者實際授權或驗收後提交。使用者只說停止，不代表核准 Agent 尚未提出的移除方案。

```sh
python3 cogito/scripts/cogito_gate.py --repo <root> disposition begin \
  --disposition-id DP-export --source-run DEV-export \
  --reason '使用者取消匯出功能，請分析成果處置' --action-id begin-1
python3 cogito/scripts/cogito_gate.py --repo <root> disposition stop \
  --disposition-id DP-export --action-id stop-1
```

RP 撤回在 `begin` 增加 `--replan-id RP-export`。既有一般 `transition --event cancel` 會建立可查詢的 DP；`replan abandon --disposition cancel-source` 也走同一停止與保存機制。

移除、補修或恢復先用正常的 preparation Gates 準備新 run 的 Package，再提出方案：

```json
{
  "action": "remove",
  "author_id": "coordinator",
  "summary": "移除匯出按鈕及 API，保留其他訂單功能",
  "impact": {
    "paths": ["src/export/**", "src/orders/toolbar.ts"],
    "slice_ids": ["FS-export"],
    "reason": "工具列與自動報表依賴匯出 API"
  },
  "acceptance": "匯出入口與 API 已移除，其他訂單及報表行為正常",
  "followup_run_id": "DEV-remove-export",
  "followup_package_hash": "<新候選 Package 的實際 hash>"
}
```

`action` 為 `remove`、`retain`、`restore` 或 `resume`。Reviewer 必須不同於 author；review 綁定方案 hash，包含非空 `assessment`，且 `findings` 必須已實際解決。

```sh
python3 cogito/scripts/cogito_gate.py --repo <root> disposition propose \
  --disposition-id DP-export --input proposal.json --action-id propose-1
python3 cogito/scripts/cogito_gate.py --repo <root> disposition review \
  --disposition-id DP-export --input review.json --action-id review-1
python3 cogito/scripts/cogito_gate.py --repo <root> disposition approve \
  --disposition-id DP-export --proposal-hash <實際方案hash> --authorized --action-id approve-1
```

核准前會驗證 follow-up 候選、文件、policy、baseline 及交付目錄可啟動；尚有保存的未提交修改時，先 `release`，不先寫入無法執行的核准。核准 DP 只授權該版本的處置方案；執行仍需以正常 `approve` Gate 核准同一份 follow-up Package，再依正常流程啟動、驗證、覆核、人工驗收與結案。所有 DP follow-up 強制人工驗收。只有它實際 `accepted`，DP `complete` 才解除待處置範圍。

`reject --reason ...` 保留否決紀錄、作廢當前覆核並回分析；新的 `propose` 保存新版本。已核准的方案改變時先 `pause --reason ...`，停止並保存舊 follow-up，取消其剩餘工作，再提出新方案。歷次影響範圍保留，不能藉縮小新版 impact 提早解除限制。

## 無修改保留與恢復原契約

無修改保留限先前已驗證的交付成果。方案需為 `retain`、沒有 follow-up，並提供 `no_change_evidence`，包含 `head`、`content_tree`、原 run ledger 中完整的 `evidence_paths`。Gate 比對已提交產品內容、保存快照、有效契約與正式 evidence。核准方案後，使用者實際驗收才執行 `complete --human-accepted`。尚未提交的 Maintenance 成果仍需關聯任務完成正式交付。

恢復暫停的原契約使用 `resume` 方案，包含：

```json
"withdrawal_authorization": {
  "authorized": true,
  "reason": "使用者明確撤回將三步操作簡化為一步的要求"
}
```

Gate 在核准前檢查恢復可行性。人工來源若原契約／內容已改變，必須提出 `restore` follow-up；可直接恢復時回到 `post-integration-verification`，重跑 checks 後再次人工驗收，不直接結案。若等待期間其他任務佔用交付分支，先等它完成；不清除他人的 Graph 佔用。

尚未開始實作、沒有 Implementer Result／Amendment／RP 成果時，可以提出 `retain` 的無成果處置方案：`no_change_evidence` 額外包含 `no_work: true`，`evidence_paths` 為空，HEAD／tree 必須符合保存的原 baseline。Gate 比對所有保存及當前的產品內容與 index；任何未登錄修改或新 commit 都拒絕。經獨立覆核、方案審核與 `complete --human-accepted` 才完成，無須捏造修正任務。

## 保存、釋放與重送

快照在取消前釘選到 `refs/cogito/dispositions/<DP>/<snapshot_hash>/...`，分別保存 HEAD、index、content tree；可用 `git archive <ref>` 匯出，或 `git show <ref>:<path>` 查看。manifest 與逐路徑釋放紀錄在 `.cogito/dispositions/<DP>/archives/`。

Maintenance 等流程可能在 delivery checkout 留有未提交產品修改。停止保存後、準備及核准後續方案前，可執行 `disposition release --disposition-id ... --action-id ...`，將已保存且屬於處置範圍的 dirty 路徑還原至保存的 HEAD。此操作保留 archive、原 worker worktrees、Graph 更新及範圍外修改；不移動 HEAD。存在未知漂移即拒絕覆寫。已整合內容仍留在 HEAD，必須由審核後的移除／恢復任務修改。

狀態與歷史使用 `disposition status`、`disposition history`。中斷重送保持相同 action ID 與輸入；變更決定先走合法 pause／修訂，不能改寫舊決定或刪除 marker。`run next` 顯示關聯 DP 與待辦事項。

Project Graph 的 `active_run_id` 仍只代表目前執行者；DP 的範圍限制另由權威事件推導，核准、派工、受控檢查與整合前重新檢查。paths、Slice lineage 與傳遞相依提供機械保護，語意影響仍由 Agent 分析及 Reviewer 覆核。停止或影響未知時保守暫停；這次不擴張為多個 run 同時執行。
