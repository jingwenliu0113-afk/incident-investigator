# 100 — Held-out 最終結果

- 狀態：結果報告，2026-10-31 新增（decision 030 預留的固定檔名）。**只寫一次**：之後發現的錯誤寫進新的 decision（031–099），本檔不改（030 §3）。
  它不是設計決策；放在 `docs/decisions/` 只因為 freeze 之後只有這裡能新增檔案（030 §1）。
- **Gate 判定：NOT PASSED**（decision 023 §7，只用第一次執行的結果）。下一步由使用者決定，記錄在同一個 commit 的 [decision 031](031-heldout-wrap-up.md)：照現在的結果收尾，不改題、不進 Advanced。
- 本檔只轉寫凍結工具寫出的檔案（030 §5）：不手算、不改寫、不新增指標或比較。表格照原檔（英文欄位）原樣轉寫；§4 的總表只是把四份 table.md 的同一列並排。
- 不列任何 held-out incident id 或 run group id（030 §4 第 12 項）：只用 slot 與 fault。

## 1. 範圍與來源

- held-out set（decision 023）：Pilot 的 10 個 fault 與 variant，每個 fault K = 5 個 slot，共 50 個 slot；slot 順序由 master seed 決定（`docs/heldout/slots.json`：master_seed 20261009，plan sha256:0a10496a9e3f72b4d783c1f738ed0e0c5443ee2b2233c076a6f040ee62360cf8）。
- freeze 紀錄：`docs/heldout/freeze.json`（sha256:7d68302545d958c4ba4d787e2d4f6fa558c954ccb27b7369f217b4b14d20cb39；frozen_from_commit `4b42a4a287a4cfea10bf4e0a32c9cbe000d34f59`，frozen_at 2026-10-16T13:47:17Z）。
- incident 清單：`heldout_incidents.json`（sha256:e606baae8b8944f1267e6296e7d9784620b952149b12f37e46dc99821a6140b5）：列入 50 個，排除 1 個（見 §4「排除與缺格」）。
- 數字來源（`data/external/` 不進 git）：`data/external/results/heldout/<method>/table.md` 與 `scores.json`（`eval score`）、`data/external/results/heldout/compare-agent-vs-stat-anomaly.md`（`eval compare`）、`data/external/results/heldout/agent/gate.md` 與 `gate.json`（`eval gate`）。這些檔案由凍結的工具在 held-out gold 完成之後（2026-10-30）寫出。
- `gate.json` 記錄的 inputs：
  - `scores_sha256` agent：sha256:2905d4626759fde62dc867f37a71ad957f1c8855603b9484379a94636cf5bc55
  - `scores_sha256` stat-anomaly：sha256:b7ce9349b1ec66b70968b238055bf14ba9c5023fd03d5c064be581b4c2998513
  - `compare_sha256` stat-anomaly：sha256:bd1ce82f2d0d42f7b869c43c2d09482d520ed87696a7514bd53e18fd8009c1df

## 2. 模型範圍

- 三個 LLM 方法（dump-all、retrieval、agent）用同一個本機模型（decision 029）。table.md 記錄的設定（三份相同）：

  > Model runtime (decision 029): ollama 0.35.0, qwen3.5:9b-q4_K_M @ sha256:6488c96fa5faab64bb65cbd30d4289e20e6130ef535a93ef9a49f42eda893ea7, num_ctx 262144, num_predict 8192, temperature 0, seed 42, think false; inference host gpu-server: the user's own RTX 5070 Ti desktop, reached through an SSH tunnel (decision 029 revision 1); cost 0 = no external cost.

- 推論在使用者的 RTX 5070 Ti 桌機（029 修訂 1），經 SSH tunnel；snapshot、ground truth 與評分留在 Mac。cost 0 = 沒有外部費用。
- **結論只限於這個本機模型**（qwen3.5 9B，q4_K_M），不推廣到其他模型；付費 API 模型延後，沒有執行。
- stat-anomaly 是統計 baseline（decision 014），不用模型。

## 3. 只用第一次執行的結果

- 每個（方法, incident）只跑一次（023 §5、§6），prediction 永不覆寫；只有 `api_error` / `transport_error` 依停止原因重試，最多 2 次嘗試。
- 四個方法都對 50 個列入的 incident 寫出 prediction（各方法 `scores.json` 的 `heldout.unanswered` 都是空的）。
- 嘗試次數（各方法 `attempts.jsonl` 的結束紀錄）：stat-anomaly 50、retrieval 50、dump-all 51、agent 50。
- 失敗的嘗試（各方法 table.md 的原文）：
  - stat-anomaly：`Failed attempts: 0 (tokens in 0, out 0, cost USD 0, latency s 0).`
  - retrieval：`Failed attempts: 0 (tokens in 0, out 0, cost USD 0, latency s 0).`
  - dump-all：`Failed attempts: 1 (tokens in 0, out 0, cost USD 0.0, latency s 95.48).`
  - agent：`Failed attempts: 0 (tokens in 0, out 0, cost USD 0, latency s 0).`
  - dump-all 的失敗嘗試是第 1 次、`transport_error`（`RemoteDisconnected: Remote end closed connection without response`）；同一個 incident 的第 2 次嘗試 `ok`。
- 放棄作答（022 的 `no_answer`）留在分母、照樣計分（013 §2、026 解讀 19）；各方法的次數見 §7。
- 方法 bug 的修正版：沒有（沒有任何探索性結果）。

