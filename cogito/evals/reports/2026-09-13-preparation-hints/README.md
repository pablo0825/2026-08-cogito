# 準備階段提示與連動檢查

本次交付：4.10.0。目標是減少 Agent 回找資料、組裝命令與重複提交；保留原有判斷、核准及 guard。

## 連動範圍

| 入口 | 修改與保留條件 |
|---|---|
| 摘要 ready／confirmation | 提供已知 hash、文件引用與本輪 payload；確認值仍由實際使用者決定。文件漂移停止提示；舊資料只有 hash 不補造原文。 |
| Boundary／Package | 提供已確認摘要、Boundary 與既有命令；Agent 仍判斷範圍、evidence、Mini 適用性、任務及測試。 |
| Package 呈現／核准 | `planning candidate --candidate-hash` 匯出 Gate 保存的精確 JSON；拒絕過期 hash、不同內容的既有檔案與 symlink。匯出不增加核准事件。 |
| 規劃修訂 | 提供 candidate／compare／review 入口；未完成獨立覆核時不提供 approve。原文件、hash、覆核及核准 guard 不變。 |
| checkpoint | prepare 回傳精確 Git argv；next 以 record 原驗證判斷是否直接補登記。保留無關 staging，拒絕 HEAD 漂移；沒有自動 commit。 |
| RP successor | 提供準備及規劃覆核提示，候選完成後回 RP proposal；不提供一般 Package approve，不跳過 RP 核准及 handoff。 |
| Skill／操作文件 | 優先使用 next 的引用與命令，仍讀適用判斷規則與格式；遇例外才回查操作小節。 |

不新增 workflow 狀態、事件或第二套驗證契約。checkpoint 僅抽出原 record 驗證供查詢共用。

## 自動化結果

以下為本次實際執行的相關測試，共 79 個通過；重跑不重複計數：

| unittest discovery pattern | 數量 |
|---|---:|
| `test_preparation*.py` | 17 |
| `test_planning*.py` | 27 |
| `test_shared_rev*.py` | 9 |
| `test_stage_commits.py` | 12 |
| `test_replan_draft.py` | 9 |
| `test_run_queries.py` | 5 |

新測試在臨時 Git 專案實際執行 next 提供的 CLI／Git argv：摘要發布與確認、三次 checkpoint、Boundary、Package 匯出與核准，直到 Start。另檢查候選修訂、舊命令拒絕、既有匯出保護、Mini、歷史缺少快照、無關 HEAD 及摘要文件漂移。RP 草稿測試補查候選匯出、準備入口、覆核命令，以及提交 RP proposal 後不再出現一般操作。

最初部分 RP／checkpoint 測試因沙箱禁止 `ps` 在 fixture 初始化停止；取得測試權限後，受影響的三組測試全部重跑通過，未以 mock 移除程序檢查。

Configured mypy：27 個 source files 通過。`git diff --check` 通過。未跑全套 regression 或 CI；本次選擇準備、修訂、儲存恢復、RP 與查詢的受影響測試。

## 文件閱讀自查

逐項修改並核對 Runtime Interface、Package Authoring、Stage Commits、Grilling Workflow 與 SKILL 的閱讀路由。以下為主 Agent 的合成閱讀推演，不是獨立 Agent 評估或使用者驗收：

- 收到 ready 命令但需求未清楚：依 Grilling readiness 規則繼續問答，不立即發布摘要。
- 等待摘要確認：從 preparation_context 讀取精確版本、向使用者呈現，收到確認才填 confirmed；不把 operations 當作可整批執行的清單。
- 等待 Package 核准：匯出候選、讀取引用文件並呈現；planning revision 先 compare／review，RP 候選則走 proposal。
- checkpoint 中斷：尚未 commit 時 prepare；已有合格 commit 時直接 record，重送沿用原 action ID；無關 commit 出現 blocker，不重做提交。
- 回查文件：讀判斷規則、契約格式及例外；不再為尋找已提供的 CLI 參數重讀操作範例。

Skill 格式驗證曾執行 `quick_validate.py cogito`，但目前 Python 缺少 PyYAML，未完成，不能列為通過。此側邊對話禁止子 Agent，因此沒有獨立審查或 Agent 行為評估。未測量 token，不聲稱所有階段都不必閱讀文件。
