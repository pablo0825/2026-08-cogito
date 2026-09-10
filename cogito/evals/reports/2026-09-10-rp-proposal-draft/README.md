# RP 草稿與提示連動

日期：2026-09-10。交付版本：4.6.0。Repository 維護，未建立產品 Cogito Run。上一輪 4.5.0 派工／Reviewer 提示修改仍在工作目錄中，未與本次提交或發布。

## 修改前的連動評估

使用者要求先確認整段操作可用，而不只增加 Package 複製函式。盤查後限定以下範圍：

| 連動位置 | 處理方式 |
| --- | --- |
| 凍結候選與 planning 覆核 | 使用既有 candidate snapshot、Package hash、文件檢查及 `_planning_approval_binding`；不從任意外部檔案或未覆核修訂產生提案草稿 |
| 來源／successor `next`、RP `status` | 在需要新提案且具備候選時回 `proposal_draft.operations`；命令綁定當時候選 hash，未備齊時回 blocker |
| 草稿落地 | 新增 `replan draft --replan-id <ID> --candidate-hash <hash>`，直接建立可編輯檔案，免除從工具輸出重抄 Package 的步驟 |
| 編輯與提交 | 草稿原樣包含候選 Package、所有 source task IDs；回 `required_inputs` 與使用該檔的既有 propose 命令 |
| 提交後導航 | successor planning 修訂分支原本提交後仍提示準備 RP 提案；現在有效提案進入 reviewing／awaiting-approval 後導回原 RP 審查／核准 |
| 中斷與過時資料 | draft 每次建立不同檔案，不覆蓋已填判斷；hash 改變拒絕舊命令；正式 propose 的原 input／action ID 恢復不變 |
| runtime、事件與承接 | 原 runtime 已允許 RP drafts，不擴白名單；不改 proposal／review／approval 事件、hash、Start artifact 或 Atomic 承接契約 |

## 行為與邊界

草稿位於 `.cogito/replans/<RP-ID>/drafts/proposal-<unique>.json`。Agent 補作者、六項 differences，以及每筆 source task 的 target、disposition、validation、reason。工具不預填人為判斷或核准。

draft 不追加提案事件、不建立 Start artifact、不執行成果移植。Package、文件、來源及承接可行性仍由既有 propose／review／approve／handoff 規則驗證，產生草稿不等於提案能通過。

有有效 RP 提案正在覆核／核准时，不主動建議重建；工具接軌尚待覆核／核准或已進入交接時不產新草稿。Historical candidate snapshot 缺失不補造，依既有 Package preparation 準備。

Atomic successor 的 work 仍須由 Agent 明確填 omit、null target、rerun；來源是既有非 Atomic 時也不自動跨越此規則。draft 目錄含 symlink 先拒絕寫入。寫檔失敗回明確錯誤，說明未提交提案，保留原檔並重跑 draft；propose 失敗則依原輸入與 action ID 恢復。

新增向後相容的 CLI 能力，版本升 MINOR 至 4.6.0。未新增 Gate、流程狀態、核准種類或自動批准，未更動舊輸入格式。

## 實際自動驗證

共 **31 個不同測試通過**：

| 測試檔 | 數量 | 範圍 |
| --- | ---: | --- |
| `test_replan_draft.py` | 9 | source/successor next、status、真 CLI draft→propose→review/approve→handoff、相同 action replay、重複草稿、過時 hash／Package、planning review、提交後導航、Atomic omit、缺 snapshot、文件漂移、symlink、寫檔故障與恢復 |
| `test_replan_store.py` | 13 | 既有來源保護、精確核准與交接恢復 |
| `test_planning_rp_interop.py` | 2 | successor 修訂與 RP 核准互通／durable approval |
| `test_replan_state.py` | 7 | RP 狀態與既有事件投影 |

其中 30 個以一個 focused suite 通過；最後新增的 CLI 寫檔錯誤提示單獨測試通過，未重跑無關測試。初版修訂測試誤用已內含「完成覆核」斷言的 fixture，已改為逐步建立情境；未將該失敗算成成功。

mypy 1.20.2 設定範圍 27 source files、`git diff --check` 通過。Git／程序測試在允許 `ps` 查詢測試程序身分的環境執行，使用隔離暫存 repositories。

## 獨立檢查與限制

獨立唯讀審查找出 successor 提交後的提示漏接、draft symlink 與 Atomic 規則文字精度問題；修正後複查未發現剩餘必修問題。Focused reading simulation 涵蓋正常草稿、有效審查中、planning 未覆核與 propose 失敗恢復；屬合成閱讀決策，不是使用者驗收或真實產品 Agent 效率測量。

未跑完整 regression、CI、skill 格式驗證，未量測 token／耗時。尚未 commit 或 push。
