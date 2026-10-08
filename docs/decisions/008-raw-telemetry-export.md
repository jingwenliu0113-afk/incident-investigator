# 008 — M2 raw telemetry export：collector 內新增 raw pipeline，寫進 container 再複製出來

- 狀態：Accepted（2026-10-08）；R7 於 soak #3 之後修訂（見文末「修訂」）；實際 run 的數據見文末「結果」
- 影響範圍：鎖定的實驗環境（collector config → 新的 lock sha256）、資料格式（raw 檔與 raw export record）、
  目錄結構與 Agent 可讀範圍、收集協定（drain / 收尾 / loss accounting）
- 研究依據：M2 研究 workflow（4 個主題 + 逐條反向覆核 + 彙整），引用的檔案與上游原始碼見各條；以下「（推論）」表示沒有直接文件依據、要由實際 run 確認。

## 背景

- SPEC §2：`Normal period → fault on → traffic → fault off → export raw telemetry → normalize → frozen canonical snapshot`；
  SPEC §4：raw 只用於 provenance 與重新 normalize。
- decision 005：OpenSearch 會因 mapping 衝突丟 log，不能當 source of truth；Jaeger（in-memory，上限 25k traces，process 結束就消失）
  與 Prometheus（改名、只 promote 部分 resource attribute、經過會丟資料的 queue）也不是。
- 鎖定的 collector（contrib 0.159.0）實際生效的 pipeline（base → full → observability → extras，map 深度合併、list 整個取代）：
  traces `[otlp]` → resource_detection, memory_limiter, transform/sanitize_spans, gen_ai_normalizer, transform/redact_sensitive_data, redaction；
  metrics 9 個 receiver（含 span_metrics connector）→ resource_detection, memory_limiter；logs `[otlp]` → resource_detection, memory_limiter, transform/sanitize_logs。
  collector 的 self-telemetry（metrics 每 60 s、logs）用 OTLP 送回自己，沒有 :8888。
- 同一個 receiver 被多條 pipeline 使用時是同一個 graph node，fan-out 到每條 pipeline；只含 read-only consumer 的 pipeline 拿到的是**原始資料**，
  mutating pipeline 各拿一份 clone。所有 consumer 的錯誤會合併回傳給 SDK（non-permanent → SDK 重送 → 可能重複）。

## 決策

### 1. raw 的定義

raw = collector **收到、尚未經過任何 processor** 的 OTLP 資料，加上 scraper receiver 的資料。它**不是**「完整」資料：
- 不包含：SDK 端的 loss、container stdout（upstream 沒有 filelog receiver，維持不加）、flagd 自己的 Prometheus metrics、span_metrics（可由 raw span 重算）、profiles（SPEC §4 只要求 logs / metrics / traces）。
- 可能包含重複（SDK 重送）；normalize 用固定的 dedupe key 處理（決策 7）。
- 會包含 harness 與基礎設施的 telemetry：collector / Jaeger 的 self-telemetry、flagd、flagd-ui、load-generator，以及 docker_stats 看到的所有 container。
  要排除或遮蔽什麼，由 Core §4 / §6 **事先固定**的規則在 normalize 時處理；raw 保持完整。

### 2. Collector config（只新增，不改既有 pipeline）

- 新檔 `env/otelcol-config-raw.yml`，由 `env/compose.overrides.yaml` 用 volume（target `/etc/otelcol-config-extras.yml`）取代 upstream 的空白 extras stub；
  路徑以 upstream 目錄為基準寫成 `../../otelcol-config-raw.yml`。upstream source 不動；這個檔案以 project 檔記進 lock（sha256）。
  （另一個做法是在 overrides.env 改 `OTEL_COLLECTOR_CONFIG_EXTRAS`；不採用，因為所有偏離 upstream 的設定集中在同一個 overlay，
  `tests/test_locked_env.py` 的 render 差異測試才看得到。）
- 新增三條 pipeline，每條 processors 只有 `memory_limiter`（同一個 instance；不改資料、不觸發 clone；拒收時與主 pipeline 一致，避免「raw 收下、主 pipeline 拒收、SDK 重送」造成的重複）：
  - `traces/raw`：`[otlp]` → `file/raw_traces`
  - `metrics/raw`：upstream full layer 的 metrics receivers **去掉 `span_metrics`** → `file/raw_metrics`
  - `logs/raw`：`[otlp]` → `file/raw_logs`