## 4. 分層分數

各方法 table.md 的開頭（四份相同）：

> n = 50 incidents in 50 run groups; 95% interval: run-group cluster bootstrap (10000 resamples, seed 0).
>
> Labels: 50 reviewed (catalog+review), 0 a priori (catalog) (decision 018).

主要指標標 (main)，其餘是輔助指標；每格是平均與 95% 區間（四份 table.md 第一張表的同一列並排）。主要指標不合成一個數字（013 §2）。

| metric | stat-anomaly | retrieval | dump-all | agent |
|---|---|---|---|---|
| fault_type (main) | 0.320 [0.200, 0.460] | 0.480 [0.340, 0.620] | 0.460 [0.320, 0.600] | 0.480 [0.340, 0.620] |
| fault_family | 0.420 [0.280, 0.560] | 0.640 [0.500, 0.780] | 0.600 [0.460, 0.740] | 0.540 [0.400, 0.680] |
| origin_top1 (main) | 0.660 [0.520, 0.780] | 0.620 [0.480, 0.760] | 0.720 [0.600, 0.840] | 0.580 [0.440, 0.720] |
| origin_top3 | 1.000 [1.000, 1.000] | 0.640 [0.500, 0.760] | 0.720 [0.600, 0.840] | 0.580 [0.440, 0.720] |
| origin_rr | 0.810 [0.733, 0.880] | 0.627 [0.493, 0.760] | 0.720 [0.600, 0.840] | 0.580 [0.440, 0.720] |
| affected_precision | 0.949 [0.891, 0.991] | 0.830 [0.740, 0.908] | 0.818 [0.719, 0.904] | 0.715 [0.599, 0.821] |
| affected_recall | 0.737 [0.660, 0.810] | 0.872 [0.795, 0.937] | 0.742 [0.647, 0.830] | 0.757 [0.653, 0.855] |
| affected_f1 (main) | 0.800 [0.739, 0.857] | 0.811 [0.732, 0.881] | 0.738 [0.648, 0.819] | 0.697 [0.593, 0.795] |
| affected_jaccard | 0.714 [0.639, 0.788] | 0.750 [0.662, 0.832] | 0.667 [0.568, 0.761] | 0.640 [0.531, 0.743] |
| symptom_exact (main) | 0.400 [0.260, 0.540] | 0.500 [0.360, 0.640] | 0.460 [0.320, 0.600] | 0.460 [0.320, 0.600] |
| symptom_jaccard | 0.500 [0.380, 0.620] | 0.600 [0.480, 0.720] | 0.550 [0.430, 0.670] | 0.560 [0.440, 0.680] |

### 難度層（decision 015；有 ≥ 10 個 run group 的層才有區間，023 §7）

**stat-anomaly**

| difficulty | n | fault_type | origin_top1 | affected_f1 | symptom_exact |
|---|---:|---:|---:|---:|---:|
| easy | 25 | 0.240 [0.080, 0.400] | 0.600 [0.400, 0.800] | 0.856 [0.805, 0.906] | 0.400 [0.200, 0.600] |
| medium | 1 | 1.000 | 0.000 | 0.444 | 0.000 |
| hard | 24 | 0.375 [0.208, 0.583] | 0.750 [0.583, 0.917] | 0.757 [0.653, 0.854] | 0.417 [0.208, 0.625] |

**retrieval**

| difficulty | n | fault_type | origin_top1 | affected_f1 | symptom_exact |
|---|---:|---:|---:|---:|---:|
| easy | 25 | 0.640 [0.440, 0.840] | 0.840 [0.680, 0.960] | 0.940 [0.897, 0.978] | 0.600 [0.400, 0.800] |
| medium | 1 | 1.000 | 0.000 | 0.444 | 1.000 |
| hard | 24 | 0.292 [0.125, 0.500] | 0.417 [0.208, 0.625] | 0.691 [0.556, 0.813] | 0.375 [0.208, 0.583] |

**dump-all**

| difficulty | n | fault_type | origin_top1 | affected_f1 | symptom_exact |
|---|---:|---:|---:|---:|---:|
| easy | 25 | 0.800 [0.640, 0.960] | 1.000 [1.000, 1.000] | 0.949 [0.907, 0.987] | 0.600 [0.400, 0.800] |
| medium | 1 | 1.000 | 0.000 | 0.333 | 1.000 |
| hard | 24 | 0.083 [0.000, 0.208] | 0.458 [0.250, 0.667] | 0.534 [0.413, 0.656] | 0.292 [0.125, 0.458] |

**agent**

| difficulty | n | fault_type | origin_top1 | affected_f1 | symptom_exact |
|---|---:|---:|---:|---:|---:|
| easy | 25 | 0.800 [0.640, 0.960] | 0.840 [0.680, 0.960] | 0.901 [0.842, 0.950] | 0.600 [0.400, 0.800] |
| medium | 1 | 1.000 | 0.000 | 0.545 | 1.000 |
| hard | 24 | 0.125 [0.000, 0.250] | 0.333 [0.167, 0.542] | 0.492 [0.327, 0.655] | 0.292 [0.125, 0.500] |

### 排除與缺格

