# 101 — 探索性結果：Gemini 4 Argon 重跑三個 LLM 方法（held-out）

- 狀態：結果報告，2026-11-01 新增（decision 032 §1 第 3 點預留的固定檔名）。**只寫一次**：之後發現的錯誤寫進新的 decision，本檔不改（030 §3、032 §1）。
  它不是設計決策；放在 `docs/decisions/` 只因為 freeze 之後 main 只能新增這裡的檔案（030 §1、032 §4）。
- **EXPLORATORY, NOT a Gate decision.** Core 的 Gate 判定仍是 [100](100-heldout-final-results.md) 與 [031](031-heldout-wrap-up.md) 的 **NOT PASSED**，本檔不改變它。
  這 50 個 held-out incident 的結果在本實驗之前已經發布（100），所以本檔只能寫「探索性結果顯示…」（032 §1 第 4 點）。
- 本檔只轉寫 branch `explore/032-argon` 上的探索工具（`python -m eval.explore`）寫出的檔案；stat-anomaly 與 qwen 的數字照抄 100。不手算、不新增指標或比較。
  表格照原檔（英文欄位）轉寫；§3 的總表只是把各份 table.md 的同一列並排。
- 不列任何 held-out incident id 或 run group id（030 §4 第 12 項）：只用 fault。
- 必讀的兩個限制（§9）：模型版本只釘到名稱（[035](035-explore-gemini-turns-and-weak-pin.md) 第 3 點）；三個方法的實際執行順序與 032 §2 登記的不同（[036](036-explore-method-order.md)）。

## 1. 範圍與來源

- 事前登記：[decision 032](032-exploratory-gemini-argon.md)（Accepted 2026-10-31）；連線 [033](033-explore-gemini-api-key.md) → [034](034-explore-back-to-vertex.md)；adapter 修正 [035](035-explore-gemini-turns-and-weak-pin.md)；執行順序 [036](036-explore-method-order.md)。
- incident：與 100 相同的 50 個（`heldout_incidents.json` sha256:e606baae8b8944f1267e6296e7d9784620b952149b12f37e46dc99821a6140b5；freeze 紀錄
  sha256:7d68302545d958c4ba4d787e2d4f6fa558c954ccb27b7369f217b4b14d20cb39）。snapshot、label、ground truth 都是凍結的那一份；排除的 1 個 slot 與 100 §4 相同。
- 方法、prompt、7 個工具、可見資料範圍、預算、評分與統計都與正式執行相同（032 §2）：dump-all v2（B = 120,000 proxy tokens）、retrieval v2（q = 8、k = 25）、
  agent v1（40 次工具呼叫、120,000 proxy tokens、30 回合）。stat-anomaly 不是 LLM，沒有重跑；比較時讀正式結果（唯讀）。
- 程式：branch `explore/032-argon`（永不 merge 回 main）。執行時是 commit `04afdf3`；評分、比較、gate 在 `80de29e`（兩者之間只合併了 main 的 decision 與 NEXT）。
  main 的程式與 tag `heldout-final`（e47f2c7）不變。
- 數字來源（`data/external/` 不進 git）：`data/external/results/explore-032/heldout/<method>/table.md` 與 `scores.json`（`eval.explore score`）、
  `compare-<method>-vs-formal-{stat-anomaly,<method>}.md`（`eval.explore compare`）、`agent/gate.md` 與 `gate.json`（`eval.explore gate`）。
  這些檔案在 gold 完成之後（2026-11-01）寫出。`gate.json` 記錄的 inputs：
  - `scores_sha256` agent：sha256:f32f891509f91fe90c83479ee211ee41409676dd6d2ed33d4c1533ffda213dad
  - `scores_sha256` formal stat-anomaly：sha256:b7ce9349b1ec66b70968b238055bf14ba9c5023fd03d5c064be581b4c2998513（與 100 相同）
  - 另外兩個方法的 `scores.json`：dump-all sha256:5c618c696a889402a6b477a0deec19bedfb7b7361f9330d0e540e051fe7c3705；
    retrieval sha256:9f1c3415ff9ef209cb0ff3e552aaf5e15ebf396126a95ceef0052d51c72b9974

## 2. 模型、設定與執行

### 模型與設定（032 §3）

table.md 記錄的設定（三份相同）：

> Model: google-gemini gemini-4-argon through vertex; versions seen: gemini-4-argon.
> Settings: thinking LOW, temperature 0, seed 42, max_output_tokens 32768.
> Prices (USD per 1M tokens, each reply at the price of its time): input 2.0, cached input 0.1, output 10.0; from 2026-12-01T00:00:00Z: input 4.0, cached input 0.2, output 20.0.
> Tokens and latency are not comparable with the formal run (another tokenizer; network and cloud instead of the local GPU); proxy tokens are.

- Vertex AI（endpoint global），使用者自己的 Google Cloud project 與登入憑證（ADC），付款用試用抵免額。單次呼叫逾時 3,600 秒（與正式執行相同）。
- 三個方法所有回覆的 thinking tokens 都是 0。
- 與正式執行（qwen3.5 9B q4_K_M，本機 RTX 5070 Ti，100 §2）不同的只有 032 §3 表列的項目。

### 執行順序與時間（UTC，2026-10-31）

| 步驟 | 方法順序 | 時間 |
|---|---|---|
| Pilot 第 1 題（032 §6 第 5 步） | dump-all → retrieval → agent | 08:46Z |
| Pilot 其餘 9 題（第 6 步） | dump-all → retrieval → agent | 08:52Z – 09:26Z |
| held-out 50 題（第 7 步） | dump-all（09:26:59Z）→ retrieval（09:48:34Z）→ agent（10:14:26Z – 15:30:31Z） | 09:26:59Z – 15:30:31Z |