- `file` exporter（alpha）：`format: json`（JSON Lines，每行一個 `TracesData` / `MetricsData` / `LogsData`）、不壓縮、
  `append: true`（collector 重啟或 SIGHUP 時不清空；不能與 rotation 並用）、不開 rotation、不用 `group_by`、`create_directory: true`、
  每個 signal 一個 exporter 與各自的路徑 `/raw/{traces,metrics,logs}.jsonl`。`flush_interval` 用預設 1 s。
- 不採用：feature gate、`:8888` pull reader、filelog receiver、`otlp_json_file` receiver 重播（預設值會改資料、從檔尾讀）。

### 3. 輸出位置：container 的 writable layer，收尾時複製出來

- 寫在 collector container 自己的 filesystem（`/raw/`），不 bind mount。理由：bind mount 到 project 內會讓 verify 失敗、到 upstream 內會讓 checkout 變 dirty、
  到外部會把機器相關的絕對路徑寫進 lock；named volume 會被 `down --volumes` 刪掉。
- `up` 帶 `--force-recreate`，每個 run group 的 writable layer 都是空的；collector 重啟（不是重建）時資料還在。
- 一定要在 `down` 之前用 `python -m env compose cp otel-collector:/raw <staging>` 複製出來；複製出來的檔案歸目前使用者所有。

### 4. 收集協定的收尾（drain → stop → cp → down）

1. `end`（fault 結束後的 recovery 也跑完）之後，**全部服務繼續執行 ≥ 3 分鐘**（drain）：涵蓋最長約 30 s 的 span、SDK 5 s 的 span batch、10 s 的 OTLP timeout、
   一個 60 s 的 SDK / span_metrics 週期，以及再一次 collector 內部計數器的 push。
2. `python -m env compose stop -t 120 otel-collector`（graceful；120 s 由 dry run 校正）。用 `docker inspect` 記錄 exit code；137 代表被 SIGKILL，該 run group 要標記。
3. `compose cp` → 串流 sha256 → `down --volumes`。任何失敗路徑都要在 `finally` 先嘗試 `cp` 再 `down`。
4. 收集前檢查：沒有任何**不屬於本 Project 的 container 在執行**，否則拒絕開始（docker_stats 會把它們收進 raw，也會增加負載）。
5. 每個 run 量兩次 host ↔ Docker VM 的時鐘差（host 端前後記時間，中間 `docker exec load-generator python -c 'import time; print(time.time())'`）。

### 5. 目錄與隔離（SPEC §2 目錄建議的差異）

- raw 以 **run group** 為單位，放在獨立的樹：`data/external/raw/<RG-nnn>/{traces,metrics,logs}.jsonl` 與 `raw_export.json`。
- `DataLayout.is_agent_readable(path)`：正向 allow-list，只有 `incidents/<INC>/normalized/**` 可讀（沿用 `is_ground_truth` 的 symlink / 大小寫 / hard link 判斷）。
- incident 與 raw / run group 的對應只記在 ground-truth 側；incident manifest 只放 normalized 檔的 checksum，**不放** raw 的 sha、collector instance id、collector 啟停時間
  （這些會把同一個 run group 的多個 incident 串起來）。
- **SPEC 差異記錄**：SPEC §2 的「目錄建議」把 `raw/` 放在 `incidents/INC-001/` 底下。我們把 raw 移到以 run group 為單位的獨立樹，理由：
  (1) raw 含有 flag evaluation 等答案資訊（研究筆記 §6），放在 incident 目錄就是 decision 002 拒絕過的「只靠大家只讀 normalized/」；
  (2) raw 的單位是一次 collector 生命週期（run group），拆給每個 incident 要複製 GB 等級的檔案；
  (3) 共用的 raw sha 會洩漏「哪些 incident 屬於同一個 run group」。SPEC 的「完整 telemetry 不進 Git」「manifest 必須包含 checksum」都照做（checksum 在 raw export record 與 manifest 各自記錄）。

### 6. Raw export record 與 loss accounting

