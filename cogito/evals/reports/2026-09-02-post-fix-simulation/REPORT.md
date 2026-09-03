# Cogito 修正後全流程模擬

2026-09-02，受測版本 `df2ee65842e417260e6f73e841ac6e3d75085ae7`，包含前一輪四個修正 commit。環境：Python 3.12.10、Git 2.50.1、macOS arm64。

**原四項修正重驗通過，正常主流程與串接修正流程均能結案；但額外發現兩個新問題，其中一項可漏過核准路徑邊界，因此不能判定整體已無問題。**

這次使用新的隔離 Git repositories，未修改 Cogito 原始碼、未建立修正 commit。3 位子代理分別處理完整回歸、核准前／輸入流程、修正與結案；本輪每位工作段均少於 10 分鐘，沒有逾時工作。

**執行結果**

| 流程 | 結果 |
|---|---|
| 全部 Python 回歸 | 320/320 通過，31.581 秒，無失敗、錯誤或跳過 |
| 兩個相依 Feature Slice | 真 CLI 完成準備、核准、Start、兩波實作／驗證／審查／整合、post verification、finalization，最終 `accepted` |
| Human Gate | 真 CLI 到 `awaiting-human`，模擬核准後 `accepted` |
| 產品測試故意失敗 | 正確拒絕 verify，事件不被錯誤推進 |
| 最後驗證後夾帶修改 | 正確拒絕 finalize，未標記 accepted |
| 摘要 A → B | block/resume 後仍可修訂；缺少或舊 hash 的確認被拒；最新 hash 可確認並準備對應 Package |
| 三種 Package v1 → v2 | Feature、Maintenance、Documentation 均可重新送審；舊稿拒絕、新稿核准、核准後修訂拒絕 |
| 核准／修訂競態 | 9 次真 CLI 競態探針通過；本次均修訂方先完成，其他順序另有 deterministic 測試覆蓋 |
| 長 JSON | 大於 10 KB 的中文 inline/file payload 等價；`--payload-json` 的格式與 UTF-8 錯誤維持結構化拒絕 |
| 同一個 Maintenance run 串接三類修正 | 技術修正 → 獨立審查 needs-fix／新增修正 task → 整合 → 整合後修正 → post checks → final，成功 accepted |
| 修正負例 | 越界 snapshot、提前修正 commit、錯分支、缺 trailer、merge final 均按預期拒絕；Feature／Documentation 的 commit 型修正規則保留 |

核准前另外執行的 21 項精準測試全過；修正軌另有 8 項精準測試／規則案例全過。這些不是另外加到 320 的獨立通過總數。

Maintenance 串接情境實際記錄 `verification_corrections=2`、`review_fix_cycles=1`、integration 只有一次、Start HEAD 到 final 只有一個新 commit。Final 為 `7e5420c179b353b074575015dc3c659c1f4bcc0a`，同時包含 `TA-pre`、`TA-review`、`TA-post` 三個 trailer；Result 保存 snapshot，衍生 report 正確補上 final commit ID。這些 commit 僅存在測試 repository。

**新問題 1：P1，Maintenance 漏算 staged 變更，可能放行核准範圍外的內容**

位置：`cogito/scripts/cogito_run_store.py:270` 至 `:279` 的 `submit_agent_result()`。

Maintenance 的 base/head 通常都是同一個 Start HEAD。現有邏輯將 commit range、`git diff --name-only --`、untracked paths 合併；第二項只列工作樹相對 index 的差異，沒有取得已 staged、但工作樹與 index 相同的路徑。

已用真 CLI 重現同一根因的兩種影響：

1. 合法 `note.txt` 變更未 staged 時，正確回報 `changed_paths=["note.txt"]` 可被接受；先執行 `git add note.txt` 後，相同回報卻被拒絕：`Agent Result changed_paths do not match its commit range`。Mixed staged/unstaged 則可接受。這會阻擋正常工作方式。
2. 更重要的路徑漏檢：Package 只核准 `note.txt`；修改它但不 stage，另把未核准的 `unrelated.txt` 修改後 stage。Agent Result 只列 `note.txt`，Gate 接受；controlled checks 通過、整合、post verification 與 finalization 全部成功。最後的 commit 實際含 `unrelated.txt`，Gate 卻標為 `accepted`。

