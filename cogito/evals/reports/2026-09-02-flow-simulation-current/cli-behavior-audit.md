# 公開 CLI 與 Agent 行為規格查核

開始時間：2026-09-02 15:42:16 UTC。完成於 15:47 UTC，約 5 分鐘，符合單一子代理 10 分鐘上限。全程沒有修改產品程式、沒有建立子代理；所有 Git 寫入均在隔離的 `/private/tmp` repo。主 repo 只新增本報告、腳本與證據。

## 本次實際執行結果

使用公開 `cogito_gate.py` subprocess 介面，沒有直接呼叫 runtime 寫 event。最終一輪共 110 個命令，其中 68 個是 Gate CLI 呼叫。33 個 exit 2 是刻意測試的拒絕案例，不計作 33 個故障。

1. **Maintenance 完整流程成功**：真實 Python 檔案將內部 `value` 改為 `renamed_value`，前後輸出均為 `3\n`。Mini Package → 模擬核准 → Start Gate → lease/running → Implementer Result → complete → controlled check → verify → Maintenance review exemption → integrate 基線 → post controlled check → finalizing → final commit → accepted → report。檔案、Package、Graph、Result 同一 final commit 完成，Start HEAD 後只有 **1 個 commit**。正式 checks 執行 Python 子程序驗證輸出，並非空跑 `print('ok')`。沒有建立 Slice、Spec、Plan。
2. **未核准不可 start**：`awaiting-package-approval` 嘗試 start 回傳 exit 2，之後正常核准才能執行。
3. **最新 non-object event 修正通過獨立重驗**：array/null/string/number/boolean × 第一行/第二行 × status/next，共 **20 個案例**均 exit 2、stderr JSON `ok:false`、包含 object 診斷、沒有 traceback；受損 events、state cache、Git index bytes 均完全未改動。這裡故意寫壞的是拋棄式測試 repo 的 event，沒有修改主 repo 或正常流程歷史。
4. **Shared Understanding 在確認前可修復**：先傳入 hash=123，再以新 action ID 修改為合法 SHA-256，確認時指出最新 hash，可正常進入 boundary-analysis。
5. **發現一類新的輸入驗證卡關**，有兩個可重現入口，詳見下節。

最終成功模擬 repo：`/private/tmp/cogito-cli-behavior-azy6p4us/mini-complete`。
Final commit：`4c36e23a7843b0656b00600a090f2ef68f3f454e`。
證據檔案：[cli-behavior-summary.json](cli-behavior-summary.json)、[全部 argv/stdout/stderr](cli-behavior-commands.jsonl)、[可重跑腳本](cli-behavior-probe.py)。脚本每次建立新 `/tmp` repo；重跑會覆寫這份報告旁的 summary/transcript，因此要先複製輸出目錄。最初開發 probe 時曾錯選排序後的旧 evidence，Gate 正確拒絕 `evidence predates the current verification cycle`；已修正為明確使用新產生的 evidence。這是測試腳本問題，不是產品故障，最終 transcript 是完整成功重跑。

## 新發現：P2，核准前型別錯誤被凍結，確認後無法在原 run 合法修正

`cogito_workflow.py:55` 對 `shared_understanding_hash` 只判非空，`:58` 對 Boundary evidence 只判 truthy。因此公開 CLI 接受以下資料，並追加合法 hash 鏈的 events：

```sh
python3 cogito/scripts/cogito_gate.py --repo <tmp-repo> init --run-id DEV-bad-shared-hash --kind feature
python3 cogito/scripts/cogito_gate.py --repo <tmp-repo> transition --run-id DEV-bad-shared-hash --event shared-understanding-ready --payload-json '{"shared_understanding_hash":123}' --action-id shared-1
python3 cogito/scripts/cogito_gate.py --repo <tmp-repo> transition --run-id DEV-bad-shared-hash --event shared-understanding-confirmed --payload-json '{"confirmed":true}' --action-id simulated-confirmation-1
python3 cogito/scripts/cogito_gate.py --repo <tmp-repo> transition --run-id DEV-bad-shared-hash --event boundary-complete --payload-json '{"decision":"single-slice","evidence":["bounded"]}' --action-id boundary-1
```

結果成功進入 `package-preparing`，其中 `shared_understanding_hash` 是數值 `123`。第二個獨立 repo 使用合法 hash，但 Boundary 為 `{"decision":"single-slice","evidence":"not-an-array"}`，同樣成功進入 `package-preparing`。

實際後果：

| 輸入 | 忠實帶入已記錄值的 Package | 修正型別後的 Package |
| --- | --- | --- |
| hash=123 | `shared_understanding.hash must be a non-empty string without NUL bytes` | `Package is not bound to the confirmed Shared Understanding` |
| evidence 是字串 | `boundary.evidence must be a non-empty array` | `Package is not bound to the recorded Boundary Gate result` |

`prepare_package()` 在 `cogito_run_store.py:184` 驗證 Package 型別，`:190–193` 又要求等於已確認/已記錄資料，形成此卡關。從 `package-preparing` 重送修正的 shared-understanding-ready 或 boundary-complete 都因非法狀態拒絕。

已另外實跑 **block → resume**：兩個 repo 都回到原 `package-preparing`，同一份已修正 Package 仍拒絕。`resume --target preparing` 是不支援的 CLI 參數。`resume_gate()` 的 `:691` 固定取 `blocked_from`，無任意回退能力。

