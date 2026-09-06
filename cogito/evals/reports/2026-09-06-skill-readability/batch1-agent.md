# Cogito 正向閱讀模擬：Package 選擇 A–E

這是唯讀推演，沒有建立 run、修改專案、執行 checks、取得真實核准或建立 commits。只讀目前 Skill 與相關 references；沒有讀 Git 歷史、既有報告、程式實作或其他 Agent 討論。本檔是唯一產出。

## 實際讀取順序

1. `cogito/SKILL.md` 全文：啟動、不變量、類型選擇、操作路由與 finalization。
2. `cogito/references/package-authoring.md` 全文：先讀「選擇 Package 類型」，再看完整 Package、核准前修訂與核准後流程，判斷 A–D。
3. `cogito/references/planning-revisions.md` 全文：D 的 Mini 不可 same-run 升級及原 run 處理。
4. `cogito/references/human-acceptance.md` 全文：E 的局部修正、結案授權、三輪額度及 Maintenance 例外。
5. `cogito/references/grilling-workflow.md` 全文：C 與 D 新 feature 的需求準備。
6. `cogito/references/shared-understanding-contract.md` 全文：C 與 D 摘要確認要求。
7. `cogito/references/stage-commits.md` 全文：A/B 的單一 Package checkpoint、C 的三個 checkpoints 與 Maintenance commit 起算點。
8. `cogito/references/execution-policy.md` 全文：A/B/C 後續執行與 E review、快照、final commit。
9. `cogito/references/runtime-interface.md` 全文：後續 Gate 操作、證據、review 與 D cancel 路由。
10. `cogito/references/dispositions.md` 全文：D 停止／取消與無成果處置。

步驟 3–4 與 5–8 各在同一讀取命令中依上述順序輸出。沒有讀 Spec／Plan templates，因尚未產出候選文件；沒有讀 RP reference，因 E 目前仍局部、D 尚未核准且按 Mini 取消／新 run 處理，未進入 RP。

## A：整理既有 API 文件連結與索引

**建議 `kind=documentation`，走 Mini Package。** 題目明確只重組已有語意，但仍須從來源與預期 diff 證明沒有改產品語意，不能僅依使用者一句話當成完成的技術查證。

文件與 checkpoints：只準備 Mini Package 及其來源、允許路徑、reference/hash checks、政策與必要契約資料；不建立 Slice、Spec、Plan，也不走 Shared Understanding／Boundary checkpoint。核准後只建立 Package checkpoint。執行與結案仍有 Agent Results、runner evidence、Result／Project Graph 及 Gate 產生的 delivery summary。

核准與 reviewer：`$cogito` 是 invocation；須先呈現通過 `prepare-package` 的候選並取得明確 Package approval，然後保存 checkpoint、通過 Start Gate 才修改。Documentation **必須不同於 Implementer 的獨立 Reviewer**，不能因都是文件就豁免。沒有適用 human predicates 或 hotspot 時最終可自動結案；目前未有其證據。

接下來幾步（均為擬議）：讀適用專案政策與 Git 狀態 → 查詢／建立 documentation run 並以實際 `next_action` 為準 → 查證來源、列有限允許路徑及可客觀驗證的 reference/hash checks → 準備與驗證 Mini 候選 → 呈現候選請使用者核准 → Package checkpoint → Start Gate → lease／實作、controlled checks、獨立 review、整合及最後驗證／finalization。

還缺的 evidence：實際來源清單與 hashes、目前失效連結與索引範圍、既有語意的依據、產品語意未變的 diff 分析、checks 定義與正式結果、政策／Git baseline、候選 hash、真實核准、實際獨立 reviewer 與其 Results。不得提前宣稱適用條件或 checks 已通過。

## B：改寫內部 helper 結構且語意不變

**建議暫定 `kind=maintenance`，走 Mini Package。** 題目提供了很強的低風險條件，仍須證明不改 Acceptance、公開契約、資料模型、安全、依賴與 Slice 責任，有限路徑、相關 deterministic checks 足以覆蓋，且可在目前 checkout 以單一產品 commit 交付。

文件與 checkpoints：Mini Package，不建立 Slice／Spec／Plan、摘要或 Boundary checkpoint；只有 Package checkpoint。`maintenance_guards` 保存凍結宣告，但 true 不是語意等价證明。Start Gate 後所有產品工作與修正先留工作樹快照；唯一 final commit 一併保存已驗證內容、Result／Graph 及全部適用 Amendment trailers。準備 Package checkpoint 不計入 Start Gate 後單一產品 commit 限制。

核准與 reviewer：仍需明確 Package approval 及 Start Gate。一般開發 review **僅在客觀條件有來源／diff／checks 支持、獲核准且 Gate 檢查通過時可豁免**；不能直接因「有 tests」宣告豁免。人工驗收退回修正不適用此豁免。