- 排除 1 個 slot 的 incident：slot H21（intlShippingSlowdown 10sec），原因 `fault not exercised (016 §5, 023 §5.3)`；該 slot 依 023 §5.3 重收一次，重收的 incident 列入清單（所以每個 fault 都是 5 / 5）。
- 詞彙命中而排除的 incident：沒有（`eval leakage --set heldout` 的 lexicon hits 全部是 0）。
- 關閉的 slot：沒有；Pilot 之後移除的 fault：沒有（compare 輸出 `Faults removed after the Pilot: none.`、`Slots closed: none.`）。

## 5. Gate（`eval gate --method agent --against stat-anomaly --set heldout` 的 gate.md 原文）

> Held-out set: this is the Gate decision of decision 023 §7 (SPEC Gate, entering Advanced), from first-run results only: each method ran once per listed incident under the freeze record (decision 023 §5, §6).

Gate decision: NOT PASSED.

| condition | value | |
|---|---|---|
| 1: origin_top1 of agent minus each statistical baseline, paired 95% lower bound > 0 | agent - stat-anomaly: mean -0.080, 95% interval [-0.280, 0.120], n 50 | not met |
| 2: a fault with origin_top1 wrong on >= ceil(K/2) incidents, more than half of them in one decision-022 category | intlShippingSlowdown 10sec: 4 of 4 wrong are seen_misread (K 5); paymentUnreachable on: 4 of 4 wrong are seen_misread (K 5); productCatalogLockContention on: 3 of 3 wrong are seen_misread (K 5) | met |
| 3: not_seen + seen_misread > 0.5 of the failures (decision 022) | 17 of 32 failures = 0.53 | met |

### Condition 2 by fault

| fault | scored | K | ceil(K/2) | origin wrong | categories of the wrong origins | met |
|---|---:|---:|---:|---:|---|---|
| adHighCpu on | 5 | 5 | 3 | 4 | no_answer 1, not_seen 2, seen_misread 1 | no |
| adManualGc on | 5 | 5 | 3 | 1 | no_answer 1 | no |
| cartFailure 100% | 5 | 5 | 3 | 0 | - | no |
| emailMemoryLeak 1000x | 5 | 5 | 3 | 5 | no_answer 2, not_seen 1, seen_misread 2 | no |
| intlShippingSlowdown 10sec | 5 | 5 | 3 | 4 | seen_misread 4 | yes |
| paymentFailure 100% | 5 | 5 | 3 | 0 | - | no |
| paymentUnreachable on | 5 | 5 | 3 | 4 | seen_misread 4 | yes |
| productCatalogFailure on | 5 | 5 | 3 | 0 | - | no |
| productCatalogLockContention on | 5 | 5 | 3 | 3 | seen_misread 3 | yes |
| recommendationCacheFailure on | 5 | 5 | 3 | 0 | - | no |

### Descriptive only (not Gate criteria)

- Coverage (SPEC Gate "收尾或改題"; no threshold): 0 of 32 failures = 0.00; 0 failures classified without a reviewed label (decision 022 §2); 32 failures among 50 scored incidents.
- agent - stat-anomaly, other main metrics (fault_type is never a Gate criterion, decision 023 §7): fault_type 0.160 [-0.020, 0.340], affected_f1 -0.103 [-0.222, 0.007], symptom_exact 0.060 [-0.160, 0.280].
- Leave one fault out (agent - stat-anomaly, origin_top1 lower bound): adHighCpu on -0.222, adManualGc on -0.289, cartFailure 100% -0.400, emailMemoryLeak 1000x -0.222, intlShippingSlowdown 10sec -0.244, paymentFailure 100% -0.311, paymentUnreachable on -0.200, productCatalogFailure on -0.400, productCatalogLockContention on -0.356, recommendationCacheFailure on -0.311.

#### origin_top1 by fault: right k of K, agent and stat-anomaly (decision 023 §7 robustness report; descriptive only)

direction: the sign of agent - stat-anomaly over the fault's incidents scored for both (no direction without one).

| fault | agent right / K | stat-anomaly right / K | paired | direction |
|---|---:|---:|---:|---|
| adHighCpu on | 1 / 5 | 5 / 5 | 5 | - |
| adManualGc on | 4 / 5 | 5 / 5 | 5 | - |
| cartFailure 100% | 5 / 5 | 0 / 5 | 5 | + |
| emailMemoryLeak 1000x | 0 / 5 | 4 / 5 | 5 | - |
| intlShippingSlowdown 10sec | 1 / 5 | 4 / 5 | 5 | - |
| paymentFailure 100% | 5 / 5 | 5 / 5 | 5 | 0 |
| paymentUnreachable on | 1 / 5 | 5 / 5 | 5 | - |
| productCatalogFailure on | 5 / 5 | 0 / 5 | 5 | + |
| productCatalogLockContention on | 2 / 5 | 0 / 5 | 5 | + |
| recommendationCacheFailure on | 5 / 5 | 5 / 5 | 5 | 0 |

Freeze record sha256:7d68302545d958c4ba4d787e2d4f6fa558c954ccb27b7369f217b4b14d20cb39; incident list sha256:e606baae8b8944f1267e6296e7d9784620b952149b12f37e46dc99821a6140b5.

Inputs: agent scores sha256:2905d4626759fde62dc867f37a71ad957f1c8855603b9484379a94636cf5bc55, stat-anomaly scores sha256:b7ce9349b1ec66b70968b238055bf14ba9c5023fd03d5c064be581b4c2998513.

### paired 差異與 leave-one-fault-out（compare-agent-vs-stat-anomaly.md 原文；條件 1 之外都只是描述）

