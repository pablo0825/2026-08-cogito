# Cogito CLI 恢復與長 payload 演練

本演練只使用隔離 Git repositories，不修改 Cogito 原始碼。全部狀態與敏感 verdict 透過 `cogito_gate.py` subprocess，fixture 僅產生合法 Package 與 Git 基線。

## 結果

- `preparing -> blocked -> preparing` 成功。
- `awaiting-shared-confirmation -> blocked -> awaiting-shared-confirmation` 成功。
- `awaiting-package-approval -> blocked -> awaiting-package-approval` 成功。
- 每個來源連續記錄兩個不同原因的 block，來源保留；resume 清除 blocked_from。
- 每個來源重送完全相同 resume action ID：成功且只存在一筆 resume event，無重複附加。
- 恢復後 `next` 能正常回傳原階段動作。

## 已重現問題：合法長 JSON 被當成檔名查詢

位置：`cogito/scripts/cogito_gate.py:18-19` 的 `_json_arg()`。

`--payload-json` 接受內嵌 JSON 或 JSON 檔路徑，但目前先執行 `Path(value).is_file()` 才解析 JSON。本機 Python / macOS 的 is_file 對超長 path component 擲出 OSError，因此一段完全合法的 JSON 在語法驗證前被拒絕。

- JSON 共 64、254 ASCII bytes：成功。
- JSON 共 274、514、2014、10014 ASCII bytes：CLI exit 2，`invalid JSON payload: [Errno 63] File name too long`。
- 相同 10014 bytes payload 寫入檔案、`--payload-json /tmp/.../long-payload.json`：成功。

此為輸入介面 bug，不是 workflow guard 合理拒絕；相同 payload 經 file 路徑可通過，長度也僅數百 bytes 即觸發。暫時 workaround 是傳 JSON 檔路徑。修正方向是先解析明顯的內嵌 JSON，或先嘗試 JSON parse 再把非 JSON 的字串當路徑。

## 證據

- `probe.py`：重現腳本；可用 `python3 probe.py /tmp/another-empty-cogito-probe` 重跑，目標資料夾內各案例 repo 應尚不存在。
- `logs.json`：全部 37 個 CLI 呼叫的 argv、stdout、stderr、returncode。
- `summary.json`：狀態、事件數、payload 結果摘要。
- `preparing/`、`shared/`、`package/`、`payload/`：四個隔離 repo，含 `.cogito/runs/` 原始事件及 projection。
- `long-payload.json`：成功的檔案版 payload。

沒有剩餘進行中工作；未執行 package approval 或 implementation，因本子任務只檢查核准前恢復與 CLI 輸入。所有資料均留存。
