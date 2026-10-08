# NEXT

## 目前位置

**Core §1 完成；Core §2 / §4 的工具全部就緒。soak #4 FAILED（R7、R8，都是量測程式的問題，raw 完整）→ decision 008 修訂 3 → 待跑 soak #5。
補送 update 的診斷 run 與 soak #3 的最終校準正在跑；之後：soak #5 → 用 soak #3 + #5 凍結 policy v1 → INC-001。**
- 記憶體設定已凍結（soak #2）。soak #3（raw export 的新 lock）：R1–R6、R8、R9 通過，R7 失敗 → 維持 FAILED。
- soak #4（同一個 lock）：R7 失敗在 OpenSearch 清佇列時的 ambient 拒收、R8 失敗在一行 `{}`（空的 MetricsData）；raw 完整（accounting 平衡）。修訂 3 只放行 opensearch exporter 的關閉錯誤、把 `{}` 計為空訊息；memcg 探測 container 改名 `ii-probe-…`（policy 當 harness 排除）。soak #4 維持 FAILED。
- R7 失敗原因（診斷 run 重現）：pipeline 都正常關閉後，collector 把 self-telemetry 推給自己已關閉的 4318 → exit 1。
  R7 修訂為「exit 0，或 exit 1 且關閉 log 證明只有這個錯誤」（decision 008 修訂），soak #4 用新標準判定。
- decision 012：docker_stats receiver 啟動 race 讓 shipping 整個 run 沒有 container metrics → up 後補送 no-op `docker update`；
  incident 視窗內缺任何 SUT container metrics 即無效。**補送是否有效還要診斷 run 確認**（`tools/rescan_diag.py`，見下一步 2）。
- loss accounting 完成（decision 008 修訂 2）：soak #3 視窗內 receiver accepted = file exporter sent（三種 signal 完全相等），沒有旗標。
- review workflow（normalize / 收集協定 / replay，24 個確認問題）全部修正並測試：FA-11、X8 套用到所有可見字串、check_snapshot 解碼檢查、
  double 編碼、G0 policy sha 與乾淨 checkout、manifest 先驗證再發布、seed 移到 ground truth（002 / 003 修訂）、report 計數與 schema、
  calibrate 可重跑與凍結條件 F1–F6（decision 011）、取樣失敗只看 normal period、verify-running、crash 也留 run record、收尾遮蔽訊號（009 修訂 2）。
- normalize policy v1 仍是 `calibrating`：**凍結前不得打開任何含 fault 的 raw**（程式會擋：status、釘選 sha、乾淨 checkout）。
- Day 1 清單：1 ✅、2 ✅、3 ✅、4 ✅（待凍結）、5 工具就緒、6 工具就緒。
- 沒有進入 Advanced / Optional；沒有任何付費用量。測試：456 passed（`-m "not network and not docker_daemon"`）。

## 上次完成

### 2026-10-08 session 3（decision 004–007、soak 工具、label schema、soak #1）

- 使用者決定把 product-catalog 的 memory limit 調到 64 MiB → decision 004（事先固定的 soak 通過條件 R1–R6 與升級規則）。
- decision 005：`ask_agent` 標為 known ambient failure（先不刪）；OpenSearch 不得作為 snapshot / source of truth。
- `env/compose.overrides.yaml` + `env/soak.py` + `python -m env soak`（TDD）。沒有 heavy lock、取樣窗 < 30 分鐘、已有本 Project 的 container 都會拒絕；
  `compose up` 失敗或中途失敗都會 `down` 並寫出報告。
- Docker Desktop 被外部 session 停止（09:32:48Z）→ 使用者回覆可繼續使用 → 本 session `docker desktop start`（理由記在 Blocked 的歷史紀錄）。
- **soak #1**（`data/external/soak/20261008T095930Z/`，64 MiB）：**FAILED**。
  - R1 / R2：checkout（upstream 20 MiB）在暖機期 10:01:05Z 被 memcg OOM-kill（kernel log 保存在 `oom-evidence.*`；dry run 09:27:18Z 也發生過一次）。
  - R6：product-catalog p95 51.4 MiB = 80% of 64 MiB，視窗內碰到上限 22 次。
  - R3 / R4 / R5 通過（0 個 5xx / 1,966 request；health 全程正常；telemetry 每分鐘都有）。
- 發現 R2 的量測漏洞：container 重啟會重建 cgroup，`memory.events` 歸零。修正為加上 `docker events` 的 oom / exit 137 事件，
  並在 soak #1 報告產生**之前**寫進 decision 004「修訂」（更嚴格，門檻不變）。R6 改為判定所有被 overlay 調整的服務。