| metric | n | mean difference | 95% interval |
|---|---:|---:|---|
| fault_type | 50 | 0.160 | [-0.020, 0.340] |
| origin_top1 | 50 | -0.080 | [-0.280, 0.120] |
| affected_f1 | 50 | -0.103 | [-0.222, 0.007] |
| symptom_exact | 50 | 0.060 | [-0.160, 0.280] |

Leave one fault out (descriptive): lower bound of the interval without each fault

| metric | fault left out | n | mean difference | lower bound |
|---|---|---:|---:|---:|
| fault_type | adHighCpu on | 45 | 0.267 | 0.111 |
| fault_type | adManualGc on | 45 | 0.178 | -0.022 |
| fault_type | cartFailure 100% | 45 | 0.067 | -0.111 |
| fault_type | emailMemoryLeak 1000x | 45 | 0.156 | -0.044 |
| fault_type | intlShippingSlowdown 10sec | 45 | 0.244 | 0.067 |
| fault_type | paymentFailure 100% | 45 | 0.178 | -0.022 |
| fault_type | paymentUnreachable on | 45 | 0.067 | -0.111 |
| fault_type | productCatalogFailure on | 45 | 0.089 | -0.089 |
| fault_type | productCatalogLockContention on | 45 | 0.178 | -0.022 |
| fault_type | recommendationCacheFailure on | 45 | 0.178 | -0.022 |
| origin_top1 | adHighCpu on | 45 | 0.000 | -0.222 |
| origin_top1 | adManualGc on | 45 | -0.067 | -0.289 |
| origin_top1 | cartFailure 100% | 45 | -0.200 | -0.400 |
| origin_top1 | emailMemoryLeak 1000x | 45 | 0.000 | -0.222 |
| origin_top1 | intlShippingSlowdown 10sec | 45 | -0.022 | -0.244 |
| origin_top1 | paymentFailure 100% | 45 | -0.089 | -0.311 |
| origin_top1 | paymentUnreachable on | 45 | 0.000 | -0.200 |
| origin_top1 | productCatalogFailure on | 45 | -0.200 | -0.400 |
| origin_top1 | productCatalogLockContention on | 45 | -0.133 | -0.356 |
| origin_top1 | recommendationCacheFailure on | 45 | -0.089 | -0.311 |
| affected_f1 | adHighCpu on | 45 | -0.033 | -0.137 |
| affected_f1 | adManualGc on | 45 | -0.136 | -0.252 |
| affected_f1 | cartFailure 100% | 45 | -0.102 | -0.228 |
| affected_f1 | emailMemoryLeak 1000x | 45 | -0.054 | -0.164 |
| affected_f1 | intlShippingSlowdown 10sec | 45 | -0.114 | -0.236 |
| affected_f1 | paymentFailure 100% | 45 | -0.150 | -0.271 |
| affected_f1 | paymentUnreachable on | 45 | -0.119 | -0.246 |
| affected_f1 | productCatalogFailure on | 45 | -0.097 | -0.225 |
| affected_f1 | productCatalogLockContention on | 45 | -0.094 | -0.220 |
| affected_f1 | recommendationCacheFailure on | 45 | -0.127 | -0.255 |
| symptom_exact | adHighCpu on | 45 | 0.178 | -0.044 |
| symptom_exact | adManualGc on | 45 | -0.022 | -0.244 |
| symptom_exact | cartFailure 100% | 45 | 0.178 | -0.044 |
| symptom_exact | emailMemoryLeak 1000x | 45 | 0.156 | -0.067 |
| symptom_exact | intlShippingSlowdown 10sec | 45 | 0.000 | -0.222 |
| symptom_exact | paymentFailure 100% | 45 | -0.044 | -0.267 |
| symptom_exact | paymentUnreachable on | 45 | -0.044 | -0.267 |
| symptom_exact | productCatalogFailure on | 45 | 0.067 | -0.178 |
| symptom_exact | productCatalogLockContention on | 45 | 0.067 | -0.178 |
| symptom_exact | recommendationCacheFailure on | 45 | 0.067 | -0.178 |

Faults removed after the Pilot: none.
Slots closed: none.

## 6. 各 fault 表（023 §7、Gate 解讀 10；描述用，沒有區間）

### stat-anomaly

equal weight: the mean of the per-fault means over the 10 faults with a scored incident; incidents: the mean over every scored incident (the reported estimate, decision 023 §7).

scored / K: the fault's scored incidents of its K (a count of incidents, not of right answers).

| fault | scored / K | fault_type | origin_top1 | affected_f1 | symptom_exact |
|---|---:|---:|---:|---:|---:|
| adHighCpu on | 5 / 5 | 1.000 | 1.000 | 0.933 | 1.000 |
| adManualGc on | 5 / 5 | 0.000 | 1.000 | 0.500 | 0.000 |
| cartFailure 100% | 5 / 5 | 0.000 | 0.000 | 1.000 | 1.000 |
| emailMemoryLeak 1000x | 5 / 5 | 0.000 | 0.800 | 0.667 | 1.000 |
| intlShippingSlowdown 10sec | 5 / 5 | 1.000 | 0.800 | 0.622 | 0.000 |
| paymentFailure 100% | 5 / 5 | 1.000 | 1.000 | 0.679 | 0.000 |
| paymentUnreachable on | 5 / 5 | 0.000 | 1.000 | 0.800 | 0.000 |
| productCatalogFailure on | 5 / 5 | 0.200 | 0.000 | 1.000 | 1.000 |
| productCatalogLockContention on | 5 / 5 | 0.000 | 0.000 | 1.000 | 0.000 |
| recommendationCacheFailure on | 5 / 5 | 0.000 | 1.000 | 0.800 | 0.000 |
| equal weight (10 faults) | | 0.320 | 0.660 | 0.800 | 0.400 |
| incidents | | 0.320 | 0.660 | 0.800 | 0.400 |

