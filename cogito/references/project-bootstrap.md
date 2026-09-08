# Project Bootstrap and Lazy Adoption

Cogito 3.0 不遷移舊版進行中的工作，也不讀取 Blueprint 作為狀態。既有 `docs/project/`、舊 Slice/Spec/Plan/Verification 與其他文件保持原位，不批次搬移、不重寫、不刪除。

不再新建 `Blueprint`、`Slice Brief`、Verification Markdown、Commit Plan 或文件內 approval/status metadata。既有文件只作來源，不作目前 run 的狀態。

第一次觸及既有能力時，只採納與本次能力直接相關的舊文件、程式、測試及 Git 證據。舊資料是 read-only source，不自動升格為產品需求；語意不明時依 [Grilling Workflow](grilling-workflow.md) 釐清，問答期間不預先建立完整來源清冊。

正式 source registry 的路徑、內容 hash、關聯性與 disposition 依 [Package Authoring](package-authoring.md#development-package) 在 Package 準備時封存；Slice／lineage 及文件準備沿用同一流程。核准後 run draft 不再是 registry 的權威來源。採納文件隨 [Package checkpoint](stage-commits.md) 保存，不增加 bootstrap approval。

新功能預設寫入 `docs/cogito/`、`docs/specs/` 與 `docs/plans/`，不複製到 `docs/project/`。若既有 project 文件是本次核准契約的必要來源，Package 可明確允許更新；無關文件保持不動。
