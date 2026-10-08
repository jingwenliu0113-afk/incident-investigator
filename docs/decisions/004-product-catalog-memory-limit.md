# 004 — 把 product-catalog 的 memory limit 從 upstream 的 20 MiB 調到 64 MiB（soak #1 後依升級規則改為 128 MiB）

- 狀態：Accepted（2026-10-08，使用者決定）；soak #1 後依規則 4 一次性升到 128 MiB；soak test 結果見文末「結果」
- 影響範圍：鎖定的實驗環境（Core §1）。新的 lock sha256 之前與之後的資料不得混用。

## 這個決策是什麼、不是什麼

- **是**：消除 upstream baseline instability。在**沒有注入任何 fault**的情況下，product-catalog 已經會被 OOM-kill 和卡住，
  這會在 baseline 中產生非注入的故障，破壞 RCA 實驗的因果控制（「看到的異常 = 注入的 fault」）。
- **不是**為了提高 incident task 的成績，也**不是** fault injection 的一部分。這個設定對所有 incident、所有 baseline、所有 Agent 都相同。

## 背景（證據，見 `docs/smoke-tests/2026-10-08-m1-mac-smoke.md`）

- upstream 3.1.0 `compose.yaml` 對 product-catalog 設定 `deploy.resources.limits.memory: 20M`，並設 `GOMEMLIMIT=16MiB`。
- Run 1：暖機期被 memcg OOM-kill 一次（`constraint=CONSTRAINT_MEMCG`）；約 08:15:4x 起卡住，健康檢查連續失敗 10 次（Retries=20 把它遮成 healthy）。
- Run 2：`memory.current` 全程 17.1–19.9 MiB / 20 MiB；15 分鐘內 `memory.events max` 增加了 86,416 次，持續 swap。

## 決策

1. **不修改 pinned upstream source。** 改用本 Project 的 compose overlay `env/compose.overrides.yaml`，只設定
   `services.product-catalog.deploy.resources.limits.memory: 64M`。
   它排在 upstream compose 檔之後、`env/compose.pinned.yaml` 之前，由 `env/otel-demo.spec.json` → lock 記錄 sha256。
   `tests/test_locked_env.py` 檢查 render 後的差異**只有**這一個欄位。
2. 第一版固定 **64 MiB**。`GOMEMLIMIT=16MiB`（Go 的軟性上限）、healthcheck、image 都不變。
3. 正式 collection 前，跑一次至少 30 分鐘的 baseline soak test（`python -m env soak`，全程持有 Mac heavy lock）。
   通過條件**在執行前固定**如下（從 `compose up` 開始算，暖機 5 分鐘後開始 30 分鐘的 soak 視窗）：

   | # | 條件 | 計算範圍 | 通過標準 |
   |---|---|---|---|
   | R1 | restart count | 從 up 到結束，全部 28 個 container | `RestartCount` 全部為 0 |
   | R2 | OOM kill | 從 up 到結束，全部 container 的 memcg `memory.events oom_kill` | 全部為 0 |
   | R3 | unexpected 5xx | soak 視窗內 Locust 記錄的 HTTP 5xx | 0（暖機期的 5xx 另外記錄，不判定） |
   | R4 | container health | soak 視窗內每個取樣點，所有有 healthcheck 的 container | 全部 `healthy` 且 `FailingStreak = 0` |
   | R5 | telemetry 持續流動 | soak 視窗內每一分鐘，collector debug exporter 的 Traces / Metrics / Logs | 每一分鐘三種 signal 都有 |
   | R6 | memory usage | soak 視窗內 product-catalog 的 memcg | `memory.current` p95 < 80% 上限，且 `memory.events max` 增量為 0 |

   - Known ambient failure（不判定為失敗，只記錄數量，見 005）：`ask_agent` 的 name resolution 失敗、OpenSearch mapping 拒收。
   - R3 只計 HTTP 5xx。`ask_agent` 是 DNS 失敗，不是 5xx。