- 依規則：product-catalog → 128 MiB（004，唯一一次升級）；checkout → 64 MiB（decision 007，比照 004 的規則，可一次升到 128）。lock 已重新 resolve。
- **Day 1 #2 label schema**：decision 006、`schemas/incident_label.schema.json`、`collect/labels.py`（commit `5aba810`）。
- 兩個 review workflow（label schema + R2 修正）：18 個確認的問題都已修正。
- M2 raw export 研究（4 主題 + 逐條反向覆核 + 彙整）→ **decision 008**（raw pipeline 在任何 processor 之前、寫進 collector container、收尾時 `cp` 出來；
  raw 以 run group 為單位放在 `data/external/raw/<RG>/`，Agent 只能讀 `incidents/<INC>/normalized/**`，SPEC §2 目錄差異已記錄）。
  已實作（TDD）：`env/otelcol-config-raw.yml`、`collect/rawfile.py`（串流掃描 OTLP JSONL）、`DataLayout.raw_dir` / `is_agent_readable`、
  soak 的 R7–R9 與 drain → stop → cp 收尾。研究筆記與 decision 001 的三處文件差異已更正。
- GitHub：private repo `jingwenliu0113-afk/incident-investigator` 設為 `origin`，`main` 已 push 並追蹤 `origin/main`
  （push 前稽核全部 history：沒有 telemetry / 資料 / Docker artifact / secret；`.gitignore` 補上 secret 與金鑰檔）。之後每個測試通過的 commit 都 push。
- soak #2 PASSED → 記憶體設定凍結。raw export 的 overlay 與 lock 已更新；鎖定的 collector 0.159.0 `validate` 通過合併後的 config。
- **decision 009（run group 收集協定）**：暖機 → 穩定閘門 G1–G3（最近 5 分鐘）→ normal（10 + U(0,5) 分鐘，seed 決定）→ fault → recovery → drain → raw → down；
  normal period 有異常、raw 不完整、flag 生效未確認、sampling 錯誤都判為無效（保留紀錄、不給 incident id）。
  已實作（TDD）：`collect/faults.py`（原子寫入 flag 檔、targeting rule、OFREP 確認）、`collect/validity.py`、`collect/rungroup.py`（orchestrator 與落地）、
  `collect/live.py`（真實 Docker）、`python -m collect run`。
- **decision 009 修訂**：recovery 改 5 + U(0,5) 分鐘、Pilot fault 一律 10 分鐘、時鐘漂移 > 1 s 判無效（避免窗長洩漏 fault 時間 / 類型）。
- **decision 010**：第一個 incident = `paymentFailure 100%`（Pilot、驗證 pipeline）；affected services = 自己出現因 fault 造成的錯誤或延遲的服務。
- **decision 011**（Core §4 設計 workflow：3 方向 × 3 評審 + 彙整）：ctel/1 snapshot（6 個決定性檔案、18 個 SUT 服務、資料時鐘原值、keyed id）、
  policy v1（X1–X10、控制面子樹 closure、Class A 樣板附 upstream file:line、靜默刪 token、隱私對齊）、GT-blind normalize、fail-closed `check_snapshot`。
  實作：`collect/otlp.py`、`policy.py`、`normalize.py`、`incident.py`（manifest）、`calibrate.py`、`snapshot.py`、`derive.py`、`replay.py`；CLI `normalize` / `calibrate` / `replay`。
- `MACHINE_POLICY.md` 新增「外部費用」：付費 API / 雲端 GPU / 付費資料服務在第一次使用前要報告用途、請求數、token / 運算量與成本，經使用者批准。
- 測試：397 passed（`-m "not network and not docker_daemon"`；`docker_daemon` 會跑一個幾秒的 `--rm` collector validate container）。

### 2026-10-08 session 2（smoke test + baseline commit）

- 兩輪 Mac smoke test（都持有 heavy lock）。完整紀錄（含所有問題與數字來源）：`docs/smoke-tests/2026-10-08-m1-mac-smoke.md`。
  - Run 1（互動式）：28/28 container 跑的是鎖定的 linux/arm64 manifest；traces / metrics / logs 都有進 backend；flagd 原子寫入 0.33–1.04 s 生效。
    冷啟動 504 風暴；product-catalog 被 OOM-kill 一次，約 08:15:4x 起又卡住；OpenSearch 因 mapping 衝突逐筆拒收 1,624 次（308 個 export request 失敗）。
  - Run 2（不介入觀察 15 分鐘）：沒有 504、沒有重啟、沒有 probe 失敗；`verify-running` 全部通過。
    但 product-catalog 的 cgroup 全程在 17.1–19.9 / 20 MiB，碰到上限 86,416 次；`ask_agent` 約 5.4 次/分失敗；OpenSearch 的 mapping 拒收也持續發生。
- 新增 `env/runtime.py` + `python -m env verify-running [--wait N] [--platform …]`（TDD）：確認 pinned ref、index digest、平台 manifest、running、healthy、
  沒有連續失敗的 probe（Docker 在 Retries=20 時會把失敗遮蔽成 healthy）、沒有重啟；也會列出沒有 healthcheck 的服務。
