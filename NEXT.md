# NEXT

## 目前位置

**Core §1「鎖定 OpenTelemetry Demo 版本」：鎖定與 smoke test 完成；baseline 穩定化進行中（soak #2 待跑）。**
soak #1（product-catalog 64 MiB）FAILED：R1 / R2 因 checkout 在 baseline 被 OOM-kill，R6 因 product-catalog 貼近上限。
依規則：product-catalog 一次性升到 128 MiB（decision 004），checkout 比照 004 調到 64 MiB（decision 007）。下一步是 soak #2。
Day 1 清單：1（鎖版本）✅、2（label schema）✅、3（manifest schema）✅；4（canonical telemetry schema）、5（收集 1 個 incident）、6（刪掉 live system 後重播）還沒開始。
沒有進入 Advanced / Optional。

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
- M2 raw export 的唯讀研究 workflow 已啟動（結果寫進下一個 decision log）。
- 測試：272 passed（`-m "not network"`）。

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

1. **soak #2**（Mac heavy lock）：`./tools/with-mac-lock uv run python -m env soak --minutes 30 --warmup-minutes 5`。
   判定用修訂後的 R2 與多服務 R6（decision 004「修訂」）。
   - 通過 → 在 004 / 007 寫結果，設定凍結，進 M2。
   - product-catalog 在 128 MiB 仍失敗 → **不再調整，回報使用者**（004 只允許一次升級）。
   - checkout 在 64 MiB 因 R1 / R2 / R6 失敗 → 先更新 007，一次性調到 128 MiB，重跑 soak。
   - 其他服務（currency、shipping、valkey-cart…）出現 OOM / restart → 依 007 決策 6 處理。R3 / R4 / R5 失敗 → 先調查，不調記憶體。
2. **Core §2 frozen snapshot（M2）**：先寫 raw export 的 decision log（研究 workflow 的結果；file exporter / 新 pipeline、處理前還是處理後的資料等，見研究筆記 §4）。
   已知的設計輸入：OpenSearch 會因 mapping 衝突丟 log，**不能當 source of truth**。
3. **Core §4 canonical telemetry schema**（Day 1 #4）：依 raw export 的格式設計，純 Mac 開發。
4. **Day 1 #5 收集 1 個 incident 前必須先定案**（每項都要 decision log；可能改到鎖定環境 → 重新 `resolve`）：
   - **穩定判斷條件**：只排除暖機期不夠。開始 normal period 前要求 `verify-running` 乾淨，且最近 N 分鐘錯誤率回到 baseline（只剩 `ask_agent`）；
     收集期間若有**新增**重啟或 probe 失敗，該 run 標為無效或在 label 中標記。`verify-running` 需要小幅擴充：比較的是新增的重啟數，而不是累積值。
   - `ask_agent`：known ambient failure（decision 005）；M2 之後再判斷是否污染 RCA 評測。
   - 研究筆記 §6 列出的 ground-truth 洩漏面（OpenFeature `feature_flag.*`、直接寫出 flag 名稱的 log 等）要在 normalize 前處理。
5. Pilot fault 清單（M3/M5）：見研究筆記 §2 與 decision 006 的 flag 對照；每個 flag 的 a priori origin / affected / symptom 在那時決定。

## Blocked

- 目前沒有 blocker。
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
