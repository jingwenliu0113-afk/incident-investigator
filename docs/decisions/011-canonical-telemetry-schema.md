# 011 — Canonical telemetry schema（ctel/1）與 normalize policy v1（Core §4，含 §6 需要的規則）

- 狀態：Accepted（2026-10-08）；policy v1 在 soak #3 的 raw（沒有 fault）上校準後凍結，**凍結前不得打開任何含 fault 的 raw**
- 影響範圍：Agent 與所有 baseline 唯一可讀的資料格式；raw → canonical 的轉換與洩漏處理規則；evidence id；預算的計量單位
- 依據：Core §4 設計 workflow（3 個獨立設計方向 × 3 個評審角度 + 彙整）；decision 002 / 005 / 006 / 008 / 009 / 010

## 背景

- SPEC §4：raw 與 canonical 分開，所有 baseline 與 Agent 只依賴 canonical；至少要有 logs / metrics / traces。
- SPEC §6 / §7 / §9：洩漏稽核、各方法可見範圍相同、引用的 evidence 要能驗證存在。
- raw（decision 008）是 collector 在任何 processor 之前收到的 OTLP JSON Lines，包含 harness 與基礎設施的 telemetry、flag 相關的 attribute 與訊息、
  以及 harness 在 fault on / off 時對 flagd 的查詢（decision 009 §5）。

## 決策

### 1. `incidents/<INC>/normalized/`（唯一的 Agent 可讀資料）

只允許 6 個檔，多一個就拒絕：

| 檔案 | 內容 | 排序 |
|---|---|---|
| `snapshot.json` | 描述檔：`canonical_schema = "ctel/1"`、policy 版本與 sha256、資料時鐘的窗 `[start_ns, end_ns)`、固定的 18 個服務、各檔 records / bytes / sha256、`content_sha256` | — |
| `resources.jsonl` | 有被引用的 resource | resource_id |
| `spans.jsonl` | 一行一個 span | (start, id) |
| `logs.jsonl` | 一行一筆 log | (time ?? observed, id) |
| `metric_series.jsonl` | 一行一條 series | (service, metric, id) |
| `metric_points.jsonl` | 一行一個點 | (time, id) |

- UTF-8、不壓縮；每行 `json.dumps(sort_keys=True, separators=(",", ":"), ensure_ascii=True, allow_nan=False)`；排序鍵最後接 id → 逐 byte 決定性。只用 stdlib。
- snapshot.json **不放** incident id、run group id、raw sha、時鐘差、任何移除計數（這些在 ground-truth 側）。
- 發布：先寫到 `incidents/<INC>/normalized.tmp-<pid>/`（不在 allow-list 內）→ `check_snapshot` 通過 → `os.replace` 成 `normalized/`、檔案 0444；已存在就拒絕（write-once）。
- `incidents/<INC>/manifest.json`（decision 002）的 `files[]` 列 6 個檔的 sha256；不放 raw sha。
- `ground_truth/incidents/<INC>/normalize_report.json`：移除與修正的完整計數（見 4）。

### 2. Record（ctel/1）

- 欄位一律存在（缺的填 null）；時間是**資料時鐘（VM）的原值**，JSON 整數 unix ns，不平移。
- trace_id / span_id 小寫 hex（32 / 16）；全 0 或格式錯的 span 丟掉並計數。attributes 是 `{原 key: 值}`；AnyValue 無損對應
  （int 字串 → int；非有限 double → `{"$double": "NaN"}`；bytes → `{"$bytes": b64}`；array / kvlist → list / object）。
- `service` 是封閉 enum，**18 個 SUT 服務**：accounting、ad、astronomy-db、cart、checkout、currency、email、fraud-detection、frontend、frontend-proxy、
  image-provider、kafka、payment、product-catalog、quote、recommendation、shipping、valkey-cart。
- span：`id = s-<span_id>`、trace_id、parent_span_id、name（SDK 原名，不套 semconv 改名）、kind、start / end、status_code / status_message、attributes、events、links、
  dropped counts、resource_id、scope、service。
