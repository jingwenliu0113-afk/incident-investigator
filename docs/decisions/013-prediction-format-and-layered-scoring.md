# 013 — Prediction 格式與分層評分（Pilot v1）

- 狀態：Accepted for the Pilot Set（2026-10-08）；在任何 baseline 或 Agent 執行之前寫定。
  **held-out 資料收集之前**要依 Pilot 的經驗凍結成正式版（最多改一次，寫 decision log）；看到 held-out 結果後永遠不改。
- 影響範圍：所有方法（4 組 baseline 與 Agent）的輸出格式、評分、evidence existence、報告的彙總方式（SPEC Core §8–§10、EXPERIMENT_RULES「先固定 metrics」）

## 背景

- SPEC §8：至少分開評 injected fault / origin service / affected services / user symptom，不要壓成單一 root_cause string。
- SPEC §9：evidence 分 existence 與 relevance 兩層。§10：Pilot 不進 test、同一個 run group 不跨 split、報 confidence interval 或 bootstrap。
- label 的詞彙已固定：fault_type / fault_family（decision 006）、18 個 SUT 服務（decision 011）、user symptom 的 4 種 kind。

## 決策

### 1. Prediction 格式（`schemas/prediction.schema.json`，`eval.score.check_prediction`）

每個方法對每個 incident 輸出一份：
- `fault`：`fault_type`（decision 006 的 9 種之一或 null）、`fault_family`（可以只給 family；null 時由 fault_type 推得）。
- `origin_candidates`：**排序過**的服務清單，最多 5 個，最可能的在前；空清單 = 放棄作答。
- `affected_services`：服務集合；`user_symptom.kinds`：`errors` / `latency` / `degraded_feature` / `none` 的集合。
- `evidence`：引用的 record id（`s-` / `l-` / `m-` / `p-` / `t-`，`m-` 可加時間範圍 `t0` / `t1`）。
- `usage`：tokens（in / out / proxy）、工具呼叫、retrieval 次數、latency、成本（沒有的填 null）。
- 服務必須是 snapshot 的 18 個 SUT 服務；**沒有自由文字的答案欄位**。

### 2. 每個 incident 的分數（`eval.score.score_incident`）

| 層 | 指標 |
|---|---|
| injected fault | `fault_type`（完全相同 = 1）、`fault_family`（完全相同 = 1） |
| origin | `origin_top1`、`origin_top3`、`origin_rr`（reciprocal rank；不在清單內 = 0） |
| affected | 集合的 precision、recall、F1、Jaccard（預測空集合時 precision = 0） |
| user symptom | `symptom_exact`（集合完全相同）、`symptom_jaccard` |

- 放棄作答（null / 空清單）一律算錯，不排除在分母之外。
- **主要指標（每一層各一個，報告時並列，不加權合成）**：`fault_type`、`origin_top1`、`affected_f1`、`symptom_exact`。
  其他指標（family、top-3、RR、precision / recall / Jaccard）是輔助指標，一起報告。

### 3. 彙總（`eval.score.aggregate`）

- 每個指標報平均值與 95% 區間：以 **run group 為單位的 cluster bootstrap**（有放回抽 run group，同一 run group 的 incident 一起進出），
  10,000 次、seed 0、percentile 區間。
- Pilot Set 與 held-out 分開報，永不合併。

### 4. Evidence existence（`eval.evidence.existence`）

- 引用的 id 中，`open_snapshot().resolve(id, t0, t1)` 找得到 record 的比例（`m-` 有時間範圍時，範圍內要有點）；沒有引用時是 null，不是 0 或 1。
- relevance（candidate pool、弱標籤、人工 gold subset）是另一層，之後另寫 decision；兩者永不合成一個數字。

## 為什麼

- 主要指標每層一個、並列，讓「Agent 是否更準」不會被某一層掩蓋，也符合 SPEC「不壓成單一 string」。
- origin 用排序清單，可以同時報 top-1（嚴格）與 top-3 / RR（給統計 baseline 這種天然產生排名的方法公平的比較）；限制 5 個以免灑網。
- 放棄算錯：避免方法靠拒答提高準確率。
- cluster bootstrap：同一 run group 的 incident 不獨立（SPEC §10），以 incident 為單位抽會低估變異。

## 放棄的替代方案

- **單一加權總分**：權重任意，而且會掩蓋層與層之間的取捨。
- **affected 用完全相同**：太嚴，一個服務的差異就是 0 分；F1 保留部分正確的資訊。
- **origin 允許無限長清單**：可以把所有服務列出來拿 top-k。

## 對實驗的影響

- 所有方法（含之後的 Agent）都要能輸出這個格式；baseline 的 prompt / 規則只能看 frozen snapshot（decision 011）。
- Pilot 上的數字只用於 pipeline 驗證與「baseline 難度檢查」，不作為研究結論。
