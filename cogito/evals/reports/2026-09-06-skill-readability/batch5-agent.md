# Batch 5：前向閱讀模擬

本報告僅推演合成情境，不是實際核准、Gate event、runner evidence 或執行結果。未讀程式、Git history 或其他報告；未建立真實 run 或修改專案。

閱讀順序：`cogito/SKILL.md` → `grilling-workflow.md` → `shared-understanding-contract.md` → `stage-commits.md` → `human-acceptance.md` → `execution-policy.md` → `runtime-interface.md` → `replanning.md`。reference 路徑均在 `cogito/references/`。未回讀檔案；A 的呈現細節由同批後讀 contract／stage-commits 補齊，B／C 的任務及停止細節由後讀 execution／runtime／replanning 補齊。未遇到需要猜測才能續行的分歧。

## A：同一 Grilling action、摘要修訂

第一題回答後更新決策樹，直接問下一個仍必要的獨立決策；沒有新事實缺口，不重查政策、Git 或 Gate，不逐題寫檔、event 或 commit。剩餘回答使 readiness 成為 `ready`，依固定結構形成摘要，直接保存摘要而非重複進度檔。草稿存於 run drafts；呈現前將相同 bytes 放正式摘要路徑，計算 hash，以 `shared-understanding-ready` 綁定 document path/hash 及同一摘要 hash，呈現並解釋確認即授權立即 commit。使用者修訂並非確認：更新 bytes/hash、用新 action ID 再送 ready、查詢 next 並呈現最新版，維持 awaiting-confirmation。只有明確確認目前 hash（適用時含 planning round）後才登錄 confirmation；舊 hash 不可沿用。隨後 prepare checkpoint、檢查精確 paths、只提交那些檔案、record commit，再進 Boundary；不提交 drafts、不改 footer，也未授權實作。

## B：日期缺最後一天及途中追加回饋

保存原話「日期最後一天漏掉，修一下」；`acceptance_complete`、`close_after_fixes` 保持 false，不追問是否全部驗完而阻塞明確修正。查證後若為局部上界錯誤，triage local，append Amendment 與 tasks/checks，`human start` 計本 run 一輪。完成 lease、Implementer Result、合法修正內容及 completion，runner 驗證全部適用 post-integration checks，再獨立 Reviewer Results 與 human review。途中新局部項目用 human feedback 保存新批次；Gate 暫存並撤銷當輪自動結案授權。原輪完成回 awaiting-human，依 next 取原始待辦、以相同內容依序登錄分類，不重問。新批次需自己的授權，輪數不重設；待辦未清時 human-approve 也不能結案。兩批修好仍須人工驗收；不拿修正要求當結案核准。

## C：局部 UI 與共享邏輯擴大

核准邊界內的位置調整可分類 local，即使需同步 Spec；保留 immutable Package，先追加 Amendment／修正任務，start 後完成實作及 Implementer Result。completion 宣告 `document_updates` 的 Package 引用文件精確 path/reason，Gate 保存新舊 bytes/hash；所有文件修改必須在本輪正式驗證前完成。若文件晚於最後 Implementer Result 才提交，中間 commit 只能修改宣告文件，最後修正 commit 仍須 Amendment trailer；Maintenance 則保持未提交快照直到 final commit。接著 controlled checks、human verify，獨立 reviewer 檢查 UI／Spec 一致，再 human review 依有效授權路由。後續若發現須改多頁共用邏輯，立即 human escalate、停止新派工並真正停止執行者；blocked 不是停止證據。RP 保存 receipts／快照、影響分析、獨立覆核、明確提案 hash 核准及 successor 交接後才續作；不能等三輪耗盡或普通 resume。successor 完成後仍需重新人工驗收。
