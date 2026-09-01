# Controlled Parallel Workflow

只適用於 blueprint 明確設定 `Execution Mode: controlled-parallel`。本模式建立在 Development Package 的 Preparation Authority、Autonomy Budget、獨立 review 與 Final Approval 邊界上，但以一個明確核准的 Parallel Wave 取代單一 Execution Candidate。讀取 Development Package workflow 時，其中要求「恰好一個 Execution Candidate」與只核准該候選的規則，在本模式由 Wave 的 1–3 個 exact Execution Candidates 規則覆蓋；每個候選仍必須有自己的完整 package。缺少此 mode 時不得建立 worktree、Worker branch 或平行執行多個 Slice。

第二階段只允許隔離的 implementation／test Worker 平行工作；相容性分析、Wave Approval、review、integration 與需要使用者決定的項目都經單一序列門閥。Rolling Adoption 與 Maintenance 不進入 Parallel Wave。

## 固定限制

- 同時最多 `3` 個 Worker；較低的 project／host 限制優先。
- 每個 Worker 綁定一個已核准 Slice、一個專用 worktree 與一個專用 branch。
- Worker 只能修改該 Slice 核准 Plan 的內部實作與測試；不得改變已核准行為、公開契約、資料模型、安全邊界、Slice 責任、依賴或順序。
- Worker 不得修改其他 Slice 的 Spec／Plan／Verification，不得自行 merge、rebase、cherry-pick、push 或整合其他 Worker 的結果。
- 同一時間恰好一個 Slice 可以進入 Independent Review／Integration Gate；其他完成結果保持 queued。
- Final Approval 仍逐 Slice 由使用者確認，不因低風險或平行執行而自動接受。

## Parallel Readiness Analysis

Grilling 與 Boundary Gate 依 Development Package workflow 為每個候選準備 drafts 後，先建立 Parallel Readiness Analysis。分析使用核准文件、實際 repository inspection 與可驗證的 dependency graph，不以檔名猜測獨立性。

每個候選必須列出：

- Slice ID、使用者結果、Depends On 與預計執行順序。
- exact worktree／branch identity。
- Read Set：依賴的 contracts、shared modules、schema、configuration 與生成物。
- Write Set：預計修改與建立的 exact files／internal areas。
- Integration Surface：共享型別、API、event、state、database、build／dependency 與高扇出模組。
- 預計 checks、成本／時間級別與 review 複雜度。
- 可能的 merge 順序、衝突點、處理方式、最壞影響與 rollback。

相容性只使用下列分類：

1. `independent`：Write Set 不重疊，Integration Surface 沒有未排序的 contract 或 shared-state 依賴，可直接放入同一 Wave。
2. `coordinated-overlap`：有已知重疊，但可在不改產品 contract 的前提下提出 exact merge order、owner 與 conflict resolution；必須在摘要醒目揭露，由使用者明確核准後才可放入 Wave。
3. `shared-predecessor-required`：兩個以上 Slice 需要相同共用變更，或平行修改會形成隱性 contract；先提出一個可獨立審查的共用前置 Slice 或指定既有前置 Slice。不得靜默建立、核准或執行該 Slice；其核准並整合完成後，才重新分析後續 Wave。
4. `serial-only`：耦合、風險或未知資訊不足以證明安全，從 Wave 排除並依序處理。

新增或改變共用前置 Slice、切割、依賴、順序、Write Set owner 或 conflict strategy 都是 orchestration change，必須進入決策佇列等待使用者核准。Agent 不得以「只是實作細節」吸收。

## Parallel Wave Proposal

Parallel Wave 是使用者一次核准的 exact orchestration package。Proposal 必須用摘要呈現修改前／後 Slice 結構，並包含：

- Wave ID、候選 Slice 與最多三個 Execution Candidates。
- 各候選的完整 Development Package、risk class 與 Autonomy／Review-Fix Budget。
- compatibility matrix、Read／Write Set、共用前置工作與排除候選。
- worktree／branch 配置、Worker ownership 與禁止修改區域。
- 預計完成順序、序列 review／integration 順序與每個衝突的處理方式。
- 低風險自動整合條件、高風險人工 code checkpoint、停止條件與 rollback。
- `Prepared At` 與 `Approval Expires At`；有效期固定為 2 小時。

使用者只處理一張當前決策卡。預設排序為：可快速核准且能解除最多阻礙的項目、必要澄清、拆分／共用前置變更，最後才是需要大量閱讀的高風險決定。排序不得違反 Slice dependency。

兩小時內沒有明確核准時，Wave 設為 `expired`，不得建立 worktree、branch、commit 或啟動 Worker。之後收到的舊 Proposal 核准不生效；重新檢查 repository、drafts 與 footprints，產生新的到期時間並再次等待核准。拒絕、修改要求或含糊回覆同樣不啟動。

## Wave Approval 與建立隔離環境