- 每個 run group 一份 `raw_export.json`（`schemas/raw_export.schema.json`），記錄：每個檔案的 signal、format、bytes、sha256、行數、解析錯誤、項目數、
  最早 / 最晚的資料時間；collector 的 container id、`service.instance.id`、重啟次數、stop exit code；時鐘差；accounting 結果與旗標。
- Loss accounting 的資料來源（都不需要再改環境）：
  - collector 內部計數器（從 raw metrics 檔讀 `otelcol_*`，名稱沒有 `_total`、attribute 用點號；解析度 60 s；collector 重啟會歸零）。
  - raw 檔本身（行數、解析錯誤、項目數、重複數）。
  - SDK 端 `otel.sdk.*`（8 個開了 self-observability 的 service；任何非空的 `error.type` 都算 loss）。
  - collector stdout（執行中即時串流保存；debug exporter 的輸出有 sampling，只當錯誤與重啟的佐證，不拿來算數量）；`docker events`（重啟 / OOM）。
- 檢查式（traces / logs）：兩個內部快照之間，Δ `otlp` receiver（accepted + refused）與 Δ `file/raw_*`（sent + send_failed）一致；檔案裡的項目數 ≥ 最後快照的 sent，重複另外回報。
- 下列任一成立，該 run group 標記為 **raw 不完整**：collector 重啟、stop exit code 137、沒有 graceful stop 判定的其他 exit code（見文末修訂）、accounting 對不上或無法計算（見文末修訂 2）、memory_limiter 有 refusal、file exporter `Rejecting data`、raw 檔有解析錯誤（最後一行截斷除外，另外回報）。
  標記後的處理（判為無效或在 label 標記）與「穩定判斷條件」一起在收集第一個 incident 前定案。
- Ambient loss 不算 raw 路徑的 loss：OpenSearch 拒收、Prometheus 500、host_metrics process scraper 錯誤、`ask_agent`（decision 005）。

### 7. 給 normalize 的固定規則（細節屬於 Core §4）

- dedupe key：span `(traceId, spanId)`；metric point `(resource, scope, metric, attributes, start_time, time)`；log 用涵蓋 timestamp、trace/span id 與 resource 的內容 hash。
- 依每筆資料自己的時間戳切窗，不依檔案行序：span 用 start time；log 用 `Timestamp`，沒有時用 `ObservedTimestamp`；metric 用區間 `(start, time]`，
  每個 series 在邊界後的第一個點標記為跨段。時間用量到的時鐘差修正。
- 讀 raw 用 Python 逐行 `json.loads`；trace / span id 是 hex 字串（不能用 `google.protobuf.json_format`，它會當成 base64 解碼）。

### 8. 環境變更後的 soak（事先寫定）

加上 raw export 會改變 lock 與 collector 的負載（clone + 同步寫檔），所以要用新的 lock 再跑一次完整的 30 分鐘 baseline soak。
判定沿用 decision 004 的 R1–R6（含修訂），再加上：

| # | 條件 | 通過標準 |
|---|---|---|
| R7 | raw 收尾 | collector 沒有重啟；`stop -t 120` 的 exit code 為 0（**已修訂**：或 exit 1 加上 log 證據，見文末修訂）；`cp` 成功；三個 raw 檔都存在且非空 |
| R8 | raw 可讀 | 三個檔案逐行 `json.loads` 的解析錯誤為 0（最後一行截斷也算失敗）；每一行的 signal 都正確 |
| R9 | raw 完整 | soak 視窗內每一分鐘，traces / metrics / logs 三個 raw 檔都有資料（依資料自己的時間戳） |

這次 run 同時量測「結果」需要的數字（bytes/item、items/min、檔案大小、stop 時間、cp 時間、時鐘差、內部計數器的實際名稱）。

## 放棄的替代方案

- **用 Jaeger / Prometheus / OpenSearch 的 API 在 run 後匯出**：三者都不是 source of truth（decision 005 與上方背景）。
- **把 file exporter 加進既有 pipeline 的 exporters（處理後的資料）**：要在 extras 重寫整份 list（會漂移）；`host.name` 被覆寫後無法還原；被 memory_limiter 拒收的資料 raw 裡也沒有。
  處理後的 view 可以從原始資料在 normalize 時重建，反過來不行。