- log：`id = l-…`、time / observed_time（至少一個）、severity_number / text、body、event_name、attributes、trace_id / span_id、resource_id、scope、service。
- metric_series：`id = m-…`、resource_id、scope、service、metric、kind、unit、description、temporality、monotonic、point 維度 attributes。
- metric_point：`id = p-…`、series_id（加上反正規化的 service / metric / kind）、start / time、`first_in_window`（decision 008 §7 的跨段標記）、依 kind 的值欄位；不保留 exemplar。
- duration、delta、reset、error 判定等衍生值**不存**在 snapshot，放在共用、有版本號的 `collect/derive.py`。
- id：span 用 span_id；log / point / series 用 decision 008 §7 的 dedupe key 做 keyed blake2b（8 bytes），key = 該 incident 的 raw 檔 sha256 組合（只在 ground-truth 側），
  使 Agent 無法用「可見欄位 + 猜測被刪掉的 flag attribute」反推 hash。同一 snapshot 內 id 必須唯一。

### 3. raw → canonical（policy v1，`collect/canonical_policy.v1.json`，sha256 釘在程式與測試裡）

- **G0 前置**：run 有效、raw export complete、每個 raw 檔的 sha256 與紀錄相符、policy sha 相符、`normalized/` 不存在。
- **GT-blind**：normalize 只從 run.json 讀 raw 位置、incident window、兩個時鐘差與狀態；不讀 injection.json 或 label，規則沒有 fault 參數。
- **N2 dedupe**（整個檔、切窗前，第一筆勝出）；不變式：移除數 = raw export 的 duplicates。
- **N3 切窗**：窗邊界從 host 時間換到資料時鐘（start 用第一次時鐘差、end 用第二次）；span 依 start、log 依 time ?? observed、point 依 `(start, time]`；
  每條 series 窗內第一個點標 `first_in_window`；沒有時間的 item 丟掉並計數。
- **N4 歸屬（default-deny）**：OTLP 用 resource `service.name`；docker_stats 用 `container.name`；各 receiver（postgresql → astronomy-db、redis → valkey-cart、
  kafkametrics → kafka、nginx → image-provider、httpcheck → frontend-proxy）。不在 18 個服務內的一律丟掉並計數。
- **規則（依序，每筆移除在 ground-truth 側依 rule × signal × service × minute 計數）**：
  - X1 非 SUT 服務：flagd、flagd-ui、load-generator、frontend-web、collector 自身、jaeger、prometheus、grafana、opensearch、opamp-server、telemetry-docs 與未知服務。
    **不往下串連**：Locust 發起的 SUT trace 保留。
  - X2 整個 host_metrics 丟掉（process command line 會帶出 harness 的 `docker exec … ofrep … <flag>`）。
  - X3 自我觀測 metric：`otel.sdk.*`、`otelcol*`（loss accounting 讀 raw，不受影響）。
  - X4 控制面與基礎設施路由（flagd / flagd-ui / collector / jaeger / grafana / opamp / loadgen … 的 rpc service、peer、Envoy upstream cluster、URL path）：
    span 連同整棵子樹丟掉（對全部 span 求 closure），log 整筆丟掉，metric series 整條丟掉。
  - X5 flag 儀表化：key 符合 `(?i)feature[._-]?flag`、`^openfeature`、`^flagd(\.|$)` 的 attribute 刪掉；命中的 event / log 丟掉；命中的 metric（名稱或 point attribute）整條 series 丟掉。
  - X6 scope deny：scope 名稱命中 flagd / openfeature / feature-flag / problempattern 的 item 丟掉。
  - X7 fault-artifact 樣板（Class A，「點名注入本身」的訊息，每條附 upstream file:line，測試要求樣板比對得到引用的原始字串）：整筆丟掉。
  - X8 詞彙刪除：18 個 flag key（不分大小寫、以非英數字元為界）與 `feature flag(s)`、`openfeature`、`flagd`、`ofrep`、`flagservice`、`problem pattern`，
    在所有可見字串中**靜默刪除該 token**（連同前一個分隔字元），不留 `[redacted]` 之類的標記（標記本身會在 fault 時出現）。
  - X9 隱私（對齊 raw 跳過的 upstream processor）：刪 `demo.payment.card_cvv`、`user.email` → `user.hash`（sha256）、card_number 只留末四碼、刪 card_pin / password / secret。
  - X10 丟 exemplar 與 NoRecordedValue 的點。
- **刻意保留**：所有 SUT 的錯誤、延遲與重啟；Class C 的真實症狀（`Payment request failed. Invalid token… loyalty_level=gold`、`badhost`、`badAddress`、`LOCK TABLE` SQL）；
  Class B（只在 fault 時出現、但不點名注入的內容，例如 recommendation 的 cache hit / miss log 與 `demo.recommendation.cache_hit`）保留，並在 Core §6 預先登錄為 Easy 特徵。
