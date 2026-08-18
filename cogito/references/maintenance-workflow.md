# Maintenance Workflow

用於不改變產品行為的小型內部工程維護。Maintenance 是 Feature Slice 之外的窄路徑，不建立 Slice、Blueprint、Spec、Plan、Verification 文件或 Human Acceptance。

## Maintenance Gate

先確認沒有 active Feature Slice。若已有 active Slice：

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
- <不得改變的行為、型別、輸出或契約>

Required Verification:
- <command or method>

Commit:
- <type>(<scope>): <English summary>
```

等待使用者明確核准。核准涵蓋 Proposal 內的修改、Required Verification 與單一 commit；不另問是否 commit，也不授權 push。模糊回覆不構成核准。

## 執行

1. 完整讀取 [commit-workflow.md](commit-workflow.md)，檢查 working tree、staged 狀態與目標檔案既有修改。
2. 只修改 Proposal 的 Files 與 Purpose，不建立產品文件或 Feature Slice 文件。
3. 執行全部 Required Verification。Maintenance 不使用 `advisory` 或 `human` Gate。
4. 任一檢查為 `failed` 或 `not-run` 時不得 commit；範圍內問題可修正後重跑。
5. 檢查實際 diff、untracked files、`git diff --check`、staged file list、message 與排除項目。
6. 所有檢查 `passed` 後，只 stage 核准檔案並建立 Proposal 指定的 commit。
7. 在對話回報 Commit ID、message、檔案、排除項目與每項驗證結果，然後停止。

若需要新增未核准檔案、改變 Invariants、擴大 Purpose、修改產品或 Feature Slice 文件，或發現無法以自動化證明行為不變，立即停止。原 Proposal 不授權重新分類後的工作。

Maintenance 的驗證結果只在當次對話回報；詳細歷史由 Git 保存，不建立 execution 或 verification record。