範圍要精確：hash 仍在 `awaiting-shared-confirmation` 時可以合法修正，本次已成功验证；問題是確認後／Boundary 已完成後的型別不一致。這不是繞過核准或假驗證成功，後續 Package Gate 仍 fail closed；但原 run 無現成正式修正路徑，可能需要保留現場、取得取消/重建 run 決策，不能宣稱資料永遠無法救回，也不能直接改 event 或 state cache。

建議：在首次 shared-understanding-ready／boundary-complete 寫 event 前，重用 Package 的 hash 與 Boundary 型別契約，至少拒絕非 SHA-256 hash、非非空字串陣列 evidence。若要支持已存在錯誤歷史，另設明確核准前修訂事件與重新確認語意；不要放寬 Package matching，也不要讓 resume 任意跳步。

## 操作文件與行為評測的邊界

- SKILL 的「Gate next_action 指定 reference 與輸入」實際由 SKILL 路由表補充：目前 `next` 只回 action/state、少量 ready tasks/hash，不返回 reference 路徑或完整 payload 範本。讀 SKILL + references + Python executable contract 能繼續，這是易用性缺口，未觀察到獨立 runtime 故障。
- Runtime Interface 所稱敏感 verdict 由 CLI 推导，不能理解成外部人類認證。`approve`、`human-approve` 是 Coordinator 在獲得授權後呼叫的入口；CLI 呼叫成功本身不是使用者真的說過「核准」的證明。Task/Reviewer 不同字串 ID 也不是實際不同 Agent 的證明。此次所有 approval 與角色 ID 明確是合成資料。
- `README.md` 明確指出 14 個 evals 尚無執行器或已評分 Agent 行為結果。以下是逐項證據分類，**0/14 在本工作軌被宣告為正式 Agent 行為 eval 通過**；CLI 完整流程與 unit test 都不能替代自然語言行為評分。

| Eval | 本工作軌實際證據／相關實作 | 未覆蓋或限制 |
| --- | --- | --- |
| 1 不主動啟動 | 靜態讀 SKILL invocation 規則 | 未向獨立受測 Agent 發送普通修 bug 請求並評分 |
| 2 shared 確認不是核准 | 真 CLI shared/confirmation 流程停在 Boundary/Package，未開始實作 | 自然語言解讀未評分；型別卡關見上 |
| 3 單一 Package 核准 | Mini 流程正式 approval event 一次，未核准 start 被拒，後续無額外 human gate | 真人文字核准與 Feature Package 互動未測 |
| 4 Technical correction | 閱讀 amendment/retry policy 與相關既有測試 | 本 CLI 軌沒有 amendment，不宣告此情境通過 |
| 5 語意變更停止 | 文件規定 Coordinator 對契約漂移 block | 未對「5 次變 3 次」做真正 Agent 語意辨識評分 |
| 6 三 Worker DAG | 靜態確認 scheduler/lease 上限及 dependency 規則 | 本軌是單 Maintenance task；沒有實際三 Agent Feature wave |
| 7 獨立 review loop | 靜態確認 lease/result ID 比對 | 本軌 Maintenance 豁免；沒有實際獨立 Reviewer 或 review-fix |
| 8 resume 預算持續 | 真 CLI block/resume 保留來源狀態 | 本軌沒有耗盡三輪 correction；相關 unit test 不算行為評分 |
| 9 controlled runner | 真 CLI pre/post checks 的 evidence 與結果綁定 | 本軌未另跑超時；未評分 Agent 對失敗 evidence 的敘述 |
| 10 自動 finalization | 真 CLI 無 human predicate，final commit 後 accepted，report 有 commit ID | 這是 Mini 的 runtime 路徑，不是 Feature + 真 Reviewer 完整行為證據 |
| 11 凍結 human gate | 靜態查 workflow、post-verify、human-approve | 本軌未執行；既知 expectation 與 merge 順序矛盾仍在 |
| 12 legacy lazy adoption | 閱讀 project-bootstrap/Package 來源語意相關規則 | 未實際操作舊專案；未驗證無關舊文件保留 |
| 13 Maintenance | 真 CLI rename、輸出 check、同 engine、無 Slice/Spec/Plan、單 commit | 無真人 Package 核准；語意等價判斷只是本次具體小例子，非自動證明 |
| 14 crash idempotency | 閱讀 Runtime Interface crash 規約與原始請求規則 | 本軌未注入 integrate commit/event crash，不宣告 Agent recovery 通過 |

Eval #11 的 `Does not merge before approval`（`evals.json:80`）仍與正式 `integrating → post-integration-verification → awaiting-human` 順序矛盾。這是先前報告已知事項，**不是本次新發現**。應釐清「不可在 Package approval 前 merge」或改為「Human Gate approval 前不可 finalize/accepted」。

## 交接

新 finding 是「核准前 payload 型別驗證不一致造成确认後卡關」，兩入口共用同一問題類型。最小重現、完整 transcript、正常流程、故障與修復前後 case repo 均已保存。未修改主 repo 產品程式；沒有背景程序或待交接執行中的子代理。主代理可將本軌證據與其他軌 full Feature/Documentation/correction 測試合併，但應維持 runtime 模擬與真正 Agent 行為評測的區分。