接下來幾步：讀政策／Git、取得實際 next → 查 helper 及呼叫端、契約／測試範圍 → 填具證據的 Maintenance Mini → prepare-package → 使用者核准 → Package checkpoint、Start Gate → 取得 lease 後才修改 → controlled checks、完整增量 changed_paths 與 Implementer Result → Gate 推導可否豁免 review → 最後驗證、依 human applicability 路由 → 唯一 final commit／finalize。

還缺的 evidence：helper 與 caller 範圍、所有不變條件的來源與 diff、有限路徑清單、現有 deterministic tests 的實際覆蓋力、baseline／index／工作樹快照、controlled evidence、真實候選核准與 Gate review decision。若發現語意歧義，不能勉強保留 Mini；已建立 run 的處理同 D。

## C：日期篩選漏掉最後一天

**建議 `kind=correction`，完整 Development Package。** 新 run 的修 bug 改變目前產品可見行為；不能僅因像單一運算子變更就稱 Maintenance。也不能套用 E 的既有人工驗收局部修正流程。

文件與 checkpoints：Grilling 足夠後產出固定結構 Shared Understanding，摘要在 `docs/cogito/shared-understanding/<run-id>-r<round>.md`，確認後獨立 checkpoint；Boundary 建立 provisional Slice IDs，Gate 接受後獨立 checkpoint；再建立 Slice／Spec／Plan、完整 Package、來源 hashes、atomic tasks／DAG 與 checks。Spec／Plan 路徑分別採 `docs/specs/<ID>/<ID>-<name>-spec.md`、`docs/plans/<ID>/<ID>-<name>-plan.md`。Package approval 後提交 Package checkpoint 才 Start Gate。

核准與 reviewer：先請使用者確認完整摘要（確認也授權該摘要 commit），Boundary pass 不是開發授權；只有明確 Package approval 是開發核准。Coordinator 必須派 1–3 個專用 branch/worktree Worker；小工作可一個。實作由不同 Agent 逐 task 獨立 review。每 Task 包含程式、相關 regression tests 與必要文件並獨立 commit；至少一個 required integration check。正常初版 Package 沒有額外 planning reviewer 要求；後續候選修訂才觸發獨立 planning review。

接下來幾步：讀政策／Git、init correction／next → 查目前日期篩選與 tests，先區分已驗證現況和期望行為 → 只問無法由專案確認的產品決策（例如日期含上界、時間戳精度／時區，若來源已足則不重問）→ ready 時呈現摘要並等待確認 → 摘要 checkpoint → Boundary → Boundary checkpoint → 讀 templates 並準備完整 Package → 核准後 checkpoint／Start Gate。

還缺的 evidence：重現案例、日期欄位型態／時區／既有契約、預期 end-day 行為與邊界 cases、受影響 callers、允許路徑與 checks、摘要確認、Boundary 結果、候選核准、Worker／reviewer Results、runner evidence。尚不能保證 single-slice，但可將其作為查證後的候選。

## D：preparing 的 Maintenance 增加 CSV export

**停止原 Mini 準備；新增 CSV 功能建議新 `kind=feature` 完整 Package。** 原 `kind=maintenance` 不可 same-run 改 kind，也不能以 `planning begin level=requirements` 冒充 Mini 升級。Mini 只支援範圍不變的 plan 修訂。

文件與 checkpoints：保留原 run 的既有記錄／草稿與快照。明確處理原 run 取消，使用 DP 保存停止、現場與成果處置；若確實無 Implementer Result／Amendment／RP 成果且 baseline/index/tree 未改，可提出 `retain`、`no_change_evidence.no_work=true` 的無成果方案，不捏造工作。新 feature run 依 C 的摘要、Boundary、Slice／Spec／Plan、Package 三階段 checkpoints 準備。

核准與 reviewer：新需求不是新 Package approval，也不能虛構取消授權。需把「結束舊 maintenance，保留記錄，改以 feature 準備」的具體處理說清楚；若上下文未明確授權取消，原 run 停止推進並取得該決定。DP 方案需不同於 author 的 reviewer、使用者方案審核；無成果處置完成仍要求真實的 `human-accepted`。新 feature 仍需摘要確認、Package approval 及實作獨立 review。

接下來幾步：讀 planning-revisions → 確認 run 目前實際 next、輪次、baseline 及是否有候選／成果 → 記錄 CSV 使 Mini 不再適用，停止原流程 → 讀 dispositions，準備明確取消／保存方案，按已有或新取得的取消授權走 begin/stop → 證實無成果後 propose/review/approve/complete 適用 DP → 以正確 kind 開新 run 並釐清 CSV 範圍／驗收，最後才取得新 Package 核准。

還缺的 evidence：原 run 實際 journal、尚未工作之證據、HEAD/index/content tree、使用者是否要 CSV 取代或連同 helper 交付、取消授權、DP review／approval／acceptance，及新功能欄位、格式、資料量、權限等真正相關的需求證據。若有成果不能用 no_work shortcut。所有操作仍只是推演。

