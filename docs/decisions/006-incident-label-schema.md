# 006 — Incident label schema（Core §3，Day 1 #2）

- 狀態：Accepted（2026-10-08）
- 影響範圍：資料格式（ground truth）、評測協定（SPEC §8 分層評分要對照的欄位與用詞）

## 背景

- SPEC §3 建議的 label 欄位：incident_id、run_group_id、fault_family、injected_fault、origin_service、affected_services、
  user_symptom、fault_start、fault_end、traffic_profile、seed、telemetry_coverage。
- SPEC §8 要求分開評 injected fault / origin service / affected services / user symptom，不要壓成單一 root_cause 字串。
- decision 002 已經把「注入了什麼、什麼時候」放在 ground truth 側的 `run_groups/<RG>/injection.json`（事實紀錄），
  並註明 curated label 是另一份文件。

## 決策

1. **位置**：`data/external/ground_truth/incidents/<INC-nnn>/label.json`（`DataLayout.label_path`），在 ground truth 樹裡，
   `is_ground_truth()` 會拒絕；Agent 與 baseline 只拿得到 `incidents/<INC>/normalized/`（decision 002）。
2. **格式**：`schemas/incident_label.schema.json`（頂層 `additionalProperties: false`），欄位就是 SPEC §3 的 12 個，加上：
   - `label_version`；
   - `labeling`：`method`（`catalog` = 只依 fault 設計推得；`catalog+review` = 有人對照 frozen snapshot 檢查過）、`labeled_at`、`labeler`、`notes`。
   split 的指派**不放**在 label 裡（之後由固定的 split 檔決定，避免看了 label 再分 split）。
3. **injected fault 用封閉的機制層用詞評分，不用 flag 名稱**：
   `injected_fault.fault_type` ∈ {`error_response`, `unreachable_dependency`, `added_latency`, `lock_contention`,
   `cpu_saturation`, `gc_pressure`, `memory_leak`, `queue_backlog`, `traffic_flood`}。
   `flag` / `variant` 也記在 label，但只是 provenance（必須等於 injection.json），Agent 不可能、也不應該知道 flagd flag 名稱。
4. **fault_family** 由 `fault_type` 固定對應（`collect.labels.FAULT_TYPES`）：
   error ← error_response；connectivity ← unreachable_dependency；latency ← added_latency、lock_contention；
   resource ← cpu_saturation、gc_pressure、memory_leak；messaging ← queue_backlog；traffic ← traffic_flood。
5. **服務**：`origin_service` 與 `affected_services` 都必須是鎖定 stack 的 compose service 名稱；`origin_service` 必須包含在 `affected_services` 裡。
6. **user_symptom**：從 traffic generator（使用者側）看到的現象，`kinds` ⊆ {`errors`, `latency`, `degraded_feature`, `none`}，
   `none` 不能與其他並存；可加文字描述。
7. **telemetry_coverage**：traces / metrics / logs 各自標 `origin`（在 origin service 上看得到故障）、`symptom_only`（只看得到下游症狀）、
   `none`。這是 Gate「失敗主要來自 telemetry coverage 不足」的判斷依據。
   只有看過 frozen snapshot 才知道，所以 `catalog+review` 的 label **必須**有、只依 fault 設計推得的 `catalog` label **不得**有（schema 的 if/then/else）。
8. **traffic_profile 是封閉的 id**：Core 只有 `locust-upstream-3.1.0`，代表 decision 003 表中鎖定的 upstream Locust 設定，
   內容定義在 `collect.traffic.TRAFFIC_PROFILES`（`tests/test_traffic.py` 檢查鎖定的 stack 與它完全一致）。
9. **一致性檢查**（`collect.labels.check_label`）：
   - label、injection.json 與（有的話）manifest 都必須先通過各自的 schema；
   - `fault_type` 必須等於下表 flag 對應的值（`collect.labels.FLAG_FAULT_TYPES`），不在表上的 flag 不能標成 incident；
   - label 與 injection.json 的 run_group_id、incident_id ∈ incident_ids、seed、flag、variant、
     `fault_start = schedule.fault_on`、`fault_end = schedule.fault_off` 必須一致，且 `fault_start < fault_end`；`labeled_at` 必須是合法時間；
   - 有 manifest 時：incident_id、seed 一致；`manifest.traffic.settings` 必須等於 `traffic_profile` 的定義；
     fault 區間必須與該 incident 的 telemetry window 重疊。

## 為什麼

- 封閉用詞讓 injected-fault 這一層可以自動評分，而且跟 flagd 的命名脫鉤（flag 名稱本身就是洩漏面，研究筆記 §6）。
- fault_type 是依「故障機制」分，不是依「哪個 flag」：同一機制的不同 flag（例如 adFailure、paymentFailure、productCatalogFailure）
  只靠 origin service 區分，這樣 injected fault 與 origin 兩層才是獨立的評分維度。
- label 的時間與 seed 從 injection.json 複製而不是只放 reference：評分時只讀一份檔案；由 check_label 保證兩份不會不一致。

## 對照 Core 可用的 flag（研究筆記 §2；`collect.labels.FLAG_FAULT_TYPES`；Pilot 要用哪些 fault 在 M3 / M5 另外決定）

| flag | fault_type |
|---|---|
| adFailure、paymentFailure、productCatalogFailure | error_response |
| cartFailure、paymentUnreachable | unreachable_dependency |
| intlShippingSlowdown | added_latency |
| productCatalogLockContention | lock_contention |
| adHighCpu | cpu_saturation |
| adManualGc | gc_pressure |
| emailMemoryLeak、recommendationCacheFailure | memory_leak |
| kafkaQueueProblems | queue_backlog |
| loadGeneratorFloodHomepage | traffic_flood |

不在表上的 flag（`emitRawPii`、`failedReadinessProbe`、`aiRunawayAgent`、`aiSlowResponse`、`imageSlowLoad`）在我們的組合下不是 fault 或不會生效。

## 放棄的替代方案

- **用 flag 名稱當 injected_fault 的評分目標**：Agent 必須先「知道 flagd」才答得對，等於把答案空間洩漏出去。
- **用自由文字 root cause 再請 LLM 判對錯**：SPEC §8 明確要求不要壓成單一字串；也讓評分不可重現。
- **只放 reference、不複製時間 / seed**：評分程式要同時讀兩份 ground truth，而且仍然需要一致性檢查。
- **把 split 寫進 label**：split 應在看 label 之前固定（EXPERIMENT_RULES「先固定 dataset split」）。

## 尚未決定（不在 Day 1 #2 範圍）

- 每個 flag 的 a priori origin / affected / symptom（例如 `paymentUnreachable` 的 origin 是設定錯誤的 checkout 還是收不到流量的 payment；
  `kafkaQueueProblems`、`loadGeneratorFloodHomepage` 的 origin）：在 Pilot fault 清單（M3 / M5）決定，並寫 decision log。
- 各層的評分規則（例如 affected services 用 set F1 還是 recall）：在評測協定固定時決定，必須在看到任何結果之前。

## 對實驗的影響

- 之後每個 incident 都要有一份通過 `check_label` 的 label.json，才能進入任何 split。
- `fault_type` 的用詞或 flag 對照若要增減，必須在收集 Pilot 之前，並更新本文件（`tests/test_labels.py` 會檢查 schema、`FAULT_TYPES` 與 `FLAG_FAULT_TYPES` 一致）。
