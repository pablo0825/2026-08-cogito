# Project Bootstrap and Lazy Adoption

Cogito 3.0 不遷移舊版進行中的工作，也不讀取 Blueprint 作為狀態。既有 `docs/project/`、舊 Slice/Spec/Plan/Verification 與其他文件保持原位，不批次搬移、不重寫、不刪除。

不再新建 `Blueprint`、`Slice Brief`、Verification Markdown、Commit Plan 或文件內 approval/status metadata。既有文件只作來源，不作目前 run 的狀態。

第一次觸及既有能力時：

1. 在 run draft 建立 source registry，列出與本次能力直接相關的舊文件、程式、測試及 Git 證據，並記錄每項內容 hash、關聯性與 disposition。
2. 將舊資料視為 read-only source，不自動升格為產品需求；語意不明時進入 Grilling。
3. Boundary Gate 建立本次 Slice/lineage，並將 source registry 連同其 hash 封存在 immutable Package；核准後 run draft 不再是該 registry 的權威來源。
4. Package approval 後，僅把本次必要的 Project Graph、Spec/Plan 與已封存 registry 的 Package 隨第一個合法 commit 納入；不增加 bootstrap approval。

新功能預設寫入 `docs/cogito/`、`docs/specs/` 與 `docs/plans/`，不複製到 `docs/project/`。若既有 project 文件是本次核准契約的必要來源，Package 可明確允許更新；無關文件保持不動。
