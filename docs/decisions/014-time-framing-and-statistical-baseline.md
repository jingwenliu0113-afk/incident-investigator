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