- **raw 前後都收**：磁碟加倍、clone 更多，沒有對應的需求。
- **bind mount 輸出目錄**：見決策 3。若 dry run 證明 Docker VM 磁碟不夠，才退回「host 上 project 之外的固定路徑」並另寫 decision log。
- **加 filelog receiver 收 container stdout**：改變 upstream 的 telemetry 範圍（Agent 會看到 production 通常沒有的東西）；stdout 只由 harness 保存供診斷。

## 對實驗的影響

- lock sha256 改變；之前的 smoke / soak 資料不能和之後的 incident 混用（decision 001）。新 lock 必須通過決策 8 的 soak 才能收集。
- 新增資料格式：raw JSONL（三個檔）與 `raw_export.json`；新增目錄 `data/external/raw/`；Agent 可讀範圍改為正向 allow-list。
- 研究筆記與 decision 001 的文件差異（照 CLAUDE.md 先記錄）：`prometheus/ad` 是被 full layer（不是 observability layer）拿掉的，在我們的組合裡效果相同；
  研究筆記 §4「每個 run 用不同路徑」擋不住 run 內的重啟清空（所以用 `append: true`）；「Jaeger 2.21 移除 legacy query API」說得太廣（只移除 UI 已不用的 v1 HTTP endpoints）。

## 修訂（2026-10-08 約 13:50Z 寫定：soak #3 判定為 FAILED 之後、soak #4 開始之前）

### 背景：soak #3 的 R7 失敗

soak #3（`data/external/soak/20261008T120419Z/`，新 lock）：R1–R6、R8、R9 全部通過；**R7 失敗**，因為 `stop -t 120 otel-collector` 後
collector 的 exit code 是 1（沒有重啟，停止花 0.3 s，`cp` 成功，三個檔案都完整）。

### 原因（2026-10-08 13:33–13:35Z 的診斷 run 重現，`data/external/diagnostics/20261008-collector-exit/`）

在同一個 lock 上 up → 2 分鐘 → `stop -t 120 otel-collector`，exit code 一樣是 1。collector 的最後幾行：

```
info  service@v0.159.0/service.go:320  Starting shutdown...
info  spanmetricsconnector ... Shutting down spanmetrics connector
info  extensions/extensions.go:73  Stopping extensions...
info  service@v0.159.0/service.go:334  Shutdown complete.
Error: failed to shutdown service after error: failed to shutdown meter provider: failed to upload metrics:
  Post "http://otel-collector:4318/v1/metrics": dial tcp 172.19.0.12:4318: connect: connection refused;
  failed to shutdown logger: Post "http://otel-collector:4318/v1/logs": dial tcp ...:4318: connect: connection refused
```

- upstream 的 `service.telemetry` 把 collector 自己的 metrics / logs 用 OTLP 推給**自己的** receiver（`http://${OTEL_COLLECTOR_HOST}:${OTEL_COLLECTOR_PORT_HTTP}`，見「背景」）。
- 關閉順序：先關 receiver 與 pipeline（file exporter 在這一步 flush 並關檔）→ extensions → `Shutdown complete.` → 最後才關 telemetry provider。
  provider 關閉時的最後一次推送打到已關閉的 4318，被拒絕，`Run` 回傳錯誤 → exit 1。
- 所以這個 lock 的 collector **每次正常停止都會 exit 1**，和 raw pipeline 無關；`exit code 0` 這個標準在這個環境裡永遠不會成立。
- 唯一的資料損失是 collector 自己最後一批 self-telemetry（`otelcol_*` metrics 與 collector logs），時間在 drain 的最後，不在任何分析視窗內。

### 修訂內容

1. **R7 的「graceful stop」改為**：exit code 0；**或** exit code 1，且 stop 之後的 collector log（`docker logs --tail 1000`，保存為 `otel-collector-shutdown.log`）同時滿足：
   - 最後一次 `Starting shutdown...` 之後有 `Shutdown complete.`；
   - 兩者之間沒有任何 `error` 等級的 log；
   - `Shutdown complete.` 之後只有一行 `Error: ...`，拆開後的每一段都是「telemetry provider（meter provider / logger / tracer provider）推送到
     `http://otel-collector:4318/v1/{metrics,logs,traces}` 時 `connection refused`」。
   其他 exit code、找不到 log、或多出任何別的錯誤，都**不算** graceful。exit 137 仍然失敗。R7 的其他條件（沒有重啟、`cp` 成功、三個檔非空）不變。
