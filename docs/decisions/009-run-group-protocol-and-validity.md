# 009 — Run group 收集協定：穩定判斷條件、時間結構與有效性規則

- 狀態：Accepted（2026-10-08）；在收集第一個 incident（Day 1 #5）之前寫定
- 影響範圍：收集協定、哪些 run 可以進 dataset（有效性）、ground-truth 側的紀錄
- 依據：smoke test（冷啟動 504 風暴、product-catalog 卡住）、soak #1 / #2（decision 004 / 007）、raw export（decision 008）、
  traffic / seed 政策（decision 003）、manifest 與 ground truth 分離（decision 002）

## 背景

- smoke run 1 冷啟動時有 504 風暴，暖機期也看過 OOM-kill 與卡住；「只排除前幾分鐘」不夠，要有可量測的穩定條件。
- 有些 fault 的效果本來就包含重啟 / OOM（例如 `emailMemoryLeak` 在 100M 時 OOM → restart），所以 fault 期間的重啟不能一律視為 baseline 不穩定。
- 研究（decision 008 的依據）：SDK metrics 每 60 s 一個 cumulative 區間；長 span 在結束後才送出；fault 的效果可能落後或延續（adHighCpu、lock contention、emailMemoryLeak、recommendationCacheFailure）。

## 決策

### 1. 一個 run group 的時間結構（全部用 host UTC 記錄，另量 host ↔ VM 時鐘差）

```text
up → verify-running → 暖機（≥5 分鐘）→ 穩定閘門 → normal period → fault on → fault 持續 → fault off → recovery → end → drain（≥3 分鐘）→ raw 收尾 → down
```

- **normal period 長度**：`10 分鐘 + U(0, 5) 分鐘`（以 run group 的 seed 抽樣；decision 002：固定長度會從時間窗洩漏 fault_on）。
- **fault 持續時間**：每種 fault 在 Pilot fault 清單（M3 / M5）固定；下限 5 分鐘（每個 60 s cumulative series 在 fault 內至少有 4 個完整區間）。
- **recovery**：≥ 5 分鐘。
- **drain 與 raw 收尾**：decision 008 §4。
- Day 1 / Pilot 階段一個 run group 切出**一個** incident，telemetry window = `[normal_start, end]`；多窗切法等需要時另寫 decision log。

### 2. 開始前的條件（任一不成立就不開始，不算一個 run）

- 持有 Mac heavy lock；`python -m env verify` 通過；沒有本 Project 的 container；沒有**其他** container 在執行（decision 008 §4）。
- 本 lock 已通過 baseline soak（decision 004 / 007 / 008 的 R1–R9）。

### 3. 穩定閘門（暖機之後、normal period 開始之前）

`verify-running` 乾淨之後，以 decision 004 的取樣方式觀察，**最近連續 5 分鐘**同時滿足：

| # | 條件 |
|---|---|
| G1 | 從 up 起所有 container 的 `RestartCount` = 0，沒有 Docker `oom` 事件或 exit 137 |
| G2 | 每個有 healthcheck 的 container 都 `healthy` 且 `FailingStreak = 0` |
| G3 | Locust 在這 5 分鐘內的 HTTP 5xx = 0（`ask_agent` 這類 known ambient 不算，decision 005） |

- 暖機 5 分鐘後開始檢查；不滿足就每分鐘再看一次「最近 5 分鐘」，**最多再等 10 分鐘**。
- 等不到就中止：記錄為 `aborted_unstable`（不是有效 run，不寫 injection record 與 incident），stack 照常 `down`。
- G1 一旦失敗（從 up 起有重啟 / OOM）就不會再變成通過，直接中止。

### 4. 收集期間的有效性規則

| 時段 | 觀察到 | 處理 |
|---|---|---|
| normal period（fault_on 之前） | 任何新的重啟、OOM、health 失敗、或非 ambient 的 HTTP 5xx | **run 無效**：沒有注入的異常污染了 baseline，整個 run group 不進 dataset |
| fault on 到 end | 重啟、OOM、health 失敗、5xx | **不影響有效性**（可能就是 fault 的效果）；逐筆記在 run record，給 label review 參考 |
| 整個 run | raw 不完整（decision 008 §6 的任一旗標） | **run 無效** |
| 整個 run | flag 寫入後的生效確認失敗（見決策 5） | **run 無效** |
| incident 視窗 | 任何 SUT 服務的 container 在某個完整分鐘沒有 docker_stats 資料（decision 012） | **run 無效**（`container_metrics_missing`） |
| normal period | state 或 Locust 的取樣失敗（2026-10-08 修訂 2） | **run 無效**（`sampling_errors`）：看不到的 normal period 無法保證乾淨 |
| normal period 以外，或 memcg 取樣 | 取樣失敗 | **不影響有效性**，逐筆記在 `sampling_errors` |