- 032 §2 登記的順序是 retrieval → agent → dump-all；實際順序不同，見 036 與 §9。

### 只用第一次執行的結果

- 每個（方法, incident）只跑一次，prediction 永不覆寫；只有 `api_error` / `transport_error` 重試，最多 2 次嘗試（032 §2）。看到結果之後沒有換模型、沒有改設定重跑。
- 嘗試（各方法 `attempts.jsonl` 的結束紀錄）與 table.md「Failed attempts」原文：

| 方法 | 有 prediction | 嘗試 | Failed attempts（table.md 原文） |
|---|---:|---|---|
| retrieval | 50 | 50 ok | `Failed attempts: 0 (tokens in 0, out 0, cost USD 0, latency s 0).` |
| dump-all | 50 | 50 ok | `Failed attempts: 0 (tokens in 0, out 0, cost USD 0, latency s 0).` |
| agent | 49 | 49 ok、2 `transport_error` | `Failed attempts: 2 (tokens in 213317, out 1224, cost USD 0.395987, latency s 7906.368).` |

- agent 的 2 次失敗是同一個 incident：兩次嘗試都在某一次呼叫等滿 3,600 秒後 `ReadTimeout: The read operation timed out`（兩次嘗試分別約 62 與 70 分鐘）。
  重試規則用完，評分時補 `_abstain`（013 §2、026 解讀 19）：留在分母、算 `no_answer`、F2 的 11 個指標都是 0。agent table.md 原文：
  `Scored as abstentions (no prediction after the retry rule): … (transport_error, transport_error).`（incident id 省略）。
  這是雲端連線的失敗，不是模型的判斷；照登記的規則仍算 agent 的放棄作答。
- dump-all 與 retrieval 在**同一個** incident 各自提交了「沒有 fault」的答案（fault 兩個 null、`origin_candidates` 空清單、`user_symptom.kinds` `["none"]`），
  照 013 §2 算 `no_answer`、留在分母。agent 在這個 incident 有答案（`seen_misread`）。
- 健康檢查（`data/external/logs/explore-032/inspect-run.py`，只讀 attempts、calls、transcript）：held-out 539 次呼叫、Pilot 110 次，`finish_reason` 都是 STOP，
  `model_version` 都是 `gemini-4-argon`；沒有更正（corrections 0）、沒有無法解析的工具參數、沒有空回覆。呼叫內的重試（HTTP 408 / 429 / 5xx 與斷線，adapter 的 `CALL_RETRIES`）：dump-all 2、retrieval 0、agent 9。
- Pilot（032 §6 第 6 步）只用來驗證 adapter，沒有評分，永不與 held-out 合併：30 / 30 嘗試 ok；agent 有 5 / 10 題 `submitted_after_limit`；費用 dump-all $4.482、
  retrieval $2.020、agent $3.623（合計 $10.125）。adapter 唯一的 bug 在任何 Pilot 之前修正（035），Pilot 沒有重跑。

## 3. 分層分數

各方法 table.md 的開頭（三份相同，也與 100 相同）：

> n = 50 incidents in 50 run groups; 95% interval: run-group cluster bootstrap (10000 resamples, seed 0).
> Labels: 50 reviewed (catalog+review), 0 a priori (catalog) (decision 018).

### 四個方法並排（平均；stat-anomaly 與 qwen 取自 100 §4）

主要指標標 (main)，其餘是輔助指標。主要指標不合成一個數字（013 §2）。

| metric | stat-anomaly | retrieval qwen | retrieval Argon | dump-all qwen | dump-all Argon | agent qwen | agent Argon |
|---|---:|---:|---:|---:|---:|---:|---:|
| fault_type (main) | 0.320 | 0.480 | 0.880 | 0.460 | 0.900 | 0.480 | 0.940 |
| fault_family | 0.420 | 0.640 | 0.920 | 0.600 | 0.920 | 0.540 | 0.880 |
| origin_top1 (main) | 0.660 | 0.620 | 0.860 | 0.720 | 0.840 | 0.580 | 0.820 |
| origin_top3 | 1.000 | 0.640 | 0.980 | 0.720 | 0.980 | 0.580 | 0.980 |
| origin_rr | 0.810 | 0.627 | 0.920 | 0.720 | 0.910 | 0.580 | 0.900 |
| affected_precision | 0.949 | 0.830 | 0.838 | 0.818 | 0.849 | 0.715 | 0.807 |
| affected_recall | 0.737 | 0.872 | 0.980 | 0.742 | 0.980 | 0.757 | 0.980 |
| affected_f1 (main) | 0.800 | 0.811 | 0.876 | 0.738 | 0.881 | 0.697 | 0.855 |
| affected_jaccard | 0.714 | 0.750 | 0.838 | 0.667 | 0.849 | 0.640 | 0.807 |
| symptom_exact (main) | 0.400 | 0.500 | 0.740 | 0.460 | 0.760 | 0.460 | 0.760 |
| symptom_jaccard | 0.500 | 0.600 | 0.740 | 0.550 | 0.780 | 0.560 | 0.760 |

### Argon 三個方法（平均與 95% 區間，各 table.md 第一張表）

