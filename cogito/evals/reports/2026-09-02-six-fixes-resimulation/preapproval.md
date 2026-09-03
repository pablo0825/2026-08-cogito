# 核准前與輸入／恢復流程重模擬

受測 HEAD：`a056941551c68f380078491809ff5ede5f48ea48`。執行時間：2026-09-02T15:15:55+00:00 至 2026-09-02T15:19:42.763908+00:00，共 **227.8 秒**，低於 10 分鐘上限。只使用新隔離 repo，未修改 Cogito 原始碼、未 commit。

## 結果

- 精準測試 **33 / 33 通過**，耗時 9.017 秒。
- 真實 CLI 命令共 **123 次**（含預期拒絕與新問題探針；Git fixture 命令另存）。
- 7 組正常／預期防護流程通過。
- 發現 **1 項新的可重現 P2 問題**，有 `[]` 與 `null` 兩種重現。

## 已通過的流程

1. Shared Understanding：A → block → resume → B；缺少確認 hash 或確認舊 A 均被拒絕且事件不變；確認 B 後只能 prepare 綁定 B 的 Package。
2. Feature、Maintenance、Documentation：Package v1 → v2，v1/v2 action replay 不重寫事件；連續兩次 block 後 resume 回等待核准，resume replay 不新增事件；舊稿核准拒絕，新稿核准成功，核准後再次 prepare 拒絕。canonical Package 以排除自身 `package_hash` 的正式 hash 函數比較，沒有前一輪的假失敗。
3. 大於 10KB 的中文 inline JSON 與 file JSON 原樣記錄一致；超長非法字串、array、非法 UTF-8 payload 均 exit 2／結構化錯誤，事件不變。
4. Gate `prepare-package`、`approve`、`agent-result`、`amend`、`verify`、`post-verify`、`validate` 的 input/package/prior，及 Runner 的 package/amendment，均對非法 UTF-8 與 UTF-16 回傳 exit 2、stderr JSON，無 traceback，事件/index 不变，也不建立 evidence 目錄。
5. 合法中文 Package 可 prepare/approve。已核准 Package 若遭非法編碼損壞，`status` 結構化拒絕，保留檔案與事件。
6. disposable `state.json` 若有非法 UTF-8 或 UTF-16，`status` 從不變的事件紀錄重建正確 cache。
7. authoritative `events.jsonl` 若有非法 UTF-8 或 UTF-16，`status` 結構化拒絕，事件與原 cache 位元組均不變。

## 新問題：非 object 的事件 JSON 行造成 traceback（P2）

把 `[]` 或 `null` 追加成事件 JSONL 的一行，再執行 `status`，會在 `cogito/scripts/cogito_events.py:31` 呼叫 `event.get(...)` 時產生 `AttributeError`，退出碼 **1**。預期應像其他無效事件一樣轉成 `CogitoError`，以結構化 JSON 錯誤退出 **2**。這不是 UTF-8 修正失效，而是解析成功後缺少頂層 object 型別檢查。

影響：受損事件檔案仍能阻止流程繼續，但 CLI 使用方無法解析標準錯誤訊息。兩種重現均確認事件與 cache 未被更動，沒有觀察到資料覆寫。

保存的 repo 目前保留 `null` 損壞行，可直接重現：

```sh
python3 /Users/pablo/Documents/project/2026-08-cogito/cogito/scripts/cogito_gate.py --repo /tmp/cogito-resimulation-final-20260902/preapproval/event-shape/repo status --run-id DEV-repo
```

證據：`event-shape/results.json` 包含 stderr、exit code、前後 SHA-256；`event-shape/array-damaged-events.jsonl` 與 `null-damaged-events.jsonl` 分別保存兩種現場；所有 argv 與輸出在同目錄 `commands.jsonl`。

## 證據與探針說明

- `targeted-tests.log`：33 個精準測試。
- `results.json` 的前 6 組：正常核准前／Payload 探針成功。
- `encoding-recovery/results.json`：完整 UTF-8／事件／cache 重驗成功。
- `encoding-recovery/utf8-rejection-proof.json`、`cache-recovery-proof.json`、`authoritative-rejection-proof.json`：前後 hash 或不變性證據。
- `summary.json`：機器可讀結論與耗時。

初版第 7 組探針嘗試直接寫入唯讀的 canonical Package，被檔案模式 `0444` 擋下，屬 fixture 的故障注入方式問題，並非產品錯誤。已在全新的 `encoding-recovery/` repo 明確暫時調整該測試檔權限後重跑，驗證完成後恢復唯讀；整組全部通過，舊現場完整保留。

核准／角色資料使用模擬輸入，未測真人互動。沒有執行中的程序或待交接未完工作。
