# 003 — Traffic generator 設定與 random seed 政策

- 狀態：Accepted for Milestone 1（2026-10-08）；下方「待 smoke test 決定」的項目要在第一次正式收集前定案
- 影響範圍：實驗設計（traffic profile、可重現性、變異來源）

## 背景

SPEC Core §1 要求記錄 traffic generator 設定與 random seed。在鎖定的 OTel Demo 3.1.0（見 001）中，
load generator 是 Locust 2.44.4（`ghcr.io/open-telemetry/demo:3.1.0-load-generator@sha256:b130d6ce…`，
SLSA provenance 指向 commit `dedc017`）。研究結果（2026-10-08，對照 pinned commit 原始碼）：

- `locustfile.py` **完全沒有 seed 機制**：task 選擇（`random.choice(self.user.tasks)`）、`wait_time = between(1, 10)`、
  商品 / 數量 / 人員選擇都用全域 `random`；user id 用 `uuid1`（跟時間有關），session id 用 `uuid4`（來自 `os.urandom`）。
- OTel Python SDK 的 `RandomIdGenerator` 也從**同一個全域 `random`** 取 trace / span id。
  直接對全域 `random.seed()` 會讓每次 run 的 trace id 重複，造成跨 snapshot 的 id 碰撞。
- 就算做 per-user seeded RNG，也只能固定「選擇的順序」，固定不了「時間點」：
  request 數量會受 latency 影響（fault 本身就會改變 latency）、gevent 交錯順序、瀏覽器 user 的時序、SUT 自己的隨機性
  （例如 recommendation 會隨機排序）都還是不固定。

## 決策

1. **Core 階段不修改 load generator image。** 修改就要自己 build image，會失去 upstream digest 與 provenance，
   而且仍然只能得到部分可重現性。
2. **Locust 設定沿用鎖定的 upstream 預設，並明確記錄**（由 `env/otel-demo.lock.json` 鎖住的 compose + env 檔決定）：

   | 設定 | 值 | 來源 |
   |---|---|---|
   | `LOCUST_USERS` | 5 | upstream `.env` |
   | `LOCUST_SPAWN_RATE` | 未設定 → Locust 2.44.4 預設 1 user/s | — |
   | `LOCUST_HTTP_USER_WEIGHT` / `LOCUST_BROWSER_USER_WEIGHT` | 9 / 1（5 users → 4 HTTP + 1 browser） | upstream `.env` |
   | `LOCUST_BROWSER_TRAFFIC_ENABLED` | true（compose 寫死） | `compose.yaml` |
   | `LOCUST_AUTOSTART` / `LOCUST_HEADLESS` | true / false | upstream `.env` |
   | `LOCUST_HOST` | `http://frontend-proxy:8080` | upstream `.env` |
   | `LOCUST_RUN_TIME` | 未設定（一直跑） | — |

   每個 incident 的 manifest 會在 `traffic.settings` 記錄 container 上**實際**設定的 env（`collect.traffic.traffic_settings`）。
3. **Seed 政策**：
   - 每個 run group 有一個 master `seed`，同時記在 manifest（`seed`）與 ground truth injection record。
   - seed 只用來控制**我們自己 orchestrator 的隨機性**：normal period 長度的抖動、時間窗切點、fault 執行順序。
   - manifest 的 `traffic.seed_applied` 在 3.1.0 一律是 `false`，誠實標示 Locust 沒有吃到 seed。
4. **變異用統計方法處理，不假裝可重現**：每種 fault 收集多個 run group，最終報告用 bootstrap / CI（SPEC §10）。
   同一 run group 切出的時間窗不得跨 split（002）。

## 放棄的替代方案

- **在 load generator 呼叫全域 `random.seed(seed)`**：trace id 跨 run 重複，會污染 snapshot 與 evidence validation。
- **自建 per-user seeded RNG 的 patched image**（研究草稿見 workflow 結果）：失去 upstream digest，而且只能固定選擇順序。
  如果之後 leakage audit 或 baseline 難度檢查證明 traffic 變異太大，再另開 decision log 重新評估。
- **把瀏覽器 traffic 關掉以降低變異**：`imageSlowLoad` 這類 fault 只有瀏覽器載入圖片時才會出現，關掉會讓某些 fault 根本觀察不到。暫不採用。

## 待 smoke test 決定（第一次正式收集前必須定案）

Docker daemon 啟動後的第一次 smoke test（Mac，非正式收集）要確認以下項目，若決定偏離 upstream 預設，各自補 decision log：

1. **`ask_agent` 背景錯誤**：`WebsiteUser.ask_agent`（weight 3/32 ≈ 9.4%）固定打 `http://agent:8010/prompt`，
   但 `agent` service 只存在於 `compose.agent.yaml`，不在我們鎖定的組合裡。
   **2026-10-08 smoke test 已證實**：`NameResolutionError` / `gaierror(-2)`，都在 load-generator 的 error span 裡；run 1 全程 523 個 request 中有 24 次；run 2（不介入觀察 15 分鐘）959 個 request 中有 79 次，約 5.4 次/分、8.2%。
   可選：接受並記錄成已知噪音／透過 Locust class picker 停用該 task／加入 agent stack。
2. **Traffic 視窗控制**：維持 `LOCUST_AUTOSTART=true`，或改成 autostart=false，由 orchestrator 等所有 healthcheck 通過後再 `POST /swarm`。
   orchestrator 控制 Locust 時**不要經過 Envoy `/loadgen/`**，否則控制流量會變成 frontend-proxy 的 span / access log 進入 snapshot。
3. 每個 snapshot 一起存下 Locust 的 `/stats/requests/csv` 與 `/stats/failures/csv`，作為實際跑過的 traffic 紀錄。
4. **flagd-ui scheduler 必須保持停止**（3.1.0 預設 `running: false`，只能從 `/scheduler` LiveView 手動啟動）。
   `loadGeneratorFloodHomepage` 也只能由 orchestrator 的 fault config 控制。

Smoke test（2026-10-08）的其他觀察：至少有 1 個 browser user 在跑（run 1 的 5 分鐘內，`frontend-web` 有超過 500 筆 trace）。
Run 1 冷啟動時有 connection refused 與大量 504；run 2 只有啟動瞬間 2 次 DNS 失敗。
`ask_agent` 是 run 2 唯一持續出現的錯誤（959 個 request 中 79 次，約 5.4 次/分）。詳見 `docs/smoke-tests/2026-10-08-m1-mac-smoke.md`。

## 對實驗的影響

- 同一 fault config 的不同 run group 之間，request mix 與時間點本來就會有差異；這個差異算在誤差範圍內，不算 pipeline bug。
- 3.0.0（k6）與 3.1.0（Locust）的 traffic 無法比較；本專案只用 3.1.0，絕不混用。


## 修訂（2026-10-08，第一個 incident 收集之前）

「決策」中「master seed 同時記在 manifest（`seed`）與 ground truth injection record」改為**只記在 ground truth**
（`injection.json`、`run.json`、label）：seed 決定 normal 與 recovery 的長度，加上 manifest 的 window 就能算出 fault 時間（decision 002 修訂）。
manifest 的 `traffic.seed` 一律為 `null`，`traffic.seed_applied` 仍是 `false`。
