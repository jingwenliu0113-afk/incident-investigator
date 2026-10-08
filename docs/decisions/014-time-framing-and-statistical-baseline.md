# 014 — 各方法的時間框架與統計規則 baseline v1

- 狀態：Accepted（2026-10-08）；在任何 baseline 或 Agent 對任何 incident 執行之前寫定（decision 011「延後」的第一項）。
  統計 baseline 的參數可以在 **Pilot Set** 上檢查並最多修訂一次（寫 decision log）；held-out 收集之前凍結，看到 held-out 結果後永遠不改。
- 影響範圍：所有方法（4 組 baseline 與 Agent）拿到的任務描述；SPEC Core §7 第 3 組 baseline（per-service anomaly score）

## 背景

- decision 011 延後：「各方法拿到的時間框架（例如是否告知前段是 normal——統計 baseline 的 reference period 取決於此）」，必須在任何 baseline 執行前決定。
- 收集協定（decision 009，公開）：snapshot 的時間窗 = normal（10 + U(0, 5) 分鐘）→ fault（Pilot 固定 10 分鐘）→ recovery（5 + U(0, 5) 分鐘）。
  fault_on 不能從窗長推得（seed 只在 ground truth，decision 002 修訂）。

## 決策

### 1. 時間框架（所有方法相同）

每個方法拿到：snapshot 的時間窗（start / end），以及一句固定的說明：**「時間窗的前 10 分鐘系統正常；之後某個時間點開始可能出現故障。」**
- 不給 fault_on / fault_off、不給 fault 類型或服務的提示、不給收集協定的其他細節（decision 011 §5：prompt 不描述收集協定）。
- 10 分鐘是協定保證的最短 normal 長度，對每個 incident 都一樣，所以不帶任何 incident 特有的資訊。
- 理由：真實的 RCA 通常知道「告警之前是好的」；給所有方法同一個參考期，統計 baseline 才有公平的比較基準，Agent 也拿到同樣的資訊。

### 2. 統計規則 baseline v1（`baselines/statistical.py`，method `stat-anomaly` v1）

**特徵**（每個 SUT 服務、每分鐘，從 snapshot 的 derived views 算，`collect.derive`）：
| 特徵 | 來源 |
|---|---|
| `error_ratio` | 該服務 span 中 status = error 的比例（該分鐘沒有 span 時不計） |
| `p95_latency_ms` | 該服務 server span 的 p95 duration |
| `warn_logs` | 該服務 WARN 以上的 log 數 |
| `cpu` | docker_stats `container.cpu.utilization` 的分鐘平均 |
| `memory` | docker_stats `container.memory.usage.total` 的分鐘最後值 |

**分數**：參考期 = 時間窗的前 10 個完整分鐘；之後的分鐘是檢查期。每個特徵的 robust z =（檢查期的最大值 − 參考期中位數）/ max(1.4826 × 參考期 MAD, 下限)，
只看**上升**。下限：error_ratio 0.01、p95_latency_ms 參考期中位數的 10%（至少 1 ms）、warn_logs 1、cpu 0.02、memory 參考期中位數的 2%（至少 1 MiB）。
參考期少於 3 個有值的分鐘，或檢查期沒有值，該特徵不計分。服務分數 = 各特徵 z 的最大值。

**輸出**（decision 013 格式）：
- `origin_candidates`：服務分數由高到低的前 5 名（分數 > 0；同分依名稱排序）。
- `affected_services`：服務分數 ≥ **3** 的服務（沒有任何服務 ≥ 3 時，只放第一名）。
- `fault_type`：第一名服務的最高分特徵 → `error_ratio` = error_response、`p95_latency_ms` = added_latency、`cpu` = cpu_saturation、
  `memory` = memory_leak、`warn_logs` = null（只給 family 也不給）；第一名分數 < 3 時 null。
- `user_symptom`：frontend-proxy 與 frontend 的 `error_ratio` z ≥ 3 → `errors`；`p95_latency_ms` z ≥ 3 → `latency`；兩者都沒有 → `none`。
- `evidence`：第一名服務在其最高分特徵的那一分鐘，最多 5 筆 error span（`error_ratio`）或最慢的 server span（`p95_latency_ms`）的 id；其他特徵不引用。
- `usage`：tokens 為 null，工具呼叫 0，記錄 latency。

## 為什麼

- 規則刻意簡單、事先固定，作為「Agent 必須明顯勝過」的下限（SPEC Gate）；特徵涵蓋錯誤、延遲、log、CPU、記憶體這幾類 fault 的主要症狀。
- 只看上升：v1 不處理「流量變少」（decision 010 規則 3 也不把它算 affected）。
- robust z（中位數 / MAD）與下限：參考期短（10 分鐘），避免變異接近 0 時任何小變化都爆分。

## 放棄的替代方案