4. **升級規則**：只有在 64 MiB 下 product-catalog 仍出現 OOM、restart 或持續貼近上限（R1 / R2 / R6 因 product-catalog 失敗）時，
   才允許**一次性**調到 **128 MiB**；調整前先在本文件更新理由與數據，再重跑 soak test。
   R3 / R4 / R5 若因其他原因失敗，先調查，不得用調整記憶體來處理。
5. **凍結**：soak test 通過後，正式實驗期間不得再修改此設定。

## 修訂（2026-10-08 約 10:25Z 寫定：soak #1 還在跑、報告尚未產生）

門檻與判定範圍**都不變**；只修正量測方式（讓 R2 能真的量到它定義的東西），以及把 R6 套用到 decision 007 新增的服務。

1. **R2 的量測**：定義仍是「從 up 到結束，所有 container 的 OOM kill = 0」。
   - 問題：container 被 `unless-stopped` 重啟時，cgroup 會重建、`memory.events` 歸零。
     soak #1 暖機期 checkout 在 10:01:05Z 被 memcg OOM-kill（exit 137，RestartCount 0 → 1），但重啟後的每個 memcg 取樣都是 `oom_kill=0`
     （`max_events` 從 686,707 掉回 1,865）。只看 memcg 的 R2 會誤判為通過。
   - 修正：soak 工具從 `up` 之前到 `down` 之前，用 `docker events` 記錄本 Project container 的 oom / die 事件。下列任一成立即 R2 失敗：
     (a) memcg `oom_kill` > 0；(b) 任何 Docker `oom` 事件；(c) 任何 exit 137（SIGKILL）的 die 事件（teardown 之前的 SIGKILL 只會是 OOM killer）；
     (d) 事件串流中斷（無法判定）。
   - 防誤判：soak 開始前若已有本 Project 的 container 就拒絕執行，避免 `up --force-recreate` 自己停掉舊 container 產生的 exit 137。
   - 這讓 R2 **更嚴格**，不會讓原本失敗的 run 變成通過。
2. **R6 的範圍**：對每個被 overlay 調整 memory limit 的服務都判定（`env.soak.WATCHED_SERVICES`；decision 007 加入 checkout），門檻不變。
3. **soak #1 的判定**：執行中的 process 用的是修訂前的程式（R2 只看 memcg、R6 只看 product-catalog）。
   soak #1 的 R2 以本修訂為準，依保存的 kernel log 判定為**失敗**（`data/external/soak/20261008T095930Z/oom-evidence.*`）。
   不論 R2 如何，soak #1 的 R1 已因 checkout 的重啟而失敗。

## 放棄的替代方案

- **維持 20 MiB，把 OOM / 卡住當作已知連帶效應並在 label 標記**：非注入故障會跟注入的 fault 疊加或混淆，Agent 與 baseline 的對錯就不再只反映 RCA 能力。
- **改 upstream source 或 rebuild image**：違反「不修改 pinned upstream」，也會失去 upstream provenance。
- **同時調 `GOMEMLIMIT`**：多一個偏離 upstream 的變因。cgroup 壓力的主要來源是 file cache、非 heap 與 swap，不是 Go heap 本身，先只調 cgroup 上限。
- **直接給很大的上限（例如 256 MiB）**：與 upstream 的差距不必要地大；先用有證據支持的最小調整，不夠再依升級規則處理。

## 對實驗的影響

- lock sha256 會改變。在此之前沒有任何正式收集的資料，所以不需要遷移。
- 對 Agent 可見的 telemetry 來說，product-catalog 的 `container.memory.limit` 這類 metric 會反映 64 MiB；這是環境設定，不是故障訊號。
- 之後若 fault（例如 lock contention）讓 product-catalog 的記憶體上升，那是 fault 本身的效應，而不是 baseline 的不穩定。

## 結果