- 無效的 run 保留紀錄與原始資料（供除錯），但不指派 incident id、不進任何 split；之後以**新的 run group id 與新 seed** 重收，不重用 seed。
- 所有 run（包含中止與無效）都寫一份 run record，讓「丟掉了多少 run、為什麼」可以回報（EXPERIMENT_RULES：不得只回報成功案例）。

### 5. Fault 注入與生效確認

- 控制方式：host 端原子寫入 flagd 檔（temp file + `os.replace`，`controller.method = flagd-file`，研究筆記 §3）；寫入前後的 flag 檔都記 canonical sha256（decision 002 的 injection record）。
- 生效確認：寫入後從 compose 網路內部（`docker exec`，不經過 Envoy，避免在 snapshot 留下控制流量的 span）用 OFREP 查該 flag 的值，
  10 s 內必須等於注入的 variant；fault off 時必須回到 baseline 值。量到的延遲記在 ground-truth 側。
- run 結束後把 upstream 的 flag 檔還原（`git checkout`），並確認 checkout 乾淨（`verify`）。
- 洩漏面：確認查詢本身可能在 flagd 自己的 telemetry 留下紀錄，而且時間點剛好是 fault on / off。
  run record 逐筆記錄 harness 查詢的時間與 flag；normalize 必須依 Core §6 事先固定的規則去掉 flagd 自己的 telemetry，leakage audit 用這些紀錄驗證已去除。

### 6. 紀錄放在哪裡

- `ground_truth/run_groups/<RG>/injection.json`：fault、variant、schedule（decision 002 的格式）。
- `ground_truth/run_groups/<RG>/run.json`（新）：有效性、穩定閘門結果、各時段的重啟 / OOM / 5xx 觀察、flag 生效延遲、時鐘差、incident 對應、raw 目錄。
  它含有 fault 時間，所以只能放在 ground-truth 側。
- `raw/<RG>/raw_export.json`：decision 008 §6。
- `incidents/<INC>/manifest.json`：只有 provenance（decision 002），不含 run group、fault 時間、raw sha。

## 修訂（2026-10-08，任何 incident 收集之前；依 Core §4 設計評審的發現）

時間窗本身會洩漏答案，在收集第一個 incident 前補強：

1. **recovery 長度改為 `5 分鐘 + U(0, 5) 分鐘`**，與 normal period 用同一個 seed 的第二次抽樣（`collect.rungroup.recovery_minutes`）。
   原本固定 5 分鐘時，incident window = `[normal_start, end]`，fault_off 一定剛好在窗結束前 5 分鐘。
2. **Pilot 的所有 fault 一律持續 10 分鐘**（`python -m collect run` 不再接受 `--fault-minutes`）。每種 fault 長度不同時，窗長會透露 fault 類型。
   日後若需要不同的持續時間，另寫 decision log。
3. **時鐘漂移**：normal_start 前與 end 後各量一次 host ↔ VM 時鐘差；兩次相差超過 1 s，該 run **無效**（`clock_drift`）。
   normalize 用這兩個值把 host 時間的窗邊界換算到資料時鐘（decision 011），漂移太大就無法可靠換算。
4. 窗長因此是 `normal（10–15）+ 10 + recovery（5–10）= 25–35 分鐘`，對所有 fault 的分布相同。
   殘留的風險（fault_on 落在窗起點後 10–15 分鐘）只對「知道協定的人」有用；Agent 與 baseline 的 prompt / 工具說明不得描述收集協定（decision 011）。

## 放棄的替代方案

- **固定暖機時間，不做閘門**：smoke run 1 證明冷啟動的不穩定會超過「前幾分鐘」。
- **normal period 內的異常只在 label 標記**：Agent 與 baseline 會看到沒有注入的故障，正確答案就不再唯一（破壞因果控制）。
- **fault 期間的重啟也一律判無效**：會系統性排除會造成重啟的 fault（例如 memory leak），讓 dataset 偏向「溫和」的故障。
- **無效的 run 直接刪除**：之後無法回報被丟掉的比例與原因。

## 對實驗的影響

- 每個 run group 的長度約 5（暖機）+ 0–10（閘門）+ 10–15（normal）+ fault + ≥5（recovery）+ 3（drain）分鐘；fault 10 分鐘時約 35–50 分鐘。
- dataset 只包含通過閘門、normal period 乾淨、raw 完整、flag 生效確認通過的 run；報告要附「中止 / 無效 run 的數量與原因」。
- 本決策只規定 run 的結構與有效性；每種 fault 的持續時間、要收哪些 fault，在 Pilot fault 清單（M3 / M5）決定。

## 修訂 2（2026-10-08，任何 incident 收集之前；review 確認的問題，讓程式與本決策一致）