| metric | retrieval | dump-all | agent |
|---|---|---|---|
| fault_type (main) | 0.880 [0.780, 0.960] | 0.900 [0.800, 0.980] | 0.940 [0.860, 1.000] |
| fault_family | 0.920 [0.840, 0.980] | 0.920 [0.840, 0.980] | 0.880 [0.780, 0.960] |
| origin_top1 (main) | 0.860 [0.760, 0.940] | 0.840 [0.740, 0.940] | 0.820 [0.700, 0.920] |
| origin_top3 | 0.980 [0.940, 1.000] | 0.980 [0.940, 1.000] | 0.980 [0.940, 1.000] |
| origin_rr | 0.920 [0.860, 0.970] | 0.910 [0.850, 0.960] | 0.900 [0.830, 0.960] |
| affected_precision | 0.838 [0.756, 0.909] | 0.849 [0.766, 0.921] | 0.807 [0.723, 0.880] |
| affected_recall | 0.980 [0.940, 1.000] | 0.980 [0.940, 1.000] | 0.980 [0.940, 1.000] |
| affected_f1 (main) | 0.876 [0.805, 0.936] | 0.881 [0.809, 0.944] | 0.855 [0.783, 0.916] |
| affected_jaccard | 0.838 [0.756, 0.909] | 0.849 [0.766, 0.921] | 0.807 [0.723, 0.880] |
| symptom_exact (main) | 0.740 [0.620, 0.860] | 0.760 [0.640, 0.880] | 0.760 [0.640, 0.860] |
| symptom_jaccard | 0.740 [0.620, 0.860] | 0.780 [0.660, 0.890] | 0.760 [0.640, 0.860] |

### 難度層（decision 015；有 ≥ 10 個 run group 的層才有區間）

qwen 與 stat-anomaly 的難度層見 100 §4。

**retrieval（Argon）**

| difficulty | n | fault_type | origin_top1 | affected_f1 | symptom_exact |
|---|---:|---:|---:|---:|---:|
| easy | 25 | 1.000 [1.000, 1.000] | 0.800 [0.640, 0.960] | 0.964 [0.930, 0.989] | 0.800 [0.640, 0.960] |
| medium | 1 | 1.000 | 1.000 | 1.000 | 1.000 |
| hard | 24 | 0.750 [0.583, 0.917] | 0.917 [0.792, 1.000] | 0.780 [0.654, 0.895] | 0.667 [0.458, 0.833] |

**dump-all（Argon）**

| difficulty | n | fault_type | origin_top1 | affected_f1 | symptom_exact |
|---|---:|---:|---:|---:|---:|
| easy | 25 | 1.000 [1.000, 1.000] | 0.840 [0.680, 0.960] | 0.971 [0.949, 0.994] | 0.840 [0.680, 0.960] |
| medium | 1 | 1.000 | 1.000 | 0.533 | 1.000 |
| hard | 24 | 0.792 [0.625, 0.917] | 0.833 [0.667, 0.958] | 0.802 [0.668, 0.921] | 0.667 [0.458, 0.833] |

**agent（Argon）**

| difficulty | n | fault_type | origin_top1 | affected_f1 | symptom_exact |
|---|---:|---:|---:|---:|---:|
| easy | 25 | 1.000 [1.000, 1.000] | 0.840 [0.680, 0.960] | 0.950 [0.907, 0.987] | 0.800 [0.640, 0.960] |
| medium | 1 | 1.000 | 1.000 | 1.000 | 1.000 |
| hard | 24 | 0.875 [0.750, 1.000] | 0.792 [0.625, 0.958] | 0.750 [0.621, 0.863] | 0.708 [0.500, 0.875] |

## 4. 配對差異（`compare-*.md` 原文；paired run-group cluster bootstrap，10,000 次、seed 0）

六份比較全部列出（3 個方法 × {stat-anomaly, 同方法的 qwen}），每份 4 個主要指標；沒有做多重比較校正。
只有「agent − stat-anomaly 的 origin_top1」對應 Gate 條件 1（023 §7）；其餘都只是描述。

### 對 stat-anomaly（正式結果，唯讀）

| metric | retrieval Argon − stat-anomaly | dump-all Argon − stat-anomaly | agent Argon − stat-anomaly |
|---|---|---|---|
| fault_type | 0.560 [0.420, 0.700] | 0.580 [0.440, 0.720] | 0.620 [0.480, 0.760] |
| origin_top1 | 0.200 [0.040, 0.360] | 0.180 [0.020, 0.340] | 0.160 [0.000, 0.320] |
| affected_f1 | 0.076 [-0.009, 0.155] | 0.081 [-0.006, 0.160] | 0.055 [-0.042, 0.148] |
| symptom_exact | 0.340 [0.080, 0.560] | 0.360 [0.140, 0.580] | 0.360 [0.120, 0.580] |

### 對同方法的 qwen（正式結果，唯讀）

| metric | retrieval Argon − qwen | dump-all Argon − qwen | agent Argon − qwen |
|---|---|---|---|
| fault_type | 0.400 [0.260, 0.540] | 0.440 [0.300, 0.580] | 0.460 [0.320, 0.600] |
| origin_top1 | 0.240 [0.080, 0.400] | 0.120 [-0.040, 0.280] | 0.240 [0.080, 0.400] |
| affected_f1 | 0.066 [0.000, 0.132] | 0.144 [0.045, 0.247] | 0.158 [0.077, 0.242] |
| symptom_exact | 0.240 [0.120, 0.360] | 0.300 [0.160, 0.440] | 0.300 [0.160, 0.440] |

（每格是 mean difference 與 95% 區間，n 都是 50。100 的 compare 是 agent − stat-anomaly：origin_top1 −0.080 [−0.280, 0.120]。）

## 5. Gate 條件的描述（`eval.explore gate --set heldout` 的 gate.md 原文；只描述，不判定）

> EXPLORATORY (decision 032), NOT a Gate decision: the frozen methods with another model (Gemini), on incidents whose results were already published. The Gate decision stays the one of decisions 100 and 031 (NOT PASSED).