2. 實作：`env/soak.py` 的 `shutdown_verdict()`、`container_log()`；`finalize_raw()` 在讀完 collector 狀態後保存 log 並記錄 `graceful_stop`、`shutdown_reason`。
   測試用診斷 run 的真實 log（`tests/fixtures/otelcol-shutdown-0.159.0.txt`），並逐一驗證每一種偏離都會失敗。
3. **資料格式**：`raw_export.json` 的 `collector` 新增 `graceful_stop`（boolean | null）與 `shutdown_reason`；旗標新增 `collector_unclean_stop`
   （exit code 不是 0 也不是 137，且沒有 graceful 判定，包含狀態讀不到的情況）。第 6 節「raw 不完整」的條件同步加上這一項。
   目前還沒有任何正式 run group，不影響既有資料。
4. **soak #3 的判定不變**：仍然是 FAILED（它的 collector log 是在 drain 之前擷取的，沒有關閉過程，也無法用新標準重判）。
   新標準只用在之後的 soak；**要用同一個 lock 重新跑一次完整的 soak（#4）**，通過後才算這個 lock 可以收集。

### 放棄的替代方案

- **改 collector config 讓 exit code 變 0**（例如關掉 self-telemetry 或改成 pull 模式）：會改變 raw 裡的 `otelcol_*` 計數器，而第 6 節的 loss accounting 依賴它們；也會改變 lock。
- **直接放寬成「exit 0 或 1 都算」**：exit 1 也可能來自 file exporter 關檔失敗等真正的問題；新標準要求看到 log 證據，只接受已知、無害的那一種。
- **用新標準重判 soak #3**：沒有關閉過程的 log；而且看過結果後改標準再重判同一份資料，就是 CLAUDE.md 禁止的事。

## 修訂 2（2026-10-08 約 14:40Z：loss accounting 的具體形式，依 soak #3 的實際計數器定案；任何 fault raw 之前）

第 6 節只定了資料來源與檢查方向，`raw_export.json` 的 `accounting` 寫明「看到實際計數器後才定形式」。soak #3 的 raw 裡實際觀察到：

- collector 自己的計數器（`service.name = otelcol-contrib`；jaeger 也用同名的 `otelcol_*`，要排除）每 60 s 一次，同一次 export 的點相差幾微秒。
  名稱：`otelcol_receiver_{accepted,refused,failed}_{spans,metric_points,log_records}{receiver,transport}`、
  `otelcol_exporter_{sent,send_failed}_*{exporter}`（`send_failed` 只有非 0 時才出現）、`otelcol_processor_{incoming,outgoing}_items{otel.signal,processor}`。
- 38 次 export **每一次**，三種 signal 的「raw pipeline 的 receiver accepted 總和」都**完全等於** `file/raw_*` 的 sent；memory_limiter 的 incoming 等於 outgoing。
- SDK 端：唯一的 `error.type` 是 kafka 啟動時（比 collector 早 10 s 起來，DNS 找不到 collector）一次失敗的 160 筆 log，之後不再增加。

定案（`collect/accounting.py`）：

1. **視窗**：run group 的 incident 視窗（normal 開始到 recovery 結束）。base = 視窗開始時或之前最後一次 export；final = 視窗結束時或之後第一次 export
   （drain 3 分鐘保證有）。沒有 final、或兩次 export 的 process 起點不同（collector 重啟、計數歸零）→ `accounting_unavailable`。
2. **每個 signal 的 Δ**（final − base）：raw pipeline 的 receiver（與 `env/otelcol-config-raw.yml` 一致，有測試）accepted / refused / failed；
   `file/raw_<signal>` 的 sent / send_failed；memory_limiter 的 dropped =（incoming − outgoing）與具名 refused 計數取大者。
3. **旗標**（加進第 6 節「raw 不完整」，run group 因此無效）：
   - `memory_limiter_refused`：任何 signal 的 dropped > 0；
   - `exporter_rejected`：`file/raw_*` 的 send_failed > 0；
   - `accounting_mismatch:<signal>`：不滿足 `accepted ≤ sent ≤ accepted + refused + failed`（refused 的 batch 可能已經寫進 raw，SDK 重送造成重複，
     由 normalize 去重），或檔案裡的項目（含重複）少於 final 那次的累計 sent。soak #3 的觀察是完全相等，所以不設容忍值。
   - `accounting_unavailable`：見 1。