- **attribute 用 deny-list**：只在 fault 路徑出現的 key 若用 allow-list 會被無聲刪掉；soak #3 inventory 以外的新 key 保留，並在 ground-truth 側列出供稽核。
- **check_snapshot（fail-closed）**：100% schema 驗證；詞彙的 byte grep 為 0；沒有被排除的服務名；沒有 `RG-[0-9]{3,}` / `INC-[0-9]{3,}` / raw sha；只有 6 個檔；id 唯一、引用完整。

### 4. 版本規則

- policy v1 在 soak #3 的 raw 上校準（服務 / scope / container / attribute key / 未知欄位 / 大小 / 時間 / 記憶體），commit 並釘 sha，**之後**才能打開 INC-001 的 raw。
- Pilot 稽核後最多一個 v2（寫 decision log、全部 incident 重跑 normalize、兩版都報告）；在任何 held-out 資料之前凍結；看到 test 結果後永遠不改。

### 5. 讀取、預算與 evidence

- 單一入口 `collect.snapshot.open_snapshot()`：只開 `is_agent_readable` 放行的路徑，驗證 sha；index（sqlite / FTS5）以 content_sha256 快取在 `data/external/cache/`，不屬於 snapshot。
- 單一 renderer `render_v1`（id 在前、時間寫成相對於窗起點的 `+MMM:SS.mmm`、省略 null、每行 ≤ 1024 bytes）。
- 預算單位 `proxy_tokens = ceil(utf8_bytes / 4)`（與模型無關，用來執行上限）；實際 token、latency、cost 另報。每個 run 記錄看過的 record id（exposure log）。
- evidence 只能引用單筆 record：`s-` / `l-` / `p-` / `m-`（可加時間範圍）/ `t-<trace_id>`；不提供 aggregate 形式的引用；`resource_id` 不可引用。
  existence = `open_snapshot().resolve(id)`。
- Agent 工具只提供資料存取（list_services、search_logs、search_spans、get_trace、list_series、get_points、service_minute_stats），**不提供異常排名**（否則等於免費拿到統計 baseline）。
- prompt 與工具說明不得描述收集協定（decision 009 修訂）；也要通過詞彙檢查。

## 延後（必須在任何 baseline 執行之前決定，寫在 baseline 的 decision log）

- 各方法拿到的時間框架（例如是否告知「前段是 normal」——統計 baseline 的 reference period 取決於此）。
- dump-all 的打包順序與 B / k / q / C / N / T 等預算數值。

## 已知取捨

- 刪 token 後的殘字（例如 `Product Catalog Fail Enabled`）；deny-list 可能漏掉只在 fault 路徑出現的 key（以 upstream 原始碼掃描 + 新 key 報表 + 稽核補強）。
- 丟掉 exemplar、`otel.sdk.*`、host_metrics 的 fidelity 損失；不套 semconv 改名使 token 成本較高。
- 移除 load-generator / frontend-web：`loadGeneratorFloodHomepage` 的 origin 在 snapshot 看不到 → Pilot 清單要嘛排除它，要嘛事先定義 origin（M3 / M5 決定）；
  `ask_agent` 的 ambient 失敗不會出現在 snapshot；user_symptom 只能從 frontend / frontend-proxy 推斷。label 的服務詞彙改為這 18 個。
- 無法移除的側通道（flag 變更時 flagd 推送造成的同步延遲、flag 消費端的網路量變化）由 Core §6 的稽核量化。
- repo 文件寫明了 INC-001 的 fault：Agent 不得掛載 repo；工具輸出不得包含路徑（路徑含 INC id）。

## 與既有決策的差異（照 CLAUDE.md 先記錄）

- decision 008 §7 說「用量到的時鐘差修正時間」：改為**換算窗邊界、不改 record 的時間戳**（保持 raw 原值、id 不變）。
- decision 008 §6 說 raw export record 要記時鐘差與 collector `service.instance.id`：目前時鐘差記在 run.json（ground-truth 側），instance id 尚未記錄；
  校準時決定是否需要補進 `raw_export.json`（schema bump）。
- decision 006 的 `check_label(services=…)` 改用這 18 個服務。

## 校準與凍結前的修正（2026-10-08，只用 soak #3 的 raw，沒有打開任何 fault raw）

### 校準結果（`data/external/calibration/20261008T120419Z/calibration.json`，soak #3 整段 raw）