All three conditions met: no (EXPLORATORY, decision 032; NOT a Gate decision).

| condition | value | |
|---|---|---|
| 1: origin_top1 of agent minus each statistical baseline, paired 95% lower bound > 0 | agent - stat-anomaly: mean 0.160, 95% interval [0.000, 0.320], n 50 | not met |
| 2: a fault with origin_top1 wrong on >= ceil(K/2) incidents, more than half of them in one decision-022 category | paymentUnreachable on: 4 of 4 wrong are seen_misread (K 5); productCatalogLockContention on: 3 of 3 wrong are seen_misread (K 5) | met |
| 3: not_seen + seen_misread > 0.5 of the failures (decision 022) | 8 of 11 failures = 0.73 | met |

- 條件 1 的下界是 0.000，不大於 0，所以未達成。

### Condition 2 by fault

| fault | scored | K | ceil(K/2) | origin wrong | categories of the wrong origins | met |
|---|---:|---:|---:|---:|---|---|
| adHighCpu on | 5 | 5 | 3 | 0 | - | no |
| adManualGc on | 5 | 5 | 3 | 0 | - | no |
| cartFailure 100% | 5 | 5 | 3 | 0 | - | no |
| emailMemoryLeak 1000x | 5 | 5 | 3 | 1 | seen_misread 1 | no |
| intlShippingSlowdown 10sec | 5 | 5 | 3 | 1 | no_answer 1 | no |
| paymentFailure 100% | 5 | 5 | 3 | 0 | - | no |
| paymentUnreachable on | 5 | 5 | 3 | 4 | seen_misread 4 | yes |
| productCatalogFailure on | 5 | 5 | 3 | 0 | - | no |
| productCatalogLockContention on | 5 | 5 | 3 | 3 | seen_misread 3 | yes |
| recommendationCacheFailure on | 5 | 5 | 3 | 0 | - | no |

### Descriptive only (not Gate criteria)

- Coverage (SPEC Gate "收尾或改題"; no threshold): 0 of 11 failures = 0.00; 0 failures classified without a reviewed label (decision 022 §2); 11 failures among 50 scored incidents.
- agent - stat-anomaly, other main metrics (fault_type is never a Gate criterion, decision 023 §7): fault_type 0.620 [0.480, 0.760], affected_f1 0.055 [-0.042, 0.148], symptom_exact 0.360 [0.120, 0.580].
- Leave one fault out (agent - stat-anomaly, origin_top1 lower bound): adHighCpu on 0.000, adManualGc on 0.000, cartFailure 100% -0.089, emailMemoryLeak 1000x 0.000, intlShippingSlowdown 10sec 0.000, paymentFailure 100% 0.000, paymentUnreachable on 0.133, productCatalogFailure on -0.089, productCatalogLockContention on -0.044, recommendationCacheFailure on 0.000.

#### origin_top1 by fault: right k of K, agent and stat-anomaly (decision 023 §7 robustness report; descriptive only)

| fault | agent right / K | stat-anomaly right / K | paired | direction |
|---|---:|---:|---:|---|
| adHighCpu on | 5 / 5 | 5 / 5 | 5 | 0 |
| adManualGc on | 5 / 5 | 5 / 5 | 5 | 0 |
| cartFailure 100% | 5 / 5 | 0 / 5 | 5 | + |
| emailMemoryLeak 1000x | 4 / 5 | 4 / 5 | 5 | 0 |
| intlShippingSlowdown 10sec | 4 / 5 | 4 / 5 | 5 | 0 |
| paymentFailure 100% | 5 / 5 | 5 / 5 | 5 | 0 |
| paymentUnreachable on | 1 / 5 | 5 / 5 | 5 | - |
| productCatalogFailure on | 5 / 5 | 0 / 5 | 5 | + |
| productCatalogLockContention on | 2 / 5 | 0 / 5 | 5 | + |
| recommendationCacheFailure on | 5 / 5 | 5 / 5 | 5 | 0 |

- intlShippingSlowdown 的 origin 錯 1 個是 §2 的 transport 放棄作答。
- gold 不是 Gate 條件：gold 之前與之後的 `gate.json` 只有 inputs 的 sha 不同。

## 6. 各 fault 表（023 §7；描述用，沒有區間）

equal weight 與 incidents 兩列的定義、qwen 與 stat-anomaly 的各 fault 表見 100 §6。三個方法每個 fault 都是 5 / 5 scored，Missing cells: none。

**retrieval（Argon）**

| fault | scored / K | fault_type | origin_top1 | affected_f1 | symptom_exact |
|---|---:|---:|---:|---:|---:|
| adHighCpu on | 5 / 5 | 1.000 | 1.000 | 0.440 | 0.200 |
| adManualGc on | 5 / 5 | 1.000 | 1.000 | 1.000 | 1.000 |
| cartFailure 100% | 5 / 5 | 1.000 | 1.000 | 0.933 | 0.000 |
| emailMemoryLeak 1000x | 5 / 5 | 0.000 | 0.800 | 0.560 | 0.200 |
| intlShippingSlowdown 10sec | 5 / 5 | 1.000 | 1.000 | 1.000 | 1.000 |
| paymentFailure 100% | 5 / 5 | 1.000 | 1.000 | 1.000 | 1.000 |
| paymentUnreachable on | 5 / 5 | 1.000 | 0.000 | 0.886 | 1.000 |
| productCatalogFailure on | 5 / 5 | 1.000 | 1.000 | 1.000 | 1.000 |
| productCatalogLockContention on | 5 / 5 | 0.800 | 0.800 | 0.945 | 1.000 |
| recommendationCacheFailure on | 5 / 5 | 1.000 | 1.000 | 1.000 | 1.000 |
| equal weight (10 faults) | | 0.880 | 0.860 | 0.876 | 0.740 |
| incidents | | 0.880 | 0.860 | 0.876 | 0.740 |