Missing cells: none.

### retrieval

equal weight: the mean of the per-fault means over the 10 faults with a scored incident; incidents: the mean over every scored incident (the reported estimate, decision 023 §7).

scored / K: the fault's scored incidents of its K (a count of incidents, not of right answers).

| fault | scored / K | fault_type | origin_top1 | affected_f1 | symptom_exact |
|---|---:|---:|---:|---:|---:|
| adHighCpu on | 5 / 5 | 0.600 | 0.800 | 0.257 | 0.000 |
| adManualGc on | 5 / 5 | 0.000 | 1.000 | 0.771 | 1.000 |
| cartFailure 100% | 5 / 5 | 0.600 | 0.800 | 0.867 | 0.000 |
| emailMemoryLeak 1000x | 5 / 5 | 0.000 | 0.000 | 0.674 | 0.000 |
| intlShippingSlowdown 10sec | 5 / 5 | 1.000 | 0.000 | 0.771 | 1.000 |
| paymentFailure 100% | 5 / 5 | 1.000 | 1.000 | 0.943 | 1.000 |
| paymentUnreachable on | 5 / 5 | 0.600 | 0.600 | 0.960 | 1.000 |
| productCatalogFailure on | 5 / 5 | 1.000 | 0.800 | 0.971 | 1.000 |
| productCatalogLockContention on | 5 / 5 | 0.000 | 0.200 | 0.932 | 0.000 |
| recommendationCacheFailure on | 5 / 5 | 0.000 | 1.000 | 0.960 | 0.000 |
| equal weight (10 faults) | | 0.480 | 0.620 | 0.811 | 0.500 |
| incidents | | 0.480 | 0.620 | 0.811 | 0.500 |

Missing cells: none.

### dump-all

equal weight: the mean of the per-fault means over the 10 faults with a scored incident; incidents: the mean over every scored incident (the reported estimate, decision 023 §7).

scored / K: the fault's scored incidents of its K (a count of incidents, not of right answers).

| fault | scored / K | fault_type | origin_top1 | affected_f1 | symptom_exact |
|---|---:|---:|---:|---:|---:|
| adHighCpu on | 5 / 5 | 0.000 | 1.000 | 0.600 | 0.000 |
| adManualGc on | 5 / 5 | 0.000 | 1.000 | 0.700 | 1.000 |
| cartFailure 100% | 5 / 5 | 1.000 | 1.000 | 1.000 | 0.000 |
| emailMemoryLeak 1000x | 5 / 5 | 0.000 | 0.000 | 0.533 | 0.000 |
| intlShippingSlowdown 10sec | 5 / 5 | 0.600 | 0.000 | 0.261 | 0.600 |
| paymentFailure 100% | 5 / 5 | 1.000 | 1.000 | 1.000 | 1.000 |
| paymentUnreachable on | 5 / 5 | 1.000 | 1.000 | 1.000 | 1.000 |
| productCatalogFailure on | 5 / 5 | 1.000 | 1.000 | 0.867 | 1.000 |
| productCatalogLockContention on | 5 / 5 | 0.000 | 0.200 | 0.538 | 0.000 |
| recommendationCacheFailure on | 5 / 5 | 0.000 | 1.000 | 0.880 | 0.000 |
| equal weight (10 faults) | | 0.460 | 0.720 | 0.738 | 0.460 |
| incidents | | 0.460 | 0.720 | 0.738 | 0.460 |

Missing cells: none.

### agent

equal weight: the mean of the per-fault means over the 10 faults with a scored incident; incidents: the mean over every scored incident (the reported estimate, decision 023 §7).

scored / K: the fault's scored incidents of its K (a count of incidents, not of right answers).

| fault | scored / K | fault_type | origin_top1 | affected_f1 | symptom_exact |
|---|---:|---:|---:|---:|---:|
| adHighCpu on | 5 / 5 | 0.200 | 0.200 | 0.200 | 0.000 |
| adManualGc on | 5 / 5 | 0.000 | 0.800 | 0.700 | 0.800 |
| cartFailure 100% | 5 / 5 | 1.000 | 1.000 | 0.889 | 0.000 |
| emailMemoryLeak 1000x | 5 / 5 | 0.200 | 0.000 | 0.127 | 0.200 |
| intlShippingSlowdown 10sec | 5 / 5 | 0.400 | 0.200 | 0.621 | 0.600 |
| paymentFailure 100% | 5 / 5 | 1.000 | 1.000 | 1.000 | 1.000 |
| paymentUnreachable on | 5 / 5 | 1.000 | 0.200 | 0.848 | 1.000 |
| productCatalogFailure on | 5 / 5 | 1.000 | 1.000 | 0.848 | 1.000 |
| productCatalogLockContention on | 5 / 5 | 0.000 | 0.400 | 0.822 | 0.000 |
| recommendationCacheFailure on | 5 / 5 | 0.000 | 1.000 | 0.920 | 0.000 |
| equal weight (10 faults) | | 0.480 | 0.580 | 0.697 | 0.460 |
| incidents | | 0.480 | 0.580 | 0.697 | 0.460 |