## E：Maintenance 人工驗收退回、範圍內局部修正

**保留原 `kind=maintenance`，走同一 run 的 human-correction 路徑。** 不重新準備 Mini、不以新 Package 取代既有核准；不因單純人工退回就走 RP。

文件與 checkpoints：保存原文 feedback 與逐項 triage 理由，append-only Technical Amendment 加新修正 task／必要 checks；保留每輪 lease、Implementer Result、完成快照、正式 post-integration evidence、Reviewer Result。沒有新摘要／Boundary／Package checkpoints。Maintenance HEAD 保持 Start Gate HEAD，`human complete.commit_id` 用該 HEAD，產品內容留未提交快照直到唯一 final commit。

核准與 reviewer：清楚的核准範圍內局部修正可在既有契約與回饋下進行，不等待無關「是否驗完」回答。**每輪必須由不同 Implementer 的獨立 Reviewer 審查，Maintenance 豁免完全不適用。** 題目只有 rejection 要求修正，故 `acceptance_complete=false`、`close_after_fixes=false`；修好後回 `awaiting-human`，不能推定其他部分已接受。只有本批使用者明確「其餘已接受，修好可結案」且證據有效才轉 finalizing。

接下來幾步：next／核对既有交付與正式 evidence → human feedback 保存原意 → human triage 全部明確 local → amend 新 task → human start（同 run human_corrections 額度加一）→ lease／實作／Implementer Result → human complete（工作樹快照）→ run-check 執行全部適用 post-integration checks → human verify → 不同 Agent 逐 task Reviewer Results → human review → 預設回 awaiting-human。使用者真正接受後才 finalizing／唯一 final commit／finalize。

還缺的 evidence：具體回饋、局部與核准範圍的 diff／理由、既有 effective contract、交付 HEAD／tree、已使用的人工作業輪數、本輪 Amendment、lease／Results／runner checks／review；尚沒有條件式結案授權。最多三次成功 human start，換 Agent／resume／新批次不重設。途中影響擴大立即升級 RP，不能等額度耗盡。

## 閱讀阻力與回頭點

1. 類型選擇順暢：SKILL 直接導向 Package Authoring，該表與 bullets 能明確區分 A/B/C，並明示 Documentation review 與 Maintenance 人工退回 review 例外。
2. SKILL 的「狀態主路徑」只畫完整 Package，初看容易替 Mini 加摘要／Boundary；回看 Package Authoring 與 Stage Commits 後可明確排除。不是矛盾，但 Mini 分支的例外要記住。
3. D 在 planning-revisions 已足以判斷不能升級，但未在該段直接鏈到 dispositions；需沿 Runtime Interface 的 cancel 說明再找到 DP，閱讀跨度最大。preparing、尚無候選仍不應誤套一般 planning begin 範例。
4. D 無實作取消的後續不是「cancel + init」即可完整描述；dispositions 才揭露無成果 retain 仍需獨立 review、方案 approval、human-accepted。取消授權不能从新功能請求自動偽造，因此模擬需保留真正缺失的使用者決定。
5. Maintenance 單一 commit 與準備 checkpoint 表面像衝突；Stage Commits／Execution Policy 明確說從 Start Gate HEAD 起算，能解開。Documentation 沒有同樣 single_commit 強制，不能把兩種 Mini 的提交要求混用。
6. Execution Policy 曾要求 Maintenance changed_paths 完整列出產品路徑，Runtime Interface 又細化新 lease 為每 task 起始快照增量。可理解為既有總體範圍與新 lease 分工，但表述需小心；本模擬採 Runtime Interface 的具體新 lease 規則並保留 checkout 累積範圍驗證。
7. Gate 及 contracts 沒有實際執行，所有 next／guard／review verdict 均是將來需驗證，不是模擬已通過。以上可評估閱讀引導，不能用作 executable-contract 或 behavioral eval 通過證明。

## 更新後局部複核

僅重讀更新的三處相關段落及必要相鄰文字：`SKILL.md` 完整／Mini 狀態路徑、`package-authoring.md` Maintenance 條件、`planning-revisions.md` Mini 超出範圍處理。A–E 的類型、checkpoint、核准與 review 決策均維持原結論。

- 原阻力 2 已解決：主路徑明確標為完整 Development Package，Mini 另列從 preparing 到候選核准、不經摘要／Boundary 的路徑。
- 原阻力 5 已解決：Maintenance 類型條件直接指出單一交付 commit 從 Start Gate HEAD 之後起算，首次類型判斷便能排除與準備 checkpoint 的表面衝突。
- 原阻力 3 已解決：Mini 不可升級段落直接鏈到成果處置，D 不再需要繞 Runtime Interface 才找到 DP。

本次未重展開下游流程，未執行 Gate 或 automated checks；這是同一閱讀者的局部跟進複核，不是新的盲測。原先對 D 真實取消授權／無成果 evidence，以及 changed_paths 表述的觀察未被這三項修改影響。