- `check_snapshot`：0 個問題；未知 OTLP 欄位：無；未知服務：無；span kind 一律是整數編碼；`tokens_deleted` 全部是 0（沒有 fault 時不該有 token）。
- 保留：traces 179,719 / 253,053、logs 67,377 / 80,351、metric points 149,402 / 291,292；snapshot 277 MB（約 38.6 分鐘）。
  移除最多的是 X1（被排除的服務：flagd、frontend-web、load-generator、otelcol-contrib…）、X2（host_metrics）、X5（flag event / attribute）與 X4（控制面子樹）。
- metrics 的 `service.name` 缺值的 216,983 個點全部來自 7 個 receiver，都由 `receivers` 對應（docker_stats 依 container.name；postgresql → astronomy-db；
  redis → valkey-cart；kafkametrics → kafka；nginx → image-provider；httpcheck → frontend-proxy；host_metrics 丟掉）。
- docker_stats 少了 shipping 整個 run → 不是 policy 的問題，是 receiver 的啟動 race，見 **decision 012**。
- attribute key 裡沒有需要新增隱私規則的東西（user.id / session.id 是 load generator 產生的合成值）；三種寫法的 `feature_flag*provider*name` 都被 X5 刪掉。
- 時間與記憶體：normalize 90.7 s、整個 calibrate 151.5 s、最大 RSS 約 0.91 GB。

### 凍結前修正（read-only review workflow 的確認問題，以及 upstream 全面掃描）

1. **FA-11**：fraud-detection 在 `kafkaQueueProblems` 開啟時每筆訊息都記 `FeatureFlag 'kafkaQueueProblems' is enabled, sleeping 1 second`
   （`src/fraud-detection/src/main/kotlin/frauddetection/main.kt:67`），沒有樣板 → X8 只刪 token，留下 `'' is enabled, sleeping 1 second`，
   而且只在 fault 期間出現。新增 Class A 樣板 FA-11（整筆丟掉）。研究筆記 §6 也漏了這條，已補上。
   之後對 13 個 Core flag 在 upstream SUT 原始碼逐一掃描（ad、cart、checkout、email、fraud-detection、payment、product-catalog、recommendation、shipping），
   沒有其他「點名注入」而沒有規則的訊息。
2. **X8 套用到所有可見字串**（原本只做 value）：attribute 與 kvlist 的 key（刪完變空或撞名就丟掉該 attribute，計為 `X8_key`）、scope version、
   severity_text、metric 的 unit / description、span 與 link 的 trace_state、bytes 值裡的文字（可解碼成 UTF-8 時）。metric 名稱命中詞彙 → 整條 series 丟掉（X5），不改名。
3. **check_snapshot 也檢查解碼後的字串**：檔案層級的 byte grep 讀的是跳脫後的 JSON，`\n`、`\u00e9` 會吃掉 token 的邊界、base64 會完全藏住 token；
   含跳脫字元或 `$bytes` 的行另外解碼（含 key 與 base64 內容）再檢查。

4. **metric point 的 double 編碼一致**（資料格式修正）：histogram / exponential histogram / summary 的 sum、min、max、zero_threshold、
   explicit_bounds 與 quantile 值，NaN / ±Infinity 一律寫成 `{"$double": ...}`（原本只有 gauge / sum 這樣做）；proto3 非 `optional` 的 double
   （summary 的 sum 與 quantile、zero_threshold）被 OTLP JSON 省略時是 0，不是 null。schema 補上這些欄位的型別，check_snapshot 會擋下裸字串。
   soak #3 的 raw 只有 explicit-bucket histogram 且都是有限值，既有輸出不受影響。

5. **G0 與 provenance**：`normalize_incident` 拒絕和釘選 sha 不同的 policy（不只看 `frozen`），拒絕在 dirty / 沒有 commit 的 checkout 上跑，
   並把 normalizer 的 commit 記進 report；formal manifest 檢查移到 write-once snapshot 發布**之前**（原本失敗會留下孤兒 snapshot、無法重試）；
   `collect run` 的 preflight 在 35–50 分鐘的 run 開始前就拒絕 dirty tree。