**dump-all（Argon）**

| fault | scored / K | fault_type | origin_top1 | affected_f1 | symptom_exact |
|---|---:|---:|---:|---:|---:|
| adHighCpu on | 5 / 5 | 1.000 | 1.000 | 0.323 | 0.000 |
| adManualGc on | 5 / 5 | 0.800 | 1.000 | 1.000 | 1.000 |
| cartFailure 100% | 5 / 5 | 1.000 | 1.000 | 1.000 | 0.200 |
| emailMemoryLeak 1000x | 5 / 5 | 0.800 | 0.800 | 0.800 | 0.800 |
| intlShippingSlowdown 10sec | 5 / 5 | 1.000 | 1.000 | 0.907 | 0.600 |
| paymentFailure 100% | 5 / 5 | 1.000 | 1.000 | 1.000 | 1.000 |
| paymentUnreachable on | 5 / 5 | 1.000 | 0.200 | 0.857 | 1.000 |
| productCatalogFailure on | 5 / 5 | 1.000 | 1.000 | 1.000 | 1.000 |
| productCatalogLockContention on | 5 / 5 | 0.400 | 0.400 | 0.927 | 1.000 |
| recommendationCacheFailure on | 5 / 5 | 1.000 | 1.000 | 1.000 | 1.000 |
| equal weight (10 faults) | | 0.900 | 0.840 | 0.881 | 0.760 |
| incidents | | 0.900 | 0.840 | 0.881 | 0.760 |

**agent（Argon）**

| fault | scored / K | fault_type | origin_top1 | affected_f1 | symptom_exact |
|---|---:|---:|---:|---:|---:|
| adHighCpu on | 5 / 5 | 1.000 | 1.000 | 0.330 | 0.400 |
| adManualGc on | 5 / 5 | 1.000 | 1.000 | 1.000 | 1.000 |
| cartFailure 100% | 5 / 5 | 1.000 | 1.000 | 0.867 | 0.000 |
| emailMemoryLeak 1000x | 5 / 5 | 0.600 | 0.800 | 0.760 | 0.400 |
| intlShippingSlowdown 10sec | 5 / 5 | 0.800 | 0.800 | 0.800 | 0.800 |
| paymentFailure 100% | 5 / 5 | 1.000 | 1.000 | 1.000 | 1.000 |
| paymentUnreachable on | 5 / 5 | 1.000 | 0.200 | 0.886 | 1.000 |
| productCatalogFailure on | 5 / 5 | 1.000 | 1.000 | 1.000 | 1.000 |
| productCatalogLockContention on | 5 / 5 | 1.000 | 0.400 | 0.909 | 1.000 |
| recommendationCacheFailure on | 5 / 5 | 1.000 | 1.000 | 1.000 | 1.000 |
| equal weight (10 faults) | | 0.940 | 0.820 | 0.855 | 0.760 |
| incidents | | 0.940 | 0.820 | 0.855 | 0.760 |

- 三個 Argon 方法在 paymentUnreachable 的 origin_top1 都低（retrieval 0 / 5、dump-all 1 / 5、agent 1 / 5；stat-anomaly 5 / 5）。
- adHighCpu 的 affected_f1（0.32–0.44）與 cartFailure 的 symptom_exact（0.00–0.20）三個方法都低。

## 7. 失敗分類（decision 022）

各方法 table.md「Failures」段的類別表（逐 incident 的列表含 incident id，不轉寫）。

### 總表（origin 或 fault type 答錯的 incident 數；qwen 與 stat-anomaly 取自 100 §7）

| 方法 | 失敗 | no_answer | coverage | mechanism | not_seen | seen_misread | rule_limit |
|---|---:|---:|---:|---:|---:|---:|---:|
| stat-anomaly | 36 | 0 | 0 | 19 | 0 | 0 | 17 |
| retrieval qwen | 34 | 0 | 0 | 15 | 0 | 19 | 0 |
| retrieval Argon | 12 | 1 | 0 | 5 | 0 | 6 | 0 |
| dump-all qwen | 30 | 3 | 0 | 16 | 0 | 11 | 0 |
| dump-all Argon | 10 | 1 | 0 | 2 | 0 | 7 | 0 |
| agent qwen | 32 | 4 | 0 | 11 | 3 | 14 | 0 |
| agent Argon | 11 | 1 | 0 | 2 | 0 | 8 | 0 |

### retrieval（Argon）

12 incidents with origin or fault type wrong (0 classified without a reviewed label)

| category | count | share | easy | medium | hard |
|---|---:|---:|---:|---:|---:|
| no_answer | 1 | 0.08 | 0 | 0 | 1 |
| coverage | 0 | 0.00 | 0 | 0 | 0 |
| mechanism | 5 | 0.42 | 0 | 0 | 5 |
| not_seen | 0 | 0.00 | 0 | 0 | 0 |
| seen_misread | 6 | 0.50 | 5 | 0 | 1 |
| rule_limit | 0 | 0.00 | 0 | 0 | 0 |

### dump-all（Argon）

10 incidents with origin or fault type wrong (0 classified without a reviewed label)

| category | count | share | easy | medium | hard |
|---|---:|---:|---:|---:|---:|
| no_answer | 1 | 0.10 | 0 | 0 | 1 |
| coverage | 0 | 0.00 | 0 | 0 | 0 |
| mechanism | 2 | 0.20 | 0 | 0 | 2 |
| not_seen | 0 | 0.00 | 0 | 0 | 0 |
| seen_misread | 7 | 0.70 | 4 | 0 | 3 |
| rule_limit | 0 | 0.00 | 0 | 0 | 0 |