4. **SDK 端的 loss 只記錄、不標旗**：每個服務、每個 `otel.sdk.*` 計數器與 `error.type` 在視窗內的增量（同樣用前後兩次 export 夾住），記在 `accounting.sdk_errors`。
   這些資料在到達 collector 之前就遺失了，raw 忠實記錄了 collector 收到的東西；它是 incident 的一部分（例如 fault 讓服務送不出 telemetry），
   要在報告裡揭露，但不是 raw 路徑的缺失。
5. collector 最後一次 self-telemetry（關閉時推送失敗，見修訂）不影響計算：final 是視窗結束後的第一次正常 export。
6. soak 報告也附上視窗的 accounting，但不加入判定（R1–R9 已固定）。
7. （2026-10-08 review 修正）SDK 錯誤的增量用**該服務的 SDK export 時間**夾住視窗（視窗結束後的第一次 export），不是錯誤 series 自己的點：
   視窗結束後才第一次出現的錯誤 series（例如 drain 期間）不算在視窗內。計數器的 key 改用 JSON（`[名稱, attribute 配對]`），attribute 值含 `,` / `=` 也不會解析錯。

## 修訂 3（2026-10-08 約 14:40Z：soak #4 判定為 FAILED 之後、soak #5 開始之前）

soak #4（`data/external/soak/20261008T134542Z/`，同一個 lock，依修訂 1 的 R7 判定）：R1–R6、R9 通過；**R7、R8 失敗**。兩者都是量測程式的問題，raw 本身完整：
accounting（修訂 2）在視窗內三種 signal 的 accepted 都等於 sent、沒有任何旗標；解析錯誤 0、重複 0。

1. **R7**：關閉期間唯一的 error 是 OpenSearch exporter 清空佇列時，最後一批又因 mapping 衝突被拒（`Exporting failed. Dropping data.`，
   `otelcol.component.id = opensearch`）。修訂 1 要求「關閉期間沒有任何 error」，沒有考慮到 decision 005 的 OpenSearch 拒收在關閉時也會發生；
   OpenSearch 每分鐘約 36 次拒收，關閉時清佇列幾乎每次都會遇到。這條規則同時用在 run group 的 raw 完整性（`collector_unclean_stop`），
   照原樣會讓幾乎每個 run group 無效。**修訂**：關閉期間 `otelcol.component.kind = exporter` 且 `otelcol.component.id = opensearch` 的 error
   記為 `ambient_errors`、不影響判定；其他任何 error（包括 file/raw_* exporter、receiver、processor）仍然判為不 graceful。
2. **R8**：metrics 檔的第 2 行是 `{}`，也就是空的 MetricsData 的 proto3 JSON（沒有 resource、沒有資料），scanner 把它算成 signal 錯誤。
   **修訂**：`{}` 計為 `empty_messages`（raw export 的檔案紀錄新增這個欄位），不算 signal 錯誤；其他缺少該 signal 頂層欄位的行仍是 signal 錯誤。
3. 另外發現：docker_stats 收到一次 soak 自己的 memcg 探測 container（`docker run --rm` 沒有命名，Docker 隨機命名為 `cool_tharp`）。
   之後所有 helper container 都命名為 `ii-probe-…`，policy 把這個前綴當成 harness（X1，不算未知服務；decision 011）。

**soak #4 維持 FAILED**；修訂後的標準只用在之後的 soak。同一個 lock 重跑完整的 **soak #5**。
這是 R7 / R8 第二次在看到失敗後修訂：兩次都是 harness 對「與 raw 無關的已知現象」判斷錯誤，raw 本身的檢查（解析、signal、每分鐘覆蓋、accounting）沒有放寬。

## 結果

### soak #3（新 lock，判定 FAILED：R7；見上方修訂）

up 12:04:19Z；視窗 12:10:02Z – 12:40:09Z（31 分鐘）；drain 3 分鐘；stop 0.3 s；`cp` 2.0 s；teardown `down` exit 0、`verify` 乾淨。

