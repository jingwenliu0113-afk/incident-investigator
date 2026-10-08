# 012 — docker_stats 的 container 覆蓋率：啟動後補送 update event，incident 視窗內缺任何 SUT container 即無效

- 狀態：Accepted（2026-10-08）；在 policy v1 校準時發現，在收集第一個 incident 之前寫定。補送 update event 的效果要由一次短的診斷 run 確認（見「結果」）
- 影響範圍：收集協定（decision 009：up 之後多一個步驟、多一個無效條件）、run group 紀錄（`container_rescan`、`container_metric_gaps`、`raw.container_minutes`）

## 背景

- policy v1 在 soak #3 的 raw 上校準（decision 011 §4）時，docker_stats 只回報了 28 個 container 中的 27 個：**shipping 整個 run 都沒有任何 container metrics**。
  `docker stats shipping` 正常，collector log 沒有 docker_stats 的錯誤。
- 原因（`internal/docker/docker.go`，contrib v0.159.0）：receiver 啟動時先 `LoadContainerList`（只列 running 的 container），
  再開始 `ContainerEventLoop`，而 event loop 的起點是 `lastTime := time.Now()`。在「列表之後、event loop 開始之前」啟動的 container，
  兩邊都不會看到，之後也不會再補。
- soak #3 的時間吻合：collector 12:04:32.770 啟動，`Starting otelcol-contrib...` 12:04:33.097；shipping 12:04:33.131 啟動，正好落在這個空檔
  （currency 33.039、payment 33.225、quote 33.429 都有被收到）。所有 SUT container 都 `depends_on` collector，會在它之後的一秒內密集啟動，
  所以每次 run 都可能漏掉一到兩個，而且漏哪一個是隨機的。
- 影響：漏掉的服務沒有 CPU / memory / network 等 container metrics。若那個服務剛好是 fault origin（例如 `emailMemoryLeak`、`adHighCpu`），
  Agent 與 baseline 能看到的證據會隨 run 隨機變少，是一個和 fault 無關的混淆變因。

## 決策

1. **啟動後補送 update event**：`verify-running` 通過之後、暖機開始之前，對本 Project 的每個 container 執行
   `docker update --restart <它原本的 restart policy> <id>`。設定的值和原本一樣，container 沒有任何改變，但 Docker 會發出 `update` event；
   receiver 的 event loop 對 `update` 會重新 inspect 並開始收集這個 container（已經在收的 container 不受影響）。
   結果記在 run group 紀錄的 `container_rescan`（成功數、失敗的服務）。實作：`env.soak.rescan_container_metrics()`、`LiveStack.rescan_containers()`。
2. **覆蓋率檢查（無效條件）**：raw 複製出來後，從 `metrics.jsonl` 算出 docker_stats 每個 container 有資料的分鐘（`collect.rawfile.container_minutes()`，
   記在 `raw.container_minutes`）。incident 視窗（normal 開始到 recovery 結束）內**每一個完整的分鐘**，18 個 SUT 服務（policy v1 的 `sut_services`）
   的 container 都必須有 docker_stats 資料；缺任何一個，run group 判為無效，原因 `container_metrics_missing`，缺的分鐘記在 `container_metric_gaps`
   （`collect.validity.container_metric_gaps()`）。和其他無效條件一樣：保留紀錄、不給 incident id（decision 009 §4）。
3. soak 不加這個步驟：soak 判定的是環境穩定性（R1–R9），覆蓋率不在判定範圍內；soak #4 用的是開始時的程式。

## 為什麼

- 讓每個 incident 的可觀測範圍一致（每個 SUT 服務都有 container metrics），而不是由啟動時的 race 隨機決定。
- 補送 event 不改 lock、不改 upstream 的 config 或啟動順序、不碰 container 的執行狀態；改 collector 的啟動順序或版本都要改 lock，而且版本已釘死（decision 001）。
- 無效條件是防線：就算補送失敗或 receiver 中途掉了某個 container，也不會產生一個證據不完整的 incident。

## 放棄的替代方案

- **接受並記錄缺口**：每個 incident 的證據範圍不同，而且和 fault 無關，會混進方法比較。
- **重啟 collector**：會讓 raw 檔產生重啟邊界（decision 008 §6 判為不完整），也會重置內部計數器。
- **改 compose 讓 collector 早一點啟動**（overlay 加 `depends_on` / 延遲）：改 lock 與 SUT 的啟動行為；之前的 soak 全部作廢。
- **升級 collector-contrib**：改釘選的版本（decision 001）。
- **只對缺的 container 補送**：要在執行中讀 collector 裡的 raw 才知道缺哪個；對全部補送一樣有效，也比較簡單。

## 對實驗的影響

- 收集協定多一個步驟（約 28 次 `docker update`，幾秒）；run group 多一個無效條件。目前還沒有任何正式 run group，不影響既有資料。
- 新增紀錄欄位（ground-truth 側的 `run.json`）：`container_rescan`、`container_metric_gaps`、`raw.container_minutes`。Agent 可讀資料的格式不變。
- 若補送在診斷 run 裡證明無效，要先另寫 decision log 才能收集第一個 incident（無效條件會讓每個漏掉 container 的 run 都失效）。

## 結果

- **soak #4 再次發生**：這次漏掉的是 **currency**（13:45:58.180 啟動，collector 的 `Starting otelcol-contrib...` 在 13:45:58.077），
  shipping 這次有收到。兩次 soak 各漏一個、而且不同，證實是啟動 race、每次隨機。
- （待：補送 update event 的診斷 run）
