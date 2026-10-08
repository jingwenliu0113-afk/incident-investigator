# 008 — M2 raw telemetry export：collector 內新增 raw pipeline，寫進 container 再複製出來

- 狀態：Accepted（2026-10-08）；實際 run 的數據見文末「結果」
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
- 下列任一成立，該 run group 標記為 **raw 不完整**：collector 重啟、stop exit code 137、memory_limiter 有 refusal、file exporter `Rejecting data`、raw 檔有解析錯誤（最後一行截斷除外，另外回報）。
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
| R7 | raw 收尾 | collector 沒有重啟；`stop -t 120` 的 exit code 為 0；`cp` 成功；三個 raw 檔都存在且非空 |
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

## 結果

- （待：config 實作、lock 重新 resolve、決策 8 的 soak）