| 檔案 | bytes | 行數 | 項目 | 重複 | 解析錯誤 | 資料時間範圍（UTC） |
|---|---:|---:|---:|---:|---:|---|
| traces.jsonl | 249,729,046 | 21,372 | 253,053 spans | 0 | 0 | 12:04:34 – 12:43:09 |
| metrics.jsonl | 97,624,212 | 2,077 | 291,292 points | 0 | 0 | 12:04:34 – 12:43:04 |
| logs.jsonl | 84,232,303 | 16,666 | 80,351 records | 0 | 0 | 12:04:32 – 12:43:09 |

- 規模（約 38.6 分鐘的資料）：約 6.6k spans/min（≈ 990 B/span）、7.5k points/min（≈ 335 B/point）、2.1k log records/min（≈ 1.05 kB/record）；
  合計約 432 MB，約 11 MB/min。一個 run group（約 40–50 分鐘）在 Docker VM 與 host 上各約 0.5 GB。
- collector 記憶體：memcg 的 p95 是 399.7 MiB（幾乎貼著上限），視窗內碰到 `memory.max` 2,196 次（soak #2 沒有 raw 時是 203 次）；
  增加的部分是寫 raw 檔產生的 page cache（可回收）。沒有 OOM、沒有重啟；collector log 裡 `memory_limiter` 拒收次數為 0。不在判定範圍內，只記錄。
- 已知 ambient（decision 005）：`ask_agent` 失敗 136 次；OpenSearch 失敗請求 1,078、丟掉 20,158 筆、mapping 拒收 7,562。
- loss accounting（修訂 2）在 soak 視窗 12:10:02–12:40:09 上：traces accepted = sent = 207,973、metrics 234,419、logs 65,363；
  refused / failed / send_failed / memory_limiter dropped 都是 0；沒有任何旗標；視窗內沒有 SDK 錯誤（kafka 啟動時的 160 筆在視窗之前）。
- normalize policy v1 的校準（decision 011 §4）在這份 raw 上跑完整個 soak 視窗：整個 `calibrate` 指令 151.5 s（其中 normalize 90.7 s）、最大 RSS 約 0.91 GB。

### soak #4（同一個 lock，判定 FAILED：R7、R8；見修訂 3）

up 13:45:42Z；視窗 13:51:36Z – 14:21:50Z（31 分鐘）；stop 0.4 s；teardown `down` exit 0、`verify` 乾淨。R1–R6、R9 通過（0 個 5xx / 1,822 request）。
raw：traces 228,643 spans / 225.5 MB、metrics 292,419 points / 98.0 MB、logs 74,560 records / 78.2 MB；解析錯誤 0、重複 0；metrics 有 1 行 `{}`。
accounting（視窗）：traces 177,806、metrics 234,385、logs 57,579，accepted = sent，refused / failed / dropped 都是 0，沒有旗標，沒有 SDK 錯誤。
docker_stats 漏掉 currency 整個 run（decision 012）。

### soak #5（同一個 lock，**PASSED**；依修訂 3 的標準）

程式版本 `fd09f41`；up 14:35:33Z；視窗 14:41:11Z – 15:11:20Z（31 分鐘）；teardown `down` exit 0、`verify` 乾淨。lock `sha256:055cc7a0…`。
- R1–R9 全部通過：0 個 5xx / 1,948 request；R6 checkout p95 14.7 MiB（23%）、product-catalog p95 18.4 MiB（14%），視窗內沒有碰到 `memory.max`
  （比 soak #2–#4 的約 49 / 52 MiB 低很多；判定不受影響，原因未查，記錄於此）。
- R7：stop exit 1，判為 graceful（只有 self-telemetry 推送失敗；這次關閉期間沒有 OpenSearch 錯誤）。R8：metrics 有 2 行 `{}`（空訊息），沒有解析錯誤或 signal 錯誤。
- raw：traces 256,413 spans / 252.6 MB、metrics 286,765 points / 95.7 MB、logs 82,818 records / 86.8 MB；重複 0。
- accounting（視窗）：traces 203,809、metrics 230,992、logs 65,543，accepted = sent，沒有旗標，沒有 SDK 錯誤。
- **結論：這個 lock 通過 soak，可以收集**（decision 009 §2）。soak #3、#4 的失敗都是量測程式的問題，紀錄保留。