- **不給任何時間框架、讓方法自行找變化點**：統計 baseline 的設計空間變大且難以公平比較；Agent 也會花預算猜參考期。
- **給 fault_on**：是 ground truth（decision 002）。
- **用整個時間窗的分布當參考**：fault 期間的值會汙染參考。

## 對實驗的影響

- 所有方法的任務描述包含 §1 的那一句，且只有那一句。
- 統計 baseline 的數字在 Pilot 上只用於「難度檢查」；參數修訂最多一次並寫 decision log。

## 修訂 1（2026-10-09，任何 Pilot incident 之前；只用無 fault 的資料）

**發現**（在無 fault 的校準 snapshot 上試跑 v1，檢查 pipeline，**沒有任何 label 或 Pilot / held-out 資料**）：
soak #5 的校準 snapshot（`data/external/calibration/20261008T143533Z/20261008T151534Z`）上，v1 把 18 個服務**全部**判為 affected，並預測 added_latency。原因有兩個：
1. **CPU 特徵量錯了（量測 bug）**：這個 stack 的 docker_stats `container.cpu.utilization` 在整段時間單調漂移
   （payment 從 0.006 升到 2.89；soak #3 的總和從 110 降到 24），而同一時間 `container.cpu.usage.total` 每 10 s 的增量穩定在 0.6–0.9 s
   （約 6–9% 的一顆 CPU）。它的行為像累積比例，不是每分鐘的使用率，所以 v1 的 cpu 在 soak #5 讓 18 個服務的 z 都 ≥ 3。
2. **單一分鐘的雜訊超過門檻 3**：例如 soak #5 frontend-proxy 的 p95 有一分鐘 133 ms（其餘約 12 ms），z = 44.9；payment 記憶體單一分鐘 101 MiB（其餘約 63），z = 34。
   robust z 的分母來自 10 分鐘參考期，檢查期取最大值，無 fault 時也很容易超過 3。

**修訂（stat-anomaly v2）**：
1. `cpu` = 每分鐘使用的 CPU 核數 = `container.cpu.usage.total` 在該分鐘結束的各區間的增量 ÷ 區間長度（跨重啟的區間不計）；
   不再使用 `container.cpu.utilization`（`collect.derive` v4）。
2. **門檻用無 fault 資料校準**：每個特徵的門檻 T_f = max(3, 無 fault 校準 snapshot 上任何 SUT 服務該特徵的最大 z)，無條件進位到小數一位。
   校準 snapshot = 凍結 policy v1 時用的 soak #3 與 soak #5（`calibration/20261008T120419Z/20261008T151532Z`、`calibration/20261008T143533Z/20261008T151534Z`），
   參考期與檢查期的切法與 incident 相同（前 10 分鐘 / 之後全部）。數值寫死在程式（`NULL_THRESHOLDS`），之後不再重算。
3. 服務分數 = max_f（z_f ÷ T_f）；affected = 分數 ≥ 1 的服務（沒有時只放第一名）；origin_candidates 依分數排序（> 0 的前 5 名）；
   fault_type = 第一名服務分數最高的特徵（對應同 v1；第一名分數 < 1 時 null）；user_symptom：frontend-proxy / frontend 的 error_ratio z ≥ T_error_ratio → errors，
   p95 z ≥ T_p95 → latency。evidence 同 v1。method version `2`。

**為什麼可以現在改**：只用無 fault 資料（沒有 label、沒有任何評測資料），所以不消耗「在 Pilot 上最多修訂一次」的額度；那一次修訂的規則不變。
CPU 是量測 bug，不修正的話 cpu_saturation 永遠量不到、而且每個 incident 都會誤報。用無 fault 資料定門檻是控制誤報率的標準作法，也讓不同特徵的分數可以比較。

**放棄的替代方案**：
- 維持門檻 3：baseline 在沒有 fault 時就把所有服務判為 affected，Gate 的「明顯勝過統計 baseline」會失去意義。
- 改成「連續 k 分鐘超過」：要另外決定 k，而且 fault 的形狀（例如稀疏的 intlShippingSlowdown）會受影響；留給 Pilot 的那一次修訂再考慮。
- 每個服務各自校準門檻：只有 2 個無 fault snapshot，每個 (服務, 特徵) 只有 2 個樣本，太少。

**校準結果**（CPU 修正後重算；最大 z 與來源）：error_ratio 0（兩個 soak 都沒有錯誤上升）→ T = 3；warn_logs 0 → T = 3；
cpu 3.57（soak #5 payment）→ T = 3.6；memory 33.98（soak #5 payment）→ T = 34.0；p95_latency_ms 44.92（soak #5 frontend-proxy）→ T = 45.0。
v2 在這兩個校準 snapshot 上（依定義）不預測任何 fault type、user symptom 為 none、affected 只放第一名。
已知後果：記憶體門檻 34 讓較小的記憶體上升（例如 email 在 100 MiB 上限內的洩漏）可能偵測不到；這是 baseline 的設計結果，不為特定 fault 調整。
