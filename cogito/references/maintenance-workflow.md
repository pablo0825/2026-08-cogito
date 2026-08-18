# Maintenance Workflow

用於不改變產品行為的小型內部工程維護。Maintenance 是 Feature Slice 之外的窄路徑，不建立 Slice、Blueprint、Spec、Plan、Verification 文件或 Human Acceptance。

## Maintenance Gate

先確認沒有 active Feature Slice。`blocked` 仍占用 active slot。若已有 active Slice：

- 修改是完成該 Slice 所需：納入其核准 Plan／batch；若尚未核准則先修訂 Plan。
- 修改與該 Slice 無關：停止，等待 active Slice 結束，不平行執行 Maintenance。

只有下列條件全部成立才可使用 Maintenance：

- 只有一個清楚目的，能以一個 commit 完成與審查。
- 新 agent 能在單一 context 中理解修改及證據。
- 不改變使用者可見行為、Scope、Acceptance、API 或 Integration Contract。
- 不改變資料語意、schema、migration、安全、權限、帳號或部署行為。
- 不需要 Human Acceptance。
- 有足以證明行為不變的自動化測試或靜態檢查。

典型適用項目包括局部 identifier 改名、不改行為的函式抽取、純格式化、測試整理、內部型別收斂，以及有證據證明不可到達的 dead code 移除。

Dependency／framework 升級、build／deployment 設定、效能或快取策略、跨模組大型重構、使用者可見 UI／文案／互動，以及任何條件不確定的修改都不屬於 Maintenance。若實際需求改變產品行為，改走 Grilling 與 Feature Slice；若實作偏離有效 Spec，改走 `correction`；其他較大工程工作停止並提出適合的治理方式，不建立假的 Slice。

純文件錯字、失效 reference 與不改語意的 canonical 文件修正依 blueprint／文件規則處理，不走 Maintenance。

## Maintenance Proposal

修改前提出一份短 Proposal：

```text
Maintenance Proposal

Purpose:
- <單一修改目的>

Files:
- <明確檔案>

Invariants:
- M-I01: <不得改變的行為、型別、輸出或契約>

Required Verification:
- M-V01: <command or method> -> M-I01

Commit:
- <type>(<scope>): <English summary>
```

每個 Invariant 必須由至少一項能觀察該行為的自動化證據覆蓋；一項檢查可覆蓋多個 Invariant。優先在修改前後執行相同證據，證明沒有回歸；若只能執行修改後檢查，Proposal 必須解釋它為何仍足以證明行為不變。格式、lint、型別或 `git diff --check` 只有在對應 Invariant 本身就是該性質時才算證據；`git diff --check` 單獨不能證明產品或程式行為不變。

Maintenance 不接受 `advisory`、`human` 或 `N/A` 檢查。若原定證據實際上不適用或不足，必須修訂 Proposal 並重新取得核准，不得在執行中自行替換。

等待使用者以包含 `$cogito` 的下一則訊息明確核准。核准涵蓋 Proposal 內的修改、Required Verification 與單一 commit；不另問是否 commit，也不授權 push。模糊回覆不構成核准。

## 執行

1. 檢查 working tree、staged 狀態與目標檔案既有修改；若 Proposal 要求前後對照，先執行修改前證據並保存結果。
2. 只修改 Proposal 的 Files 與 Purpose，不建立產品文件或 Feature Slice 文件。
3. 執行全部 Required Verification，逐項回報結果與覆蓋的 Invariant。
4. 任一檢查為 `failed` 或 `not-run` 時不得 commit。只有 Proposal 已明確授權且不擴大 Purpose、Files 或 Invariants 的修正才能繼續；其餘情況停止並提出新版 Proposal。
5. 完整讀取 [commit-workflow.md](commit-workflow.md)，由它負責 diff、untracked files、`git diff --check`、staging、message 與 commit 的機械性檢查。
6. 所有 Invariant 都有充分且 `passed` 的自動化證據後，只 stage 核准檔案並建立 Proposal 指定的 commit。
7. 在對話回報 Commit ID、message、檔案、排除項目，以及每個 Invariant 對應的驗證結果，然後停止。

若需要新增未核准檔案、改變 Invariants、擴大 Purpose、修改產品或 Feature Slice 文件，或發現無法以自動化證明行為不變，立即停止。原 Proposal 不授權重新分類後的工作。

Maintenance 的驗證結果只在當次對話回報；詳細歷史由 Git 保存，不建立 execution 或 verification record。