### agent（Argon）

11 incidents with origin or fault type wrong (0 classified without a reviewed label)

| category | count | share | easy | medium | hard |
|---|---:|---:|---:|---:|---:|
| no_answer | 1 | 0.09 | 0 | 0 | 1 |
| coverage | 0 | 0.00 | 0 | 0 | 0 |
| mechanism | 2 | 0.18 | 0 | 0 | 2 |
| not_seen | 0 | 0.00 | 0 | 0 | 0 |
| seen_misread | 8 | 0.73 | 4 | 0 | 4 |
| rule_limit | 0 | 0.00 | 0 | 0 | 0 |

- 三個 Argon 方法的 `no_answer` 各 1：retrieval 與 dump-all 是方法自己提交的「沒有 fault」（同一個 incident），agent 是 §2 的 transport 放棄作答（另一個 incident）。
- Argon 的失敗以 `seen_misread` 為主（看過相關紀錄但判讀錯），`not_seen` 都是 0。

## 8. Evidence（decisions 013 §4、017；各層分開，永不合成）

- n = 有引用的 incident 數。existence、弱標籤（temporal / service / origin / weak）與 gold 分開列。
- gold（032 §5）：規則與 017 相同，每個方法每個 incident 最多抽 5 個引用（`GOLD_PER_METHOD`）。已在正式 604 項判定過的（同一個 id、t0、t1）沿用，不重判；
  新的 **475 項**由使用者盲標（標註者 `human:jingwen`，寫入時間 2026-11-01T06:48Z）：relevant 375、not relevant 100、略 0，未判定 0 項。
  - 呈現方式與正式 held-out 相同：不顯示方法名稱的精簡版，依 fault 分 10 組；工作表的背景資訊依 017（fault type、origin、affected、fault 時間）。
    使用者每組給答案與註記，主 session 只照答案用 `eval.explore gold-add` 寫入（`data/external/logs/explore-032/gold/`：原文 `answers.md`、寫入前檢查每個 incident
    的項數與註記和答案一致，抽查 26 項註記描述的紀錄與工作表一致），不代替判斷。註記照原文存在列到的每一項。
  - 新的判定另存在 ground truth 側的 `evidence_gold.explore-032.json`；正式的 `evidence_gold.json` 不變，所以 100 的 gold 數字不可能因此改變。
  - 使用者的註記有幾處對照了正式 gold 的同一筆紀錄（例如「與正式 gold … 一致」），作為一致性檢查。
- gold precision = 判定為相關 / 判定數，gold coverage = 判定數 / 引用數（017）。Argon 引用的紀錄比 qwen 多，每個方法每個 incident 只抽 5 個，所以 coverage 低於 qwen。
- gold 只改變 evidence 的 gold 欄位：gold 之前與之後的 `scores.json` 除了 gold 欄位之外沒有任何改變（備份在 `data/external/logs/explore-032/pre-gold/`）。
- gold 不是 Gate 條件。

### 總表（qwen 與 stat-anomaly 取自 100 §8）

| 方法 | n | existence | weak: temporal and service | weak: origin service | gold precision | gold coverage |
|---|---:|---:|---:|---:|---:|---:|
| stat-anomaly | 40 | 1.000 | 0.940 | 0.700 | 0.850 | 1.000 |
| retrieval qwen | 33 | 1.000 | 0.697 | 0.308 | 0.520 | 0.374 |
| retrieval Argon | 50 | 1.000 | 0.870 | 0.410 | 0.820 | 0.766 |
| dump-all qwen | 44 | 0.967 | 0.679 | 0.275 | 0.589 | 0.944 |
| dump-all Argon | 49 | 1.000 | 0.884 | 0.404 | 0.725 | 0.914 |
| agent qwen | 46 | 0.990 | 0.787 | 0.335 | 0.727 | 0.986 |
| agent Argon | 49 | 1.000 | 0.966 | 0.601 | 0.942 | 0.762 |

- 各方法的 n 不同，不是 paired 的比較；qwen 與 Argon 的 gold 是同一位標註者在不同時間、對不同樣本的判定。

### retrieval（Argon）

| layer | n incidents | mean | 95% interval |
|---|---:|---:|---|
| existence | 50 | 1.000 | [1.000, 1.000] |
| weak: temporal | 50 | 0.977 | [0.933, 1.000] |
| weak: affected service | 50 | 0.876 | [0.805, 0.939] |
| weak: origin service | 50 | 0.410 | [0.366, 0.454] |
| weak: temporal and service | 50 | 0.870 | [0.791, 0.937] |
| gold precision | 50 | 0.820 | [0.721, 0.904] |
| gold coverage | 50 | 0.766 | [0.706, 0.823] |

### dump-all（Argon）

| layer | n incidents | mean | 95% interval |
|---|---:|---:|---|
| existence | 49 | 1.000 | [1.000, 1.000] |
| weak: temporal | 49 | 0.944 | [0.883, 0.992] |
| weak: affected service | 49 | 0.936 | [0.877, 0.983] |
| weak: origin service | 49 | 0.404 | [0.349, 0.462] |
| weak: temporal and service | 49 | 0.884 | [0.806, 0.951] |
| gold precision | 49 | 0.725 | [0.604, 0.836] |
| gold coverage | 49 | 0.914 | [0.878, 0.948] |

### agent（Argon）