- 2026-10-08：overlay 已加入 lock；`tests/test_locked_env.py` 確認 render 後只有 product-catalog 的 memory limit 改變。
- 2026-10-08 約 2 分鐘的流程 dry run（不是正式 soak，不判定）：64 MiB 下開始時 `memory.current` 47.5–49.5 MiB，`memory.events max` 為 0。
  Dry run 在 09:32:48Z 因外部 workload 執行 `docker desktop stop` 而中斷（見 `NEXT.md` Blocked）。
- **soak #1（64 MiB，2026-10-08，`data/external/soak/20261008T095930Z/`）：FAILED。**
  up 09:59:30Z；暖機 5 分鐘；視窗 10:05:07Z – 10:35:20Z（31 分鐘）；teardown `down` exit 0、`verify` 乾淨。
  | # | 結果 | 數據 |
  |---|---|---|
  | R1 | **FAIL** | checkout RestartCount 1（10:01:05Z 被 OOM-kill，見 007）；其他 container 0 |
  | R2 | **FAIL**（依上方修訂） | 報告（修訂前程式）顯示 pass：checkout 的 cgroup 在重啟時重建，memcg 計數歸零。kernel log：10:01:05.919Z `CONSTRAINT_MEMCG task=checkout` |
  | R3 | pass | 視窗內 0 個 HTTP 5xx（1,966 個 request）；暖機期 0 |
  | R4 | pass | 121 個取樣點都 healthy、FailingStreak 0 |
  | R5 | pass | 31 分鐘每分鐘都有 traces / metrics / logs |
  | R6 | **FAIL**（product-catalog） | `memory.current` p95 51.4 MiB = 80% of 64 MiB（max 52.1 MiB）；視窗內 `memory.events max` +22 |
  - Known ambient：`ask_agent` 失敗 123 次；OpenSearch 1,019 個 export request 失敗、19,623 筆 log 被丟、6,884 次 mapping 拒收。
- **依升級規則一次性調到 128 MiB**（2026-10-08，在本段寫完後才改 overlay）：
  R6 因 product-catalog 失敗（持續貼近上限，且在視窗內碰到上限 22 次）。64 MiB 下沒有 OOM / restart，
  但「持續貼近上限」就是規則 4 的升級條件之一。這是**唯一一次**升級；128 MiB 下若 product-catalog 仍失敗，不再調整，改為回報使用者。
  R1 / R2 的失敗來自 checkout，不是 product-catalog，另由 decision 007 處理，不影響本升級的理由。
- **soak #2（product-catalog 128 MiB + checkout 64 MiB，2026-10-08，`data/external/soak/20261008T103855Z/`）：PASSED。**
  up 10:38:55Z；視窗 10:44:32Z – 11:14:45Z（31 分鐘）；判定用修訂後的 R2（含 Docker oom / exit 137 事件）與多服務 R6；teardown `down` exit 0、`verify` 乾淨。
  | # | 結果 | 數據 |
  |---|---|---|
  | R1 | pass | 141 個取樣點，所有 container RestartCount 0 |
  | R2 | pass | memcg oom_kill 0；Docker oom / SIGKILL 事件 0 |
  | R3 | pass | 視窗內 0 個 HTTP 5xx（2,061 個 request）；暖機期 0 |
  | R4 | pass | 121 個取樣點都 healthy、FailingStreak 0 |
  | R5 | pass | 31 分鐘每分鐘都有 traces / metrics / logs |
  | R6 | pass | product-catalog p95 20.8 MiB = 16% of 128 MiB（max 21.4），視窗內碰到上限 0 次；checkout p95 19.1 MiB = 30% of 64 MiB（max 20.1），0 次 |
  - Known ambient：`ask_agent` 失敗 126 次；OpenSearch 1,024 個 export request 失敗、18,734 筆 log 被丟、7,158 次 mapping 拒收。
- **凍結**：product-catalog 128 MiB 自 soak #2 起凍結，正式實驗期間不得再修改（決策 5）。
  之後的 lock 變更（decision 008 的 raw export）不動這個設定，但仍要重跑 soak（decision 008 §8）。
