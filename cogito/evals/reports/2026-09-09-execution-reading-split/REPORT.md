# Execution 閱讀單位拆分

本次承接前一輪尚未提交的文件整理，只拆分 Execution Policy 並更新必要引用。比較基準為本次操作前的工作樹，不以 Git HEAD 冒充前一輪已交付文件。舊 execution-policy 為 309 行／22,817 字元，SHA-256 為 `b63d4151c1ffad9a4c07084abcbef50b2d13cde1e00fba81959190e6886b00c7`，與前輪紀錄的文件綁定一致。

## 修改

- [Execution Policy](../../../references/execution-policy.md) 保留正常派工、Task、checks、未知結果／重送／transient retry、一般審查與整合。未完成 Task 的原範圍內修錯不升格成正式修正。
- 新增 [Execution Corrections](../../../references/execution-corrections.md)，集中 Amendment 邊界、路徑補列、review-fix、審查採認、修正額度與 Maintenance completion。Transient 額度移至正常 check recovery，開發／整合共用 correction 預算保留同一處。
- [SKILL](../../../SKILL.md) 將正常執行與正式修正分成兩個入口；Grilling、Package Authoring、Human Acceptance、Finalization 僅更新指向已搬移章節的連結。Runtime、Replanning 及其他既有內容未在這一輪另行重構。

沒有修改程式、workflow、契約、Agent metadata 或測試；操作語意及版本 `4.4.3` 保留。前一輪文件與歷史報告保持原樣，本次沒有 commit、tag 或 publish。

## 獨立合成閱讀與保留檢查

一個無父任務歷史的新子代理依序完成三個情境。原擬使用另一代理處理修正情境，但協作工具回報 `agent thread limit reached`，因此由同一評估者續接；不是三次獨立盲測。每個情境先推演當前文件，再核對拆分前內容；後兩個情境沿用前輪上下文。

| 情境 | 實際判讀 |
|---|---|
| 原授權 Task targeted check 失敗後修復與交付 | lease → 真實 executor 登錄 → running；留原 Task／lease 修錯、保留失敗 evidence，以新 action ID 重跑，不新增 Amendment 或使用 transient retry。合法獨立 commit 後 task-finish，依 next 完成 verify、逐 Task 獨立 review、串行整合與 post-verify |
| 同 Slice 兩個 needs-fix，尚無修正 Task 且需未授權 mapper | 彙整 findings，finding-only review-fix-start；停妥 executor/checks，以 added_tasks＋path_additions 提案，獨立覆核後才授權及建立可執行 Task；新契約 evidence、trailer commit、task-finish、review-fix-complete、驗證及複審。未受影響 approval 採認為受限選項，不能覆蓋 needs-fix |
| 既有未完成 review-fix Task 再漏檔，review 事件已寫但 executor 尚未封存 | 只追加原 Task 的 path_additions／必要 added_checks；保持停止，按 next 的 retry-path-amendment 原輸入原 action ID 補完原操作。保留 Task ID、lease base、branch 與建立 Task 的原 Amendment；新 evidence 綁有效契約，後續純路徑補正另記 proposal_hash |

保存性比對沒有發現 scope、DAG、required checks、evidence、Reviewer 身分、修正額度、歷史紀錄或部分失敗恢復規則遺失。Maintenance 雙快照、延後提交與一般審查豁免的適用限制保留。

### 實際閱讀範圍與限制

正常情境的代理讀取 SKILL 全文 1–76、Execution Policy 全文 1–144、Runtime Interface 全文 1–69；在完成正常推演前沒有讀修正文件。之後為保存性比對才讀新修正文件 1–40 與 167–171、舊基準全文，並因工具截斷回讀舊 review 段。

修正情境新增讀修正文件標題索引及 59–166，另依必要引用讀 Replanning 26–42 的 executor 停止憑據；未將 RP begin/stop 套用到 path amendment。沿用已讀 Task、checks、review、共通前提與額度。

此樣本仍整檔讀取正常流程及 Runtime，多讀了部分不適用的 Maintenance、snapshot retry 與歷史恢復。故不能宣稱嚴格按需讀取或最少閱讀量已驗證，也沒有實測 token、時間或錯誤率。上述是合成閱讀決策與文件保留檢查，不是真實 Gate、controlled evidence、產品驗收或 CI 結果。

## 檢查

- 20 份 active Markdown（SKILL、README、18 份 references）的 143 個相對連結／標題 anchors 通過；範圍不包括所有歷史報告。
- 拆分前的 5 個 fenced CLI／JSON 範例，忽略搬移後縮排後，與兩份文件的範例集合完全相同；未變更命令或 payload。
- Skill creator `quick_validate.py cogito` 通過，沿用既有暫存 PyYAML，沒有安裝專案依賴。
- `git diff --check` 通過。主代理另對比拆分前工作樹，確認其他引用文件只改路由。

本次未執行 unittest、完整 regression、mypy、Gate 端到端模擬或 CI；變更限文件搬移及引用，使用內容比對、連結／格式及合成閱讀檢查，不把前輪的測試或 CLI help 結果算成本次新執行。

## 文字量

字元按 UTF-8 解碼後 `len(text)` 計算，包含 Markdown 與換行。

| 閱讀單位 | 行數 | 字元 |
|---|---:|---:|
| 原 Execution Policy | 309 | 22,817 |
| 新 Execution Policy | 144 | 11,494 |
| 新 Execution Corrections | 171 | 12,437 |
| 拆分後兩份合計 | 315 | 23,931 |

正常流程的整檔文字量減少約 49.6%；兩份合計增加 1,114 字元，主要為獨立入口、必要局部提醒與精確跨文件連結。收益是正常流程不再同時載入完整正式修正分支，而非總字數下降。

## 本輪文件綁定

| 文件 | SHA-256 |
|---|---|
| `SKILL.md` | `9d5f4203d58b05684d2f574995fb21ce2be709d080e9e18604bb55e6c253f885` |
| `references/execution-corrections.md` | `bca881671db3af003b11b925a23232e916cb22fa2c4c3fc414d9e47f48910375` |
| `references/execution-policy.md` | `fec2747ffd626318d3846eec2ca5385512bfd7cc40284ecb8364bb83f1621412` |
| `references/finalization.md` | `b32533a6cdb1a8a3744fc26393374181f0630492778b54eb639e852844725050` |
| `references/grilling-workflow.md` | `e49de8d9a84bfc3c38cdab97864c02bb7d249a494f44d1067e0ba11640a4533d` |
| `references/human-acceptance.md` | `44e83c6251f716f4befe3ec59bc8add2eebbf2639c0f66b8b54fe07ad263d3eb` |
| `references/package-authoring.md` | `92f91d4784c221d8a4d5b5e8beb0b6e0c5ffef3576a39ac8c2f09d5c64f501c5` |