| layer | n incidents | mean | 95% interval |
|---|---:|---:|---|
| existence | 49 | 1.000 | [1.000, 1.000] |
| weak: temporal | 49 | 1.000 | [1.000, 1.000] |
| weak: affected service | 49 | 0.966 | [0.945, 0.985] |
| weak: origin service | 49 | 0.601 | [0.541, 0.661] |
| weak: temporal and service | 49 | 0.966 | [0.945, 0.985] |
| gold precision | 49 | 0.942 | [0.900, 0.977] |
| gold coverage | 49 | 0.762 | [0.707, 0.814] |

## 9. 預算、用量、可見資料與成本（SPEC §7、decision 024；只報告，不計分）

- tokens 與 latency 和正式執行不可比（不同的 tokenizer；網路加雲端 vs 本機 GPU）；proxy tokens（預算的單位）、工具呼叫數、可見紀錄數可比。

### 可比的用量（平均；qwen 取自 100 §9）

| 方法 | proxy_tokens qwen → Argon | tool_calls / retrievals qwen → Argon | records_seen qwen → Argon | 停止原因 qwen → Argon |
|---|---|---|---|---|
| retrieval | 20,356 → 38,519 | retrievals 4.080 → 6.760 | 45.160 → 132.820 | submitted 50 → submitted 50 |
| dump-all | 119,402 → 119,402 | - | 538.240 → 538.240 | invalid_submission 3、submitted 47 → submitted 50 |
| agent | 30,701 → 74,098 | tool_calls 23.120 → 35.592 | 107.940 → 438.041 | submitted 35、submitted_after_limit 12、turn_limit 3 → submitted 24、submitted_after_limit 25 |

- agent（Argon）一次回覆常平行呼叫多個工具，40 次工具呼叫的預算用得快：49 題中 25 題 `submitted_after_limit`（用完預算後被要求提交）。預算沒有改（032 §2）。

### retrieval（Argon）

Visible data: the per-minute overview, then the spans and logs found by at most q queries of k results each (decision 021 §3).
Model: gemini-4-argon. Budgets: queries 8, k 25.

| quantity | n | mean | median | max |
|---|---:|---:|---:|---:|
| tokens_in | 50 | 98,664 | 97,220 | 123,762 |
| tokens_out | 50 | 508.820 | 487.500 | 787.000 |
| proxy_tokens | 50 | 38,519 | 38,520 | 49,241 |
| tool_calls | 50 | 0.000 | 0.000 | 0.000 |
| retrievals | 50 | 6.760 | 7.000 | 8.000 |
| latency_s | 50 | 30.014 | 22.397 | 89.294 |
| cost_usd | 50 | 0.202 | 0.200 | 0.254 |

Total cost (USD): 10.12.
Replies: 100 (failed attempts included); prompt tokens 4,933,220 of which cached 0; output tokens 25,441 of which thinking 0; cost USD 10.12.

### dump-all（Argon）

Visible data: the per-minute overview, then error-level groups and a time-stratified sample, packed within the proxy-token budget (decision 021 §2).
Model: gemini-4-argon. Budgets: proxy_tokens 120000.

| quantity | n | mean | median | max |
|---|---:|---:|---:|---:|
| tokens_in | 50 | 223,928 | 224,026 | 226,324 |
| tokens_out | 50 | 250.100 | 232.500 | 1,172 |
| proxy_tokens | 50 | 119,402 | 119,406 | 119,518 |
| tool_calls | 50 | 0.000 | 0.000 | 0.000 |
| retrievals | 50 | 0.000 | 0.000 | 0.000 |
| latency_s | 50 | 24.802 | 16.817 | 88.212 |
| cost_usd | 50 | 0.450 | 0.450 | 0.461 |

Total cost (USD): 22.52.
Replies: 50 (failed attempts included); prompt tokens 11,196,412 of which cached 0; output tokens 12,505 of which thinking 0; cost USD 22.52.

### agent（Argon）

Visible data: any record of the snapshot through 7 read-only tools, within the tool-call, proxy-token and turn budgets (decision 019).
Model: gemini-4-argon. Budgets: tool_calls 40, proxy_tokens 120000, turns 30.

| quantity | n | mean | median | max |
|---|---:|---:|---:|---:|
| tokens_in | 49 | 512,847 | 468,991 | 1,239,072 |
| tokens_out | 49 | 1,418 | 1,423 | 1,983 |
| proxy_tokens | 49 | 74,098 | 74,861 | 119,982 |
| tool_calls | 49 | 35.592 | 39.000 | 40.000 |
| retrievals | 49 | 0.000 | 0.000 | 0.000 |
| latency_s | 49 | 224.247 | 136.134 | 1,748 |
| cost_usd | 49 | 0.380 | 0.331 | 1.300 |

Total cost (USD): -.
Replies: 389 (failed attempts included); prompt tokens 25,342,822 of which cached 17,037,928; output tokens 70,730 of which thinking 0; cost USD 19.02.

- agent 的「Total cost (USD): -」：補位的 `_abstain` 沒有 usage，凍結的報表程式在有缺值時印 `-`（`eval/runner.py` `_usage_lines`）。實際費用是「Replies」那一列的 $19.02（含失敗的嘗試）。
- agent 的「shown to the method」：records_seen 平均 438.041（中位數 388、最大 753）；overview_share 平均 0.930。retrieval 與 dump-all 的 overview_share 都是 1.000。

### 實際花費（試用抵免額，USD）

| 項目 | 費用 |
|---|---:|
| Gemini API 探測（033；HTTP 402，沒有產生用量） | 0 |
| Vertex 探測（034 §4） | 0.21 |
| 小診斷（035） | 0.0027 |
| 重跑探測（035 第 5 點） | 0.28 |
| Pilot（10 題 × 3 方法） | 10.125 |
| held-out（50 題 × 3 方法，含失敗的嘗試） | 51.660 |
| **合計** | **約 62.28** |