Wave Approval 同時核准 Proposal 中 exact candidates 的文件 checkpoint、Worker execution、完整 checks、獨立 review 與受限 integration；不核准 Final Approval，也不核准未列出的 candidate 或 fallback strategy。

核准仍須先依 commit workflow 建立每個候選的 Approval Documentation commit。只有所有必要 approval commits 都成功且 base revision 未漂移時，Coordinator 才按 Proposal 建立專用 branches／worktrees並啟動 Worker。建立後記錄 immutable Base Revision、worktree path、branch 與 owner；不得讓兩個 Worker 共用同一 worktree。

若 host 不支援隔離 worktree、無法取得足夠 Worker、branch／path 已存在、working tree 不安全或 base revision 漂移，停止建立新 Worker並產生一張決策卡。已安全啟動的 Worker可完成目前核准 batch，但不得因此擴大 Wave。

## Worker 執行與安靜通知

每個 Worker依自己的核准 Plan 連續執行 implementation batches、batch checks 與完整 required checks。一般進度、成功 batch、低風險且已修正的 finding 不通知使用者；只更新 Coordinator evidence。

以下情況才建立關鍵通知或決策卡：安全／資料／不可逆風險、Scope／contract／Write Set 越界、需要拆分或共用前置變更、Worker 間實質分歧、修正未收斂、無法建立隔離環境，或所有可執行工作均 blocked。若沒有背景通知能力，只在目前對話回報。

Worker完成時不得自行宣告 `awaiting-human`。它提交 Worker Result：actual diff、commits、checks、Base Revision、實際 Write Set、風險與偏離情況，然後進入 Review Queue。

## 序列 Review／Integration Gate

Coordinator 保持單一 FIFO-compatible gate；dependency 與 base freshness 優先，在同樣安全時先處理 review effort 最小、最快可解除後續工作的 result。任何時刻不得同時 review 或 integrate 兩個 Slice。

每個 queued result 依序執行：

1. 對最新 Integration Baseline 重算 diff、Read／Write Set 與 compatibility。若先前整合已造成 contract、dependency 或未預期 conflict，停止該 Slice並提出決策卡。
2. 由未參與該 Slice 實作的獨立 Reviewer 檢查核准 Spec／Plan、baseline、完整 diff、tests、Wave merge strategy 與跨 Slice 風險。
3. 只對 Autonomy Budget 內的內部實作／測試 finding 執行最多 1–3 輪 review–fix；修正後必須重新 review。任何公開行為、契約、資料、安全或 Slice 邊界變更都停止。
4. `low` risk 且 Reviewer recommendation 為 `approve`、required checks 通過、actual Write Set 符合 Proposal時，Integration Agent 可依核准 strategy 自動序列整合，保存 report，將 Slice 推進至 `awaiting-human`；最終摘要必須把 Reviewer 結論與整合結果提供給使用者查看。
5. `high` risk 時，Reviewer 必須指出 exact file／line、最壞影響、evidence gap 與 rollback；在使用者親自檢查並明確核准該 code checkpoint 前不得整合。其他 queued Slice 保持等待，不繞過門閥。
6. 整合完成後重跑受影響 integration checks 與完整 required checks。失敗只能在核准 integration budget 內修正並重新獨立 review；否則停止並保留可回復狀態。

Integration Agent 只可執行 Proposal 已說明的 merge／conflict strategy。即使是已預測的衝突，若實際解法改變產品行為、公開契約、資料模型、安全邊界、Slice 責任或依賴，也不得自行決定。未預測衝突一律重新分類；不能靠機械選擇 ours／theirs 繼續。

## 狀態與恢復

`controlled-parallel` 可同時有最多三個阻礙前狀態為 `approved` 或 `in-progress` 的 Active Feature Slices；blueprint 同時記錄唯一 `Integration Candidate`。queued result 仍為 `in-progress`，整合且 Verification closure 完成後才成為 `awaiting-human`。

中斷後恢復時，先以 Git、worktree list、branch tips、Approval commits 與 Worker Result 重建狀態；不能僅依對話記憶。若無法證明 branch ownership、base、actual diff 或 review queue 順序，停止並要求重新建立 Wave Proposal，不猜測或重做 commits。

Wave 中某 Slice 被判定需要拆分時，該 Slice 停止並移出可執行集合；產生拆分 Proposal 放入決策佇列。其他真正 independent 且不依賴它的 Worker可完成已核准工作，但 Review／Integration Gate 不得越過會使其 baseline 或順序失效的依賴。

## 相容性

`legacy-staged` 與 `sequential-package` 行為保持不變。既有 blueprint 不會自動升級；切換到 `controlled-parallel` 是 project-level Blueprint Revision，必須先呈現 active-slot、worktree、branch、approval expiry、review／integration 與回復差異並取得明確核准。停用時必須先讓所有 Worker、queued result 與 Integration Candidate 收斂或明確 blocked，不遺留無 owner 的 worktree／branch。
