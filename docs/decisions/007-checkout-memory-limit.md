# 007 — checkout 的 memory limit 比照 decision 004，從 upstream 的 20 MiB 調到 64 MiB

- 狀態：Accepted（2026-10-08）；soak test 結果見文末「結果」
- 影響範圍：鎖定的實驗環境（Core §1）。新的 lock sha256 之前與之後的資料不得混用（目前還沒有任何正式收集的資料）。
- 依據：使用者在 decision 004 定下的原則——baseline 中**沒有注入 fault** 就出現的 OOM-kill / restart 是 upstream baseline instability，
  會破壞 RCA 實驗的因果控制，正式 collection 前必須消除。本文件把同一個原則、同一套規則套用到 checkout。

## 這個決策是什麼、不是什麼

- **是**：消除 upstream baseline instability（理由與 004 相同）。
- **不是**為了提高 incident task 的成績，也**不是** fault injection 的一部分。這個設定對所有 incident、所有 baseline、所有 Agent 都相同。

## 背景（證據）

- upstream 3.1.0 `compose.yaml` 對 checkout 設定 `deploy.resources.limits.memory: 20M`，並設 `GOMEMLIMIT=16MiB`（與 product-catalog 相同）。
- checkout 在沒有注入任何 fault 的情況下，兩次被 memcg OOM-kill（Docker Desktop VM 的 kernel log，`init.log` 的 `kmsg`：
  `oom-kill:constraint=CONSTRAINT_MEMCG … task=checkout`），都由 `unless-stopped` 拉回：
  - 2026-10-08T09:27:18Z：decision 004 的流程 dry run（product-catalog 64 MiB，checkout 20 MiB）；
  - 2026-10-08T10:01:05Z：正式 soak #1 暖機期（exit 137，`RestartCount` 0 → 1）。
- soak #1 的 memcg 取樣：被 kill 前一分鐘內 `memory.current` 19.6–20.0 / 20 MiB，`memory.events max` 從 90,357 增加到 686,707。
  重啟後仍然一直貼著上限：30 分鐘視窗內 p95 19.9 / 20 MiB，`memory.events max` +85,352。
- kernel log 顯示觸發 OOM 的是 healthcheck 的 `grpc_health_probe`：healthcheck 在 container 的 cgroup 裡執行，
  20 MiB 的上限連 probe 的記憶體都容不下，被 kill 的是 checkout 主程式。

## 決策

1. 與 004 相同的做法：只在本 Project 的 overlay `env/compose.overrides.yaml` 設定
   `services.checkout.deploy.resources.limits.memory: 64M`；不改 upstream source，`GOMEMLIMIT`、healthcheck、image 都不變。
   `tests/test_locked_env.py` 檢查 render 後的差異只有 overlay 宣告的 memory limit。
2. 第一版 **64 MiB**（比照 004 的第一版，同樣的機制、同樣的起點）。
3. 用 004 的 soak test 與通過條件 R1–R6 驗證；**R6 改為對每個被 overlay 調整 memory limit 的服務都判定**（product-catalog 與 checkout），
   門檻不變（`memory.current` p95 < 80% 上限，且視窗內 `memory.events max` 增量為 0）。這個擴充在下一次 soak 執行**之前**寫定。
4. 升級規則與 004 相同：只有在 64 MiB 下 checkout 仍出現 OOM、restart 或持續貼近上限（R1 / R2 / R6 因 checkout 失敗）時，
   才允許**一次性**調到 **128 MiB**；調整前先在本文件更新理由與數據。R3 / R4 / R5 因其他原因失敗時先調查，不得用記憶體處理。
5. **凍結**：soak test 通過後，正式實驗期間不得再修改此設定。
6. 其他 upstream 20 MiB 的服務（currency、shipping、valkey-cart）：只要在 baseline（沒有 fault）出現 OOM-kill 或 restart，
   就用同一套規則處理（先在本文件補證據與決策，再改 overlay）；沒有證據就不動，維持與 upstream 最小的差異。

## 放棄的替代方案

- **維持 20 MiB，把 checkout 的 OOM 當作已知噪音**：checkout 位在下單路徑的中心（payment、shipping、email、kafka 都由它呼叫），
  它的重啟會在 baseline 製造下游的錯誤與 trace 斷裂，跟注入的 fault 混在一起。理由與 004 相同。
- **直接用 128 MiB**：product-catalog 的資料暗示 64 MiB 可能不夠，但 checkout 沒有在不受限情況下的量測；
  與 004 用同一個起點與升級規則，比根據另一個服務的資料推測更容易說明。
- **一次把所有 20 MiB 的服務都調高**：currency、shipping、valkey-cart 目前沒有 OOM / restart 的證據；沒有證據的偏離不做。

## 對實驗的影響

- lock sha256 會改變；之前沒有正式收集的資料，不需要遷移。
- checkout 的 `container.memory.limit` 這類 metric 會反映新的上限；這是環境設定，不是故障訊號。
- 之後若 fault（例如 `kafkaQueueProblems`，會讓 checkout 多送 100 倍的訊息）讓 checkout 的記憶體上升，那是 fault 本身的效應。

## 結果

- soak #1（checkout 20 MiB）：R1 / R2 因 checkout 失敗（見 004「結果」）。這是本決策的證據，不是 64 MiB 的測試。
- 同一個視窗內其他 upstream 20 MiB 服務**沒有** OOM-kill 或 restart：shipping p95 16.6 MiB（83%，`max` +1,610）、
  valkey-cart 16.3 MiB（82%，+5,318）、currency 15.8 MiB（79%，+1,312）。依決策 6 不調整；之後每次 soak 的 R2 都會檢查它們。
- 觀察（不判定、不調整）：很多服務的 `memory.current` 都在上限的 99–100%（grafana、flagd、accounting、fraud-detection、kafka、
  otel-collector、opensearch…），其中 grafana 在視窗內碰到上限 2,390,637 次、flagd 39,015 次、quote 29,422 次。
  `memory.current` 含可回收的 page cache，碰到上限本身不是故障；判定只看 OOM / restart / 5xx / health / telemetry（R1–R5）。
  flagd 是 fault 注入機制，它的記憶體壓力若影響 flag 生效延遲，會在 M2 收集時由 injection record 的時間量到。
- **soak #2（checkout 64 MiB + product-catalog 128 MiB，`data/external/soak/20261008T103855Z/`）：PASSED**（R1–R6 全部通過，數據見 004「結果」）。
  checkout p95 19.1 MiB = 30% of 64 MiB，視窗內碰到上限 0 次，沒有重啟或 OOM；其他 20 MiB 服務也沒有 OOM / restart。
  **checkout 64 MiB 自此凍結**；不需要升到 128 MiB。