- 使用者批准的上限是 $150（032 §6 第 5 步，「批准上限 $150」）；執行程式在每次嘗試前與每題之後檢查累計費用，沒有觸發。
- 全部在 2026-12-01 漲價之前完成。

## 10. 與事前登記的差異與限制

1. **模型版本只釘到名稱（035 第 3 點）**：Vertex 回覆的 `model_version` 只是 `gemini-4-argon`，`models.get` 的 version 是 `default`。
   Pilot 與 held-out 共 649 次回覆都是 `gemini-4-argon`，但這抓不到 Google 在同一個名稱下更新模型。執行期間（2026-10-31 08:46Z – 15:30Z）是否有同名更新，無法確認。
2. **執行順序（036）**：實際是 dump-all → retrieval → agent，032 §2 登記的是 retrieval → agent → dump-all。在第一個 held-out 嘗試進行中發現，當時沒有任何 held-out 結果；
   沒有中斷、沒有重跑。每次呼叫彼此獨立（temperature 0、seed 42），預期不影響預測；可能受影響的是 latency、費用，以及若有同名更新（第 1 點）時哪個方法落在更新前後。
3. **設定檔的 sha256 沒有記在每次執行的紀錄裡**（寫本檔時發現，2026-11-01）：032 §4 寫「每次執行都記錄它的 sha256」，但 `run_config.json` 記的是設定的內容
   （provider、endpoint、model、thinking、temperature、seed、max_output_tokens、單價），沒有記檔案的 sha256。依 git 紀錄，`eval/llm_methods.explore-032.json`
   從 Vertex 設定（`677da55`，第一次付費的 Vertex 探測之前）到執行結束只改過 `status`、`cost_ceiling_usd` 與 `note`（`a3d0a91`、`04afdf3`）；執行時的檔案 sha256 是
   7d8ceb0bc9fbb981b53d12e5395ee78c9c0587c4e6a15abd314cd08c1b9cb92f（`04afdf3`）。設定在探測之後沒有改過。程式沒有修改，這裡只記錄差異。
4. **032 §3 設定的確認**（036「另記」）：使用者沒有另外回一句「確認第 3 節的設定」；探測報告寫明設定不變，使用者接著批准總額，記為確認。
5. **不是盲測**：這 50 個 incident 的正式結果在本實驗之前已經發布（100）。方法、prompt、工具、預算都沒有為這些 incident 調整，但同一組 held-out 現在用過兩次；
   要成為 Gate 等級的結論，需要新的 held-out 集合（023 §7，另寫 decision；032 §1 第 4 點）。
6. **只試一個模型、每個（方法, incident）只跑一次**（032 §1 第 2 點）：結果包含單次抽樣的變異，不能推廣到其他模型或同模型的其他版本。
7. **gold 的時間**：使用者在看到主要指標之後才盲標 gold（與正式 held-out 相同的順序）。工作表不顯示方法名稱；gold 不影響主要指標與 Gate 條件。
8. **transport 放棄作答**：agent 的 1 個放棄作答來自雲端呼叫逾時，不是模型的判斷；照登記的規則算 `no_answer`、算錯。
9. 六份配對比較、每份 4 個指標，都沒有做多重比較校正。

## 11. 不列 id；bootstrap 能說明與不能說明的範圍

- 本檔不列任何 held-out incident id 或 run group id；只用 fault。
- 區間：run-group cluster bootstrap（10,000 次、seed 0、percentile；013 §3）。paired 差異的兩個方法用同一組重抽的 run group（023 §7）。
- 能說明與不能說明的範圍同 100 §12（同一個 stack、traffic profile、10 個 fault 的條件下；不能推廣到其他 fault、variant 或系統；n 很小或比例接近 0、1 時區間會覆蓋不足）。
  另外，本實驗的區間不包含模型版本變動的不確定性（§10 第 1 點）。

## 12. 結論的寫法與下一步

- **探索性結果顯示**：在同樣這 50 個 held-out incident、同樣的方法、prompt 與預算下，把模型從 qwen3.5 9B（本機）換成 Gemini 4 Argon（Vertex AI），
  三個 LLM 方法的四個主要指標平均都較高（§3）。與同方法的 qwen 配對比較（§4）：fault_type、symptom_exact 三個方法的 95% 區間都在 0 以上；
  origin_top1 retrieval 與 agent 在 0 以上，dump-all 跨過 0；affected_f1 dump-all 與 agent 在 0 以上，retrieval 的下界是 0.000。
- **以 Gate 的三個條件描述**（§5）：條件 1（agent − stat-anomaly 的 origin_top1，下界 > 0）**未達成**：+0.160 [0.000, 0.320]。條件 2、3 達成。三個條件沒有同時達成。
  retrieval 與 dump-all 對 stat-anomaly 的 origin_top1 下界大於 0（0.040、0.020），但 Gate 條件 1 只定義在 agent 上（023 §7），這兩個只是描述。
- Argon 仍有的弱點：paymentUnreachable 的 origin（三個方法 0–1 / 5，stat-anomaly 5 / 5）；productCatalogLockContention 的 origin（agent 2 / 5、dump-all 2 / 5）；
  失敗以 `seen_misread` 為主（§7）。
- **Core 的結論不變**：Gate 判定仍是 100、031 的 NOT PASSED；本實驗不進 Advanced。之後是否做任何事（例如另開新的 held-out 集合）由使用者決定，需要另寫 decision。
