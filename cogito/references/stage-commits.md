# Stage Commits

每個已完成且確認的準備階段都建立獨立本地 Git commit，不等到實作或結案才保存。階段文件提交不授權產品實作，也不授權 push。

| 階段完成條件 | 提交內容 | 下一步 |
|---|---|---|
| 使用者確認 Shared Understanding | 確認版本的摘要原文、ready／confirmation 事件與文件 hash | Boundary analysis |
| Gate 接受 `boundary-complete` | Boundary decision、evidence 與事件紀錄 | Package 草擬 |
| 使用者核准 Package | 凍結 Package、Spec／Plan、`adopted`／`updated` 來源、摘要引用、Project Graph 與核准事件 | Start Gate |

Grilling 的持久產物是已確認的 Shared Understanding；不另將整段聊天、未決問答、未確認草稿或整個 `.cogito/` 提交。Mini Package 沒有摘要／Boundary 階段，只建立 Package checkpoint。Maintenance 的單一實作 commit 從此後的 Start Gate HEAD 起算。

## 操作

一般 run 的 `init` 預設啟用階段提交。建立 run 前在指定 delivery branch 上確認目前 HEAD，保留使用者既有變更；後續每個 checkpoint 必須直接接在上一個 checkpoint（第一個則是 init HEAD）之後。

完成階段轉移後查詢 `next`。收到 `commit-stage-artifacts` 時：

1. 執行 `checkpoint prepare --run-id <run-id>`。Gate 核對確認時保存的精確 bytes，產生 `docs/cogito/checkpoints/<run-id>/<sequence>-<stage>.json`，回傳 `paths`、`base_commit`、`branch` 與 `commit_message`。
2. 檢查清單內的 diff。只 stage 回傳的精確路徑，並用 `git commit --only` 指定相同路徑，避免把原本已 staged 的無關變更帶入。路徑以獨立且正確引用的 argv 傳入，不使用 `git add .` 或 `git commit -a`。若 Git ignore 排除了正式文件，先查明規則；確認是本次應保存的正式文件後，可僅對該精確路徑使用 `git add -f`。不默默略過、擴張提交範圍或關閉 checkpoint guard。
3. 取得完整 commit ID，執行 `checkpoint record --run-id <run-id> --commit-id <commit-id> --action-id <stable-action-id>`。Gate 驗證 delivery branch、唯一 parent、精確提交範圍、所有文件 bytes 與 regular-file mode；成功後追加 `stage-committed` 事件。
4. 再查詢 `next` 繼續。不需要為同一批已確認／核准的階段文件重複詢問 commit 授權。

命令均使用 `python3 cogito/scripts/cogito_gate.py --repo <repo>` 前綴。`checkpoint prepare` 只寫不可變 manifest，不修改 Git index 或建立 commit；commit 由 Coordinator 執行，Gate 負責驗證。Package 與 Spec／Plan 必須有完整、hash 相符的文件快照；Package 必須引用該 run 已確認摘要的同一路徑與 hash。摘要確認後不要為了更新 footer 改寫原文。

## 失敗與恢復

未完成 checkpoint 時，Gate 保留階段狀態並拒絕後續準備、核准與執行；仍可依原 guard 登錄 block、resume 或使用者授權的取消。`prepare` 可重送；若文件改變或 manifest 已存在但不同，停止並查明差異，不覆寫確認內容。

Git commit 已成功而 receipt 未成功時，先檢查 HEAD 與事件，沿用既有 commit ID、原 action ID 重送 `checkpoint record`。事件已保存而 cache 失敗也使用同樣方式恢復；不再次 commit、不 amend、不 reset。若 commit 夾帶無關變更或 HEAD 已漂移，保留現場並處理 Git 差異，不把失敗當作已完成階段。

RP successor 仍依 [Replanning](replanning.md) 保存 frozen delivery 快照與既有 handoff 流程；本次階段提交不套用於 RP，以保留撤回後恢復 source 的能力。CLI 偵測有效 RP successor 時預設維持舊協定，明確要求 `--stage-commits` 會在初始化前拒絕，不改動原 run。

## 實作到結案（方案 A）

| 階段 | 提交方式 | 原因 |
|---|---|---|
| Worker 完成一項完整修改 | 將相關程式與對應測試放進同一個有意義的 commit；較大的任務可拆成數個完整修改 | 方便審查與回復，避免程式與保障其行為的測試分離 |
| Slice 整合 | 保留實際 worker commits，由 Gate 登記整合 HEAD；可 fast-forward | 保存真正交付的版本，不為了湊階段數建立空 commit |
| 驗證或獨立 review | 結果先記錄在本地事件與 evidence；若需要改程式，另建合法修正 commit | 單純檢查不會改變產品版本；修正則必須可追蹤 |
| 人工驗收 | 退回、再次驗證與確認記錄於事件；一般修正各自 commit | 使用者尚未接受時不能先結案；有明確條件式授權時依 Human Acceptance 規則處理 |
| 正式結案 | 最後一個 commit 保存 Result、Project Graph 與完整 `delivery_summary` | 將主要版本、檢查、審查與人工驗收歷程一併保存至 Git |

Maintenance 仍採 Start Gate 後單一產品 commit：任務與修正先保存工作樹快照，最後連同 Result／Graph 提交。摘要以基線、content tree 表示這些未提交成果，不捏造中途 commit。

進入 `finalizing` 後執行 `delivery-summary --run-id <run-id>`，將輸出 JSON 原樣放入 Result 的 `delivery_summary` 欄位，再提交 Result 與 Project Graph。摘要由 Gate 從實際事件產生，包含準備 checkpoint、implementer 的任務與版本、整合版本、controlled checks、獨立 reviewer，以及人工退回／修正／接受紀錄。產生摘要本身不代表已結案；`finalize` 仍須核對已提交 Result、事件與驗證內容。

啟用 `stage_commits` 的 run 缺少摘要、漏掉階段、改動 commit 或使用過期驗收摘要時，Gate 拒絕結案。完整檢查輸出與回饋原文仍留在本地 `.cogito`；Git 中保存的是摘要與證據引用，不提供完整事件還原，也不另建 audit branch。Result 不含自身 commit ID；通過 finalization 後，由結案報告附上實際 final commit。

## 相容性

沒有 `stage_commits` 的歷史 `run-created` 事件仍按舊流程重播，不回填確認原文、修改已核准 JSON／hash 或重寫舊 commits。CLI 的 `--no-stage-commits` 僅供舊協定相容性使用；正常 skill 流程不使用此選項。Python `RunStore.create()` 的既有呼叫預設維持舊協定，新的整合呼叫需明確傳入 `stage_commits=True`。新增 receipt 事件保存 commit ID，manifest 不內嵌包含自身的 commit ID。