6. **normalize report 補齊並固定格式**（`schemas/normalize_report.schema.json`，寫出前驗證）：每個移除都依 rule × signal × service × minute 計數，
   包括原本只按 signal 計的 X5_attribute、X5_event、X7_event、X8（`X8_token`、`X8_key`）與原本完全沒計的 X9（`X9_delete` / `X9_hash` / `X9_mask`）；
   `attribute_keys` 列出保留 record 的原始 attribute key（依 `signal/service`）；policy 帶 `attribute_key_inventory` 時，`new_attribute_keys` 列出
   inventory 沒見過的 key，給 Core §6 的稽核用（deny-list 的補強）。inventory 在凍結時由沒有 fault 的 soak 的 `attribute_keys` 產生，放進 policy 檔，受同一個 sha 保護。

7. **校準可以重跑、只讀 soak**：`collect calibrate` 每次寫進新的 `data/external/calibration/<soak>/<UTC 時間>/`（之前的結果保留為證據）；
   輸入必須是有 soak `report.json` 的目錄（不接受 run group 的 raw）；錯誤以 exit 2 回報。

8. **讀取端的小修正**：所有 record 的每個字串都清掉 lone surrogate（原本只有 attribute 與 body，render / proxy_tokens 會崩潰），
   check_snapshot 擋下無法編成 UTF-8 的文字；`render_v1` 的時間依 §5 寫成 `+MMM:SS.mmm`，span event 的時間也改為相對時間；
   `derive.point_deltas` 需要傳入 series 的 `monotonic`，非 monotonic 的累計 sum（UpDownCounter）下降不再當成 reset（`DERIVE_VERSION` 2）；
   calibrate 的視窗用解析後的時間取最早 / 最晚（字串比較在寬度不同時會選錯），兩端各留 1 s。

9. **harness 的 helper container**：`harness_container_prefixes: ["ii-probe-"]`。soak / run group 的 memcg 探測 container 改用這個前綴命名
   （soak #4 有一次被 docker_stats 收到，當時名稱是 Docker 隨機給的 `cool_tharp`）；normalize 以 X1 丟掉、記為 `harness-probe`，不算未知服務。
   soak #4 的 raw 裡那筆仍是隨機名稱，會被算成未知服務，所以凍結證據改用 soak #3 與 soak #5。

10. （同日第二輪 review）X9 隱私規則同時套用在原始 key 與 X8 清洗後的 key（`ofrep.user.email` 清洗後是 `user.email`，原本會漏掉 hash）；
    normalize report 改在 snapshot 發布**之前**驗證 schema；失敗的 normalize 不留 staging，未發布的暫存目錄在重試時清掉，同一個 incident 可以重跑。

policy 檔的 sha 隨 FA-11、`harness_container_prefixes` 重新釘選（狀態仍是 `calibrating`）。

### 凍結條件（2026-10-08 約 14:15Z 寫定，在用最終程式重跑校準之前）

policy 只有在**每一份**沒有 fault 的 soak raw（soak #3，以及之後用新探測命名跑的 soak #5）上同時滿足下列條件，才可以把 `status` 改為 `frozen`
（`collect.calibrate.freeze_check`，`collect calibrate` 的 exit code 只有全部通過才是 0）：

| # | 條件 |
|---|---|
| F1 | `check_snapshot` 沒有任何問題 |
| F2 | 沒有未知服務（不在 SUT 也不在 excluded），沒有未知的 OTLP 欄位 |
| F3 | X7（Class A 樣板，含 span event）在沒有 fault 的 raw 裡命中 0 次：命中就是樣板太寬 |
| F4 | X8 刪除的 token 為 0：沒有 fault 時出現 token，代表缺規則或詞彙太寬 |
| F5 | raw 裡有 telemetry 的 SUT 服務，snapshot 裡都至少留下一筆（沒有服務被規則整個清掉） |
| F6 | 約 40 分鐘的 soak：normalize ≤ 600 s、最大 RSS ≤ 4 GiB |

凍結時同時寫入：`attribute_key_inventory` = 各 soak 校準 report 的 `attribute_keys` 聯集；這裡記錄 soak 目錄、每份 `calibration.json` 的 sha256、
凍結後的 policy sha 與 commit。凍結之後，任何改動都是 v2（見 §4）。
凍結由 `python -m collect freeze --calibration <a> --calibration <b>` 執行（`collect.calibrate.freeze`）：每份校準都必須是**目前這個 policy 檔**
（sha 相同）、來自同一個乾淨的 commit（calibration.json 記錄 normalizer 的 git 狀態）且 F1–F6 全過，否則拒絕；policy 檔寫入 `status: frozen`、`attribute_key_inventory` 與 `frozen_from`（soak 與 calibration.json 的 sha256），
之後手動重釘 `POLICY_SHA256`（測試會檢查）。