- `.gitignore` 補上 Docker artifacts（`*.tar`、`*.tar.gz`、`*.tgz`、`*.tar.zst`、compose override）與 `*.log`；`tests/test_repo_hygiene.py` 守住「telemetry dump / Docker artifact / 大型資料不得進 git」以及「會被追蹤的檔案 < 1 MiB」。
- `MACHINE_POLICY.md` 新增「Mac Docker Desktop（Core 階段）」規則，包含 anonymous volume 的歸屬規則，以及診斷 container 要用 `--rm` / `rm -v`。
- 回填 decision 001 / 003 與研究筆記 §7 的 runtime 結果。Code review 一輪（另有一輪核對文件與原始證據），確認的問題都已修正。
- 清理本 session 自己的診斷資源：`alpine:3` image，以及 `ii-inspect-probe` 留下的 anonymous volume `ed5c71e9…`（已確認來源才刪除）。
- 第一個 baseline commit：`chore: establish core baseline`。

### 2026-10-08 session 1

- 研究（5 個主題 + 反向覆核）→ `docs/research/2026-10-08-otel-demo-3.1.0-notes.md`。
- 決策 001（鎖 3.1.0 = `dedc017`）、002（manifest 與 ground truth 物理隔離）、003（traffic 與 seed 政策）。
- `env/`（lock 工具鏈）、`collect/`（provenance、layout、records、traffic）、`schemas/`，全部 TDD；兩輪 code review 確認的 14 個問題都已修好。

## 下一步（Core，依序）

1. **soak #5**（執行中，2026-10-08 14:37Z 起，持有 heavy lock）：R1–R9（R7 / R8 用修訂 3 的標準）。通過 → 這個 lock 可以收集；decision 008「結果」補 soak #5。
   不通過 → 調查，不動凍結的設定。
2. **校準（tree 必須乾淨）**：`uv run python -m collect calibrate --soak data/external/soak/20261008T120419Z` 與 soak #5 各一次
   （同一個 commit；soak #4 的 raw 有隨機命名的探測 container，不用；14:29Z 那次 soak #3 校準沒有記錄 commit，不能用來凍結）。
3. **凍結**：`uv run python -m collect freeze --calibration <soak #3 的 calibration.json> --calibration <soak #5 的>` →
   重釘 `collect/policy.py` 的 `POLICY_SHA256` → 測試 → decision 011 記錄凍結證據（soak、calibration sha、policy sha、commit）→ commit。
4. **Day 1 #5**：`./tools/with-mac-lock uv run python -m collect run --flag paymentFailure --variant 100%`（preflight 擋 dirty tree 與沒通過 soak 的 lock）。
   run group 無效（例如 `container_metrics_missing`）→ 記錄原因、換新 seed 重收（decision 009 §4）。
5. **normalize + Day 1 #6**：`uv run python -m collect normalize --incident INC-001`，然後 `uv run python -m collect replay --incident INC-001`。
6. **INC-001 的 a priori label**：`uv run python -m collect label --incident INC-001 --origin payment --affected payment,checkout,frontend,frontend-proxy
   --symptom errors --description "orders fail: failed to charge card" --labeler agent:claude-code`（decision 010）。
   `catalog+review`（對照 snapshot、填 `telemetry_coverage`）依 decision 006 / 010 要由**人**做：到 Gate 時請使用者 review。
7. 之後：Pilot fault 清單（M3/M5）、Core §6 leakage audit（含 normalize report 的 `new_attribute_keys`）、baseline 前要決定的時間框架與預算；
   LLM baseline / Agent 第一次呼叫付費 API 前依 MACHINE_POLICY 報告成本並等批准。

## Blocked

- 目前沒有 blocker。soak #3 曾等 heavy lock（`llm-serving-lab` 11:14:59Z–12:04:19Z 持有），釋放後由本 Project 的 wrapper 取得。
- 歷史紀錄（已解除）：Docker Desktop 在 2026-10-08 09:32:48Z 被另一個 Claude Code session（`rtu-maintenance-platform` 專案，
  執行 `docker compose stop db && docker desktop stop`）停止。使用者回覆「可以再繼續用了」後，本 session 執行 `docker desktop start`
  （理由：跑 decision 004 的 soak test；當時 daemon 是停止狀態，沒有其他 workload 在跑），接著先 `compose down --volumes` 清掉本 Project 被 restart policy 拉起的 container。
- 遠端 RTX 5070 Ti：Core 不需要，沒有使用。
- Docker Desktop：依 `MACHINE_POLICY.md`，在 Core 階段是本 Project 專用。
  機器上不屬於本 Project 的 Docker 資源都保持原狀：`pgvector/pgvector:pg17` image、`rtu-maintenance-platform-db-1`（停止中）container、它的 volume `rtu-maintenance-platform_rtu_db_data` 與 network `rtu-maintenance-platform_default`。
- Mac heavy lock：soak #1 期間持有，已由 wrapper 釋放；目前沒有人持有。
- 本機已下載 28 個鎖定的 image（約 11.7 GB），保留給之後的收集使用。
- Docker Desktop VM 的 kernel log（`~/Library/Containers/com.docker.docker/Data/log/vm/init.log*`）約 2.5 分鐘輪替一次，只保留約 25 分鐘；
  OOM 證據要在 run 期間抓（soak 工具的 `docker-events.jsonl`）。