Missing cells: none.

## 7. 失敗分類（decision 022）

各方法 table.md「Failures」段的類別表（逐 incident 的列表含 incident id，不轉寫）。不只報成功的案例：四個方法的失敗都列出。

### stat-anomaly

36 incidents with origin or fault type wrong (0 classified without a reviewed label)

| category | count | share | easy | medium | hard |
|---|---:|---:|---:|---:|---:|
| no_answer | 0 | 0.00 | 0 | 0 | 0 |
| coverage | 0 | 0.00 | 0 | 0 | 0 |
| mechanism | 19 | 0.53 | 10 | 0 | 9 |
| not_seen | 0 | 0.00 | 0 | 0 | 0 |
| seen_misread | 0 | 0.00 | 0 | 0 | 0 |
| rule_limit | 17 | 0.47 | 10 | 1 | 6 |

### retrieval

34 incidents with origin or fault type wrong (0 classified without a reviewed label)

| category | count | share | easy | medium | hard |
|---|---:|---:|---:|---:|---:|
| no_answer | 0 | 0.00 | 0 | 0 | 0 |
| coverage | 0 | 0.00 | 0 | 0 | 0 |
| mechanism | 15 | 0.44 | 8 | 0 | 7 |
| not_seen | 0 | 0.00 | 0 | 0 | 0 |
| seen_misread | 19 | 0.56 | 4 | 1 | 14 |
| rule_limit | 0 | 0.00 | 0 | 0 | 0 |

### dump-all

30 incidents with origin or fault type wrong (0 classified without a reviewed label)

| category | count | share | easy | medium | hard |
|---|---:|---:|---:|---:|---:|
| no_answer | 3 | 0.10 | 0 | 0 | 3 |
| coverage | 0 | 0.00 | 0 | 0 | 0 |
| mechanism | 16 | 0.53 | 5 | 0 | 11 |
| not_seen | 0 | 0.00 | 0 | 0 | 0 |
| seen_misread | 11 | 0.37 | 0 | 1 | 10 |
| rule_limit | 0 | 0.00 | 0 | 0 | 0 |

### agent

32 incidents with origin or fault type wrong (0 classified without a reviewed label)

| category | count | share | easy | medium | hard |
|---|---:|---:|---:|---:|---:|
| no_answer | 4 | 0.12 | 0 | 0 | 4 |
| coverage | 0 | 0.00 | 0 | 0 | 0 |
| mechanism | 11 | 0.34 | 5 | 0 | 6 |
| not_seen | 3 | 0.09 | 0 | 0 | 3 |
| seen_misread | 14 | 0.44 | 4 | 1 | 9 |
| rule_limit | 0 | 0.00 | 0 | 0 | 0 |

Agent 各 fault 的類別見 §5「Condition 2 by fault」：那張表只算 origin 答錯的 incident（023「實作說明：Gate 計算」解讀 5），只有 fault_type 錯的 `mechanism` 不在其中。

## 8. Evidence（decisions 013 §4、017；各層分開，永不合成）

- n = 有引用的 incident 數。existence、弱標籤（temporal / service / origin / weak）與 gold 分開列。
- gold 由使用者盲標（017 §3）：標註者 `human:jingwen`（2026-10-26 至 10-30），看的是不顯示方法名稱的工作表。每個方法每個 incident 最多抽 5 個引用（017，`GOLD_PER_METHOD`），各方法的樣本合併、同一個 (id, t0, t1) 只判一次：共 604 項（各 incident 的 `evidence_gold.json`，由 `eval gold-add` 寫入），未判定 0 項。
- 四個方法的樣本都全部判定，所以四個方法都報 gold precision（017「對實驗的影響」）。gold precision = 判定為相關 / 判定數，gold coverage = 判定數 / 引用數（017）。
- 工作表每個 metric 最多列引用範圍內前 20 個點、trace 最多 20 個 span（與 Pilot 相同的工作表格式）。
- gold 不是 Gate 條件。

### stat-anomaly

| layer | n incidents | mean | 95% interval |
|---|---:|---:|---|
| existence | 40 | 1.000 | [1.000, 1.000] |
| weak: temporal | 40 | 0.965 | [0.920, 1.000] |
| weak: affected service | 40 | 0.975 | [0.925, 1.000] |
| weak: origin service | 40 | 0.700 | [0.550, 0.825] |
| weak: temporal and service | 40 | 0.940 | [0.870, 0.995] |
| gold precision | 40 | 0.850 | [0.745, 0.940] |
| gold coverage | 40 | 1.000 | [1.000, 1.000] |

### retrieval

| layer | n incidents | mean | 95% interval |
|---|---:|---:|---|
| existence | 33 | 1.000 | [1.000, 1.000] |
| weak: temporal | 33 | 0.832 | [0.721, 0.928] |
| weak: affected service | 33 | 0.803 | [0.678, 0.916] |
| weak: origin service | 33 | 0.308 | [0.215, 0.411] |
| weak: temporal and service | 33 | 0.697 | [0.550, 0.833] |
| gold precision | 33 | 0.520 | [0.353, 0.681] |
| gold coverage | 33 | 0.374 | [0.262, 0.496] |

### dump-all