第二個現場 final commit：`bcb0062570a40e65c2f643291d8bf039b71fb554`。Machine summary：

```json
{
  "state": "accepted",
  "approved_paths": ["note.txt"],
  "declared_changed_paths": ["note.txt"],
  "actual_final_diff": [
    "docs/cogito/project-graph.json",
    "docs/cogito/results/MNT-staged-scope.json",
    "note.txt",
    "unrelated.txt"
  ]
}
```

這不是測試失敗被合理阻擋，而是缺少路徑資料造成的漏檢。最後 verified content tree 可以證明提交內容與檢查內容一致，但不能替代核准路徑驗證。此前新增的 correction snapshot 路徑檢查有正確拒絕 staged 越界內容；本次漏檢發生在**不經 correction 的一般 Maintenance 主路徑**。

建議修正時同時處理：正確收集 HEAD 到 index／working tree 的整體差異與 untracked paths、使用 NUL 分隔以保留特殊路徑；驗證 Agent Result 與 task 路徑；在結案前再次驗證實際交付 diff 沒有超出核准範圍。不得藉由清空使用者 index 隱藏此問題。

證據：[staged-only 對照](staged-maintenance.json)、[越界結案結果](staged-scope.json)。封存內有 `probe_staged_maintenance.py`、`probe_staged_scope.py`、完整 CLI 紀錄及保留的 Git repositories。

**新問題 2：P2，部分 JSON 檔案輸入遇到非法 UTF-8 會直接 traceback**

位置：`cogito/scripts/cogito_gate.py:33` 的 `_read_object()`。

`prepare-package --package invalid-utf8.json` 實際回傳 `UnicodeDecodeError` traceback、exit code 1；預期是 `{"ok":false,"error":"..."}` 與 exit code 2。事件紀錄沒有改變，未觀察到狀態損毀。

前一輪修復的是 `--payload-json` 的 `_json_arg()`，它現在能正確處理長 JSON 與非法編碼。但其他檔案參數經過 `_read_object()`，只捕捉 `OSError` 與 `JSONDecodeError`，未捕捉 `UnicodeDecodeError`。因此這是另一個仍未完善的 CLI 讀取邊界，不是原長 inline JSON 問題復發。

本次直接重現的是 `prepare-package --package`；其他共用此 loader 的命令也有相同程式路徑，但沒有逐一實跑，不列為額外已驗證案例。建議統一 JSON 檔案讀取錯誤邊界，補編碼錯誤測試。

重現指令與完整 stderr 見 [核准前驗收](preapproval.md)，封存內 `preapproval/verified/results.json` 最後一筆為此問題。

**判讀與範圍**

- 上次發現的四個問題本輪都已用有效情境重新驗證。新的兩個問題尚未修正；建議先處理 staged 路徑漏檢。
- 初版核准前探針曾將 canonical Package 與原始 draft 作完全相等比較，忽略發布時合法新增的 `package_hash`，造成三個測試腳本假失敗。修正的是探針斷言，並在全新 repositories 重跑；三種 Package 均通過。初版證據保留，最終判讀以 `preapproval/verified/results.json` 為準。
- 先前 eval #11 對 Human Gate 前 merge 的文字矛盾仍未列入這次四項修正；它是已知評測規格議題，不算本輪新發現。
- 本次 confirmation／approval／role IDs 是合成測試資料。三位真實子代理負責查核，不等同 fixture 裡實際的 Implementer／Reviewer；因此本次證明的是 CLI、Git 與 Gate 的機械流程，沒有宣稱全部 14 個自然語言 Agent eval 或真人互動品質通過。
- 這次沒有另外執行 mypy 或 skill 格式驗證。無法窮舉所有並行排程與環境差異。

**保存的證據**

[機器可讀總結](summary.json)、[完整回歸 log](unittest.log)、[回歸報告](regression.md)、[核准前報告](preapproval.md)、[Maintenance 串接結果](maintenance-chain.json)、[修正軌報告](corrections.md)、[完整現場封存](evidence.tar.gz)。封存包含所有重現腳本、CLI 輸入輸出、events、runner evidence 與測試 Git 物件。腳本保存原始絕對路徑；換環境重跑時應調整輸出目錄，不能把搬移封存當成可直接 resume 的工作樹。