1. **取樣失敗**：原本程式把任何時段的取樣失敗都判無效，比 §4 嚴格，而且會系統性排除「讓 container 重啟的 fault」
   （例如 `emailMemoryLeak`：OOM 重啟時 cgroup 暫時不存在，memcg 讀取失敗）。改為只有 normal period 內 state / Locust 的取樣失敗才無效；
   其他的照樣記錄。memcg 的解析也改成跳過 cgroup 已消失的 container，不影響其他 container 的讀數。
2. **verify-running 不乾淨就中止**：§1 / §3 說閘門在 `verify-running` 乾淨之後才開始；原本只記錄不檢查。300 s 後仍有問題 → `aborted_unstable`，
   不碰 flag，照常收尾。
3. **中途出錯也留下 run record**：harness 任何例外（含 Ctrl-C）都把 run 記為 `aborted_error`，原因寫進 `reasons`，照常收尾後由 `collect run` 存檔（§4「所有 run 都寫 run record」）。
   store 在搬動 raw 之前先檢查 raw export，被拒絕時可以重試。
4. **收尾不會被打斷**：SIGTERM / SIGHUP 轉成和 Ctrl-C 一樣的流程；收尾期間忽略 SIGINT / SIGTERM / SIGHUP（子程序 `compose stop` / `down` 也繼承），
   而且 `down` 放在最內層的 finally，一定會執行。
5. （同日 review 修正）收尾的每一步（還原 flag 檔、關 samples、停 event watch、複製 raw）各自執行，任何一步失敗只記在 `teardown_errors`，
   後面的步驟（特別是複製 raw）與 `down` 照常執行；失敗的 run 記為 `aborted_error` 並保留 run record。判定有效性時出錯也一樣保留 record。

## 修訂 3（2026-10-08，第一個 incident 收集之前）：run group 在收集時就固定所屬的集合

- `collect run` 必須指定 `--set pilot|heldout`，記在 `injection.json` 的 `split`（資料格式：`fault_injection.schema.json` 新增必填欄位）。
  incident 屬於哪個集合在收集當下就固定，之後的評分依它選 incident；SPEC §5 / §10「Pilot 永不進 test、同一 run group 不跨 split」因此可以由程式檢查。
- `--set heldout` 目前一律拒絕：held-out 的收集協定（fault 清單、時長、split 大小）要先另寫 decision。
- 之前沒有任何 injection 紀錄（RG-001 中止、沒有 injection），不影響既有資料。

## 修訂 4（2026-10-09，任何有效 incident 收集之前）：VM 時鐘的資料經量到的時鐘差對到排程

- **發現**（程式碼審查）：排程與取樣是 host 時鐘；docker events（daemon 在 Docker VM 裡）、docker_stats 的分鐘、collector 自己的計數器是 VM（資料）時鐘。
  有效性判定直接拿兩者比較，只有在時鐘差接近 0 時才對。`docker info` 回報的 daemon 時間曾比 host 慢約 68 分鐘
  （Docker Desktop 閒置時的值，可能是快取或 VM 暫停，不可靠），所以不能假設時鐘差為 0。
- **修訂**：以 normal 開始時量到的時鐘差（VM − host，`clock_offset_seconds[0]`）換算：事件時間減去時鐘差後再分到 normal / fault 時段；
  container metric 缺口（decision 012）與 loss accounting（decision 008 §6）的時間窗加上時鐘差後再比較。判定規則與門檻不變。
- 測試：VM 快 120 s 時，host 時間 fault_on 前 60 s 的 OOM（VM 時間戳在 fault_on 之後）判為 normal period 的問題。

## 收集結果

### RG-001（2026-10-08 15:21Z，paymentFailure 100%，**aborted_unstable**，沒有注入 fault、沒有 incident id）

- 暖機結束後第一次閘門：G1 失敗（grafana 15:25:44Z `die` exit 1，被 restart policy 拉起），G2 失敗（payment 的 healthcheck 從 15:22:17Z 起連續失敗，
  docker 仍顯示 healthy，15:25:21Z 自行恢復）。G1 失敗是永久的，所以直接中止，照常收尾（raw 已複製、`down` exit 0、verify 乾淨）。
- 當時 payment 的 memory.current 達 139.8 / 140 MiB、grafana 174.9 / 175 MiB（upstream 的 limit）。soak #3、#4 也觀察到 payment、cart、email、grafana
  貼著 upstream limit（memory.current 含 page cache），soak #2、#5 則低很多；R6 只判 overlay 調整過的服務，這些不在判定內。
- 補送 update（decision 012）沒有改動任何 cgroup 限制（memcg 取樣的 `memory.max` 前後相同）。grafana exit 1 的原因無法得知（container 已 `down`）。
- 處理：依 §4 以新的 run group、新的 seed 重收；規則不變。**新增診斷**：收尾時，任何重啟過或出現 die / oom event 的 container，
  在 `down` 之前保存 `docker logs`（ground-truth 側 `harness/container-logs/`）。