| layer | n incidents | mean | 95% interval |
|---|---:|---:|---|
| existence | 44 | 0.967 | [0.927, 1.000] |
| weak: temporal | 44 | 0.766 | [0.644, 0.874] |
| weak: affected service | 44 | 0.807 | [0.693, 0.909] |
| weak: origin service | 44 | 0.275 | [0.200, 0.354] |
| weak: temporal and service | 44 | 0.679 | [0.545, 0.806] |
| gold precision | 44 | 0.589 | [0.443, 0.727] |
| gold coverage | 44 | 0.944 | [0.894, 0.985] |

### agent

| layer | n incidents | mean | 95% interval |
|---|---:|---:|---|
| existence | 46 | 0.990 | [0.975, 1.000] |
| weak: temporal | 46 | 0.897 | [0.820, 0.961] |
| weak: affected service | 46 | 0.822 | [0.710, 0.920] |
| weak: origin service | 46 | 0.335 | [0.233, 0.440] |
| weak: temporal and service | 46 | 0.787 | [0.676, 0.887] |
| gold precision | 46 | 0.727 | [0.604, 0.840] |
| gold coverage | 46 | 0.986 | [0.967, 1.000] |

## 9. 預算、用量與可見資料（SPEC §7、decision 024；只報告，不計分）

各方法 table.md「Budgets, usage and visible data」段原文。

### stat-anomaly

Visible data: every span, log and container metric of the snapshot, but only as per-service, per-minute aggregates (decision 014).
Model: -. Budgets: none.

Usage over the 50 scored incidents:

| quantity | n | mean | median | max |
|---|---:|---:|---:|---:|
| tokens_in | 0 | - | - | - |
| tokens_out | 0 | - | - | - |
| proxy_tokens | 0 | - | - | - |
| tool_calls | 50 | 0.000 | 0.000 | 0.000 |
| retrievals | 50 | 0.000 | 0.000 | 0.000 |
| latency_s | 50 | 1.368 | 1.437 | 1.742 |
| cost_usd | 50 | 0.000 | 0.000 | 0.000 |

