# Replanning 契約缺口模擬：Contract Audit

## 結論

**問題存在，而且核心敘述成立。** Cogito 能停止流程推進、保存事件與工作證據，卻沒有把「使用者同意的新 API／資料模型／邊界」轉成新版核准契約並續做的合法狀態路徑。本輪只做隔離模擬，未修改產品、未 commit；fixture 中的核准全是 `/tmp` disposable repository 的合成測試資料。

來源版本：見 `contract-summary.json` 的 `source_revision`。可重跑：

```sh
python3 cogito/evals/reports/2026-09-03-replanning-audit/contract-probe.py
```

## 模擬情境與實際限制

探測以真實 CLI 建立 Feature run，核准 Package，完成兩項工作、controlled verification，進入 `reviewing`，並先登錄一項 task review。此後模擬 C 發現需要新的共用 API：

1. 用擴大 `approved_paths` 的新版 Package 呼叫 `prepare-package`：拒絕，因 `reviewing` 不能準備 Package。
2. 使用者即使同意，以新版 Package 呼叫 `approve`：拒絕，因 `reviewing` 不能核准 Package。
3. 嘗試回到 Shared Understanding 或重做 Boundary：都被狀態機拒絕。
4. Amendment 嘗試加入 `approved_paths` 或替換 `boundary`：以 forbidden fields 拒絕；新增工作／path fix 指向 `shared/api.py`：以超出 approved paths 拒絕。
5. `block` 成功，並完整保存 tasks、agent results、evidence、Package hash 與 effective contract hash。
6. `resume --target package-preparing` 根本沒有這個 CLI 參數；通用 transition 也不能偽造 resume target。合法 `resume` 固定讀 `blocked_from`，因此只回到原先的 `reviewing`，Package hash 不變。

使用者例子有一項需要精確修正：**同一個 execution wave 中，C 已正式進到全 run 的 `verifying`／`reviewing`，而 B、D 仍是 `running`，現有狀態機不允許。** `implementation-complete` 的 Gate guard 要求沒有 active task、沒有 dispatchable task，才會把共用 run 由 `executing` 推到 `verifying`；task update 也只有在執行／修正狀態合法。因此實際可達的相近情況是：

- B、C、D 都還在 `executing`，C 的個別工作過程先發現契約問題；或
- B、D 屬先前 wave，已 review／integrate；C 在後續 wave 的 verification/review 才發現問題。

這項全域 gate 限制沒有消除 replanning 缺口，只是表示不能把每位 Worker 描述成各自獨立處於 run-level `reviewing`。

## Runtime 能保證與不能保證的邊界

Runtime 有機械防線：approved Package 以 hash 與唯讀 canonical file 凍結；Package revision 僅在 approval 前合法；Technical Amendment 是 append-only overlay，只能加入 checks/tasks 或記錄已核准路徑內的 path fixes；既有 Slice dependencies 不能改；terminal run 不能再 amendment 或 transition；block 會保留權威歷史。

但 API／資料模型是否改變是**語意判斷**。Runtime 目前不解析 `reason` 的產品語意。探測提交以下 Amendment：

```json
{
  "id": "TA-semantic-probe",
  "reason": "Change public API output from list to object and replace data model",
  "path_fixes": ["src/a.txt"]
}
```

因路徑仍在核准範圍，CLI 接受並更新 effective contract hash。這不表示該變更符合政策；相反地，它證明「公開 API／資料模型不得用 Amendment 改」依賴 Coordinator 正確辨識並停止，不能宣稱 runtime 能單靠文字或 code semantics 自動拒絕。若新 API 恰好放在既有 approved path 裡，路徑驗證本身攔不住它。

## 與提問逐項對照

| 提問 | 實測判定 |
|---|---|
| 已核准 Package 不可修改／更換 | **確認**；重新 prepare/approve 均拒絕，canonical bytes 未變 |
| Technical Amendment 無法合法擴張 path、Boundary、既有 Slice 契約 | **確認**；結構／路徑規則拒絕 |
| API／資料模型語意變更能否由 runtime 自動識別 | **不能**；Coordinator 必須判讀，本輪反例被接受 |
| `blocked` 保存現場 | **確認**；tasks/results/evidence/hashes 都保留 |
| `blocked` 自動停止 Worker/process | **沒有此效果**；reference 亦明訂 Coordinator 另行停止或收尾；本子探測未重複主代理的 live subprocess 實驗 |
| `resume` 可選擇退回重新釐清／Boundary／Package | **否**；只能回 `blocked_from` |
| 只讓 C 重核准、B/D 自動前進 | **否**；state 是 run-level，沒有 Slice replanning/reapproval state |
| 舊契約結束、新契約承接成果 | **沒有正式操作或事件模型**；現有選項只剩原契約 resume 或授權後 cancel，再另開 run 並人工承接 |
| `accepted` 可重新開啟 | **否**；`accepted`/`cancelled` 是終態 |

因此提議中的目標流程，在「保存並 block」以前後各有部分能力，但缺少中間的 impact set、契約版本／supersession、再次授權、證據失效與成果承接規則，無法完整執行。

## 證據

- `contract-probe.log`：16 項公開 CLI 操作結果；預期拒絕都驗證 events 與 canonical Package 未變。
- `contract-summary.json`：結構化 observation、來源 revision 與 fixture 說明。
- `contract-events.jsonl`：隔離 run 的權威事件歷史（含 block/resume 及語意反例 Amendment）。
- `contract-revisions-tests.log`：Package revision 3 tests passed。
- `contract-amendment-tests.log`：Amendment dependency/scope 7 tests passed。
- `contract-block-tests.log`：block/recovery 3 tests passed。

本輪沒有模擬完整三 Slice Git 整合生命週期；契約缺口的肯定結論不依賴該擴充場景，因為已在合法 `reviewing` 狀態直接證明新版 Package、回退 Boundary、選擇性 resume 均無路徑。三 Slice active Worker 與 subprocess 是否會被 block 停止，由主模擬另存證據。