Total cost (USD): 0.00.
Exposure: no exposure log (the method's visible data is described above).

### retrieval

Visible data: the per-minute overview, then the spans and logs found by at most q queries of k results each (decision 021 §3).
Model: qwen3.5:9b-q4_K_M. Budgets: queries 8, k 25.
Model runtime (decision 029): ollama 0.35.0, qwen3.5:9b-q4_K_M @ sha256:6488c96fa5faab64bb65cbd30d4289e20e6130ef535a93ef9a49f42eda893ea7, num_ctx 262144, num_predict 8192, temperature 0, seed 42, think false; inference host gpu-server: the user's own RTX 5070 Ti desktop, reached through an SSH tunnel (decision 029 revision 1); cost 0 = no external cost.

Usage over the 50 scored incidents:

| quantity | n | mean | median | max |
|---|---:|---:|---:|---:|
| tokens_in | 50 | 95,603 | 96,590 | 182,143 |
| tokens_out | 50 | 1,538 | 959.500 | 11,207 |
| proxy_tokens | 50 | 20,356 | 18,528 | 34,900 |
| tool_calls | 50 | 0.000 | 0.000 | 0.000 |
| retrievals | 50 | 4.080 | 4.000 | 5.000 |
| latency_s | 50 | 59.721 | 55.807 | 241.932 |
| cost_usd | 50 | 0.000 | 0.000 | 0.000 |

Total cost (USD): 0.00.
Inference host: gpu-server (the user's RTX 5070 Ti desktop on mains power, through an SSH tunnel; decision 029 revision 1): the GPU state was read before and after all 50 timed incidents; the Mac's power mode is not a condition of this run.
GPU (nvidia-smi before and after each incident): NVIDIA GeForce RTX 5070 Ti, driver 617.42, power limit 300 W.
Stop reasons: submitted 50.

| shown to the method, per incident | n | mean | median | max |
|---|---:|---:|---:|---:|
| records_seen | 50 | 45.160 | 29.000 | 125.000 |
| records_share | 50 | 0.000 | 0.000 | 0.001 |
| overview_share | 50 | 1.000 | 1.000 | 1.000 |

### dump-all

Visible data: the per-minute overview, then error-level groups and a time-stratified sample, packed within the proxy-token budget (decision 021 §2).
Model: qwen3.5:9b-q4_K_M. Budgets: proxy_tokens 120000.
Model runtime (decision 029): ollama 0.35.0, qwen3.5:9b-q4_K_M @ sha256:6488c96fa5faab64bb65cbd30d4289e20e6130ef535a93ef9a49f42eda893ea7, num_ctx 262144, num_predict 8192, temperature 0, seed 42, think false; inference host gpu-server: the user's own RTX 5070 Ti desktop, reached through an SSH tunnel (decision 029 revision 1); cost 0 = no external cost.

Usage over the 50 scored incidents:

| quantity | n | mean | median | max |
|---|---:|---:|---:|---:|
| tokens_in | 50 | 469,149 | 422,718 | 641,486 |
| tokens_out | 50 | 542.300 | 443.500 | 1,915 |
| proxy_tokens | 50 | 119,402 | 119,406 | 119,518 |
| tool_calls | 50 | 0.000 | 0.000 | 0.000 |
| retrievals | 50 | 0.000 | 0.000 | 0.000 |
| latency_s | 50 | 131.966 | 129.743 | 186.644 |
| cost_usd | 50 | 0.000 | 0.000 | 0.000 |

Total cost (USD): 0.00.
Inference host: gpu-server (the user's RTX 5070 Ti desktop on mains power, through an SSH tunnel; decision 029 revision 1): the GPU state was read before and after all 50 timed incidents; the Mac's power mode is not a condition of this run.
GPU (nvidia-smi before and after each incident): NVIDIA GeForce RTX 5070 Ti, driver 617.42, power limit 300 W.
Stop reasons: invalid_submission 3, submitted 47.

| shown to the method, per incident | n | mean | median | max |
|---|---:|---:|---:|---:|
| records_seen | 50 | 538.240 | 537.000 | 560.000 |
| records_share | 50 | 0.002 | 0.002 | 0.002 |
| overview_share | 50 | 1.000 | 1.000 | 1.000 |

### agent

Visible data: any record of the snapshot through 7 read-only tools, within the tool-call, proxy-token and turn budgets (decision 019).
Model: qwen3.5:9b-q4_K_M. Budgets: tool_calls 40, proxy_tokens 120000, turns 30.
Model runtime (decision 029): ollama 0.35.0, qwen3.5:9b-q4_K_M @ sha256:6488c96fa5faab64bb65cbd30d4289e20e6130ef535a93ef9a49f42eda893ea7, num_ctx 262144, num_predict 8192, temperature 0, seed 42, think false; inference host gpu-server: the user's own RTX 5070 Ti desktop, reached through an SSH tunnel (decision 029 revision 1); cost 0 = no external cost.

Usage over the 50 scored incidents:

| quantity | n | mean | median | max |
|---|---:|---:|---:|---:|
| tokens_in | 50 | 765,037 | 799,320 | 1,413,063 |
| tokens_out | 50 | 3,507 | 2,972 | 21,292 |
| proxy_tokens | 50 | 30,701 | 29,846 | 48,167 |
| tool_calls | 50 | 23.120 | 26.000 | 30.000 |
| retrievals | 50 | 0.000 | 0.000 | 0.000 |
| latency_s | 50 | 103.388 | 91.967 | 442.494 |
| cost_usd | 50 | 0.000 | 0.000 | 0.000 |

Total cost (USD): 0.00.
Inference host: gpu-server (the user's RTX 5070 Ti desktop on mains power, through an SSH tunnel; decision 029 revision 1): the GPU state was read before and after all 50 timed incidents; the Mac's power mode is not a condition of this run.
GPU (nvidia-smi before and after each incident): NVIDIA GeForce RTX 5070 Ti, driver 617.42, power limit 300 W.
Stop reasons: submitted 35, submitted_after_limit 12, turn_limit 3.

| shown to the method, per incident | n | mean | median | max |
|---|---:|---:|---:|---:|
| records_seen | 50 | 107.940 | 111.500 | 264.000 |
| records_share | 50 | 0.000 | 0.000 | 0.001 |
| overview_share | 50 | 0.531 | 0.505 | 1.000 |

latency 的量測條件（各方法 `scores.json` 的 `usage.latency_power`；029 修訂 1）：

- stat-anomaly：`null`（統計 baseline，沒有本機模型；029）。
- retrieval：host `gpu-server`，incidents_timed 50，not_formal 0，failed_not_formal 0。
- dump-all：host `gpu-server`，incidents_timed 50，not_formal 0，failed_not_formal 0。
- agent：host `gpu-server`，incidents_timed 50，not_formal 0，failed_not_formal 0。

## 10. 評測之後發現的 bug（023 §6）

- 沒有。評分或稽核沒有發現 bug；freeze 之後沒有改任何程式（發布前 `collect status --set heldout` 的 `freeze_problems` 是 `[]`），沒有修正前後的數字要報告。

## 11. Pilot 分開報

- Pilot 的數字只當診斷，不是 Gate 判定，永不與 held-out 合併（SPEC §5、013 §3）：見封存的 [README「結果」](../../README.md#結果)。

## 12. 不列 id；bootstrap 能說明與不能說明的範圍

- 本檔不列任何 held-out incident id 或 run group id（023 解讀 23、026 解讀 23）；只用 slot 與 fault。
- 區間：run-group cluster bootstrap（10,000 次、seed 0、percentile；013 §3）。paired 差異的兩個方法用同一組重抽的 run group（023 §7）。
- 023 §7「其他」寫定的範圍：
  - **能說明的**：在同一個 stack、同一個 traffic profile、同樣這 10 個 fault（含 variant）、fault 10 分鐘的條件下重新收集時的變異，來源包括 traffic 時序、seed、單次 LLM 抽樣。
  - **不能說明的**：不能推廣到其他 fault、variant 或系統；不分層重抽會讓 fault 組成也跟著隨機變動，所以相對於固定設計偏保守；n 很小或比例接近 0、1 時，percentile 區間會覆蓋不足（例如某 fault 全對時區間寬度是 0）。
- 難度和 fault 高度重疊（015；023 §7「其他」）。

## 13. 下一步

- 依 SPEC「Gate」：判定不是 `pass`，**不進 Advanced**。
- 依 SPEC「收尾或改題」由使用者決定；決定記錄在 [decision 031](031-heldout-wrap-up.md)（照現在的 NOT PASSED 結果正式收尾，不改題、不進 Advanced）。本檔只記錄判定與數字。
