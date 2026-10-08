# NEXT

## 目前位置

**Core §1「鎖定 OpenTelemetry Demo 版本」：完成。** 靜態鎖定完成，2026-10-08 在 Mac 上做了兩輪 runtime smoke test。
環境可以在 Mac arm64 上跑鎖定的 image，但有已知的不穩定因素，第一次正式收集前要決定怎麼處理（見「下一步」3）。
Day 1 清單：1（鎖版本）✅、3（manifest schema）✅；2（label schema）、4（canonical telemetry schema）、5（收集 1 個 incident）、6（刪掉 live system 後重播）還沒開始。
沒有進入 Advanced / Optional。

## 上次完成

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

1. **Core §4 canonical telemetry schema**（Day 1 #4）與 **§3 label schema**（Day 1 #2）：純 Mac 開發，不需要 heavy lock。
2. **Core §2 frozen snapshot（進 M2 時）**：開始時先寫 raw export 的 decision log（file exporter / 新 pipeline、處理前還是處理後的資料等，見研究筆記 §4）。
   已知的設計輸入：OpenSearch 會因 mapping 衝突丟 log，**不能當 source of truth**。
3. **Day 1 #5 收集 1 個 incident 前必須先定案**（每項都要 decision log；可能改到鎖定環境 → 重新 `resolve`）：
   - **product-catalog 的 20 MiB 上限**：維持 upstream 設定，把間歇性卡住 / OOM 當作已知的連帶效應並在 label 中標記；
     或在 `env/` 加一個 overlay 調高上限（偏離 upstream，要記錄理由與新數值，並重新跑 smoke test 比較 `memory.events`）。
   - **穩定判斷條件**：只排除暖機期不夠。開始 normal period 前要求 `verify-running` 乾淨，且最近 N 分鐘錯誤率回到 baseline（只剩 `ask_agent`）；
     收集期間若有**新增**重啟或 probe 失敗，該 run 標為無效或在 label 中標記。`verify-running` 需要小幅擴充：比較的是新增的重啟數，而不是累積值。
   - **`ask_agent` 背景錯誤**（約 5.4 次/分，8%）：接受並記錄、停用該 task，或加入 agent stack（decision 003）。
   - 研究筆記 §6 列出的 ground-truth 洩漏面（OpenFeature `feature_flag.*`、直接寫出 flag 名稱的 log 等）要在 normalize 前處理。
4. Pilot fault 清單（M3/M5）：見研究筆記 §2（`emitRawPii` 不是 fault；`failedReadinessProbe` 在 compose 下沒有作用；`aiSlowResponse` / `aiRunawayAgent` 需要 agent stack；`imageSlowLoad` 需要 browser traffic）。

## Blocked

- 目前沒有。
- 遠端 RTX 5070 Ti：Core 不需要，沒有使用。
- Docker Desktop：依 `MACHINE_POLICY.md`，在 Core 階段是本 Project 專用；本 session 沒有重啟 Docker Desktop。
  機器上不屬於本 Project 的 Docker 資源都保持原狀：`pgvector/pgvector:pg17` image、`rtu-maintenance-platform-db-1`（停止中）container、它的 volume `rtu-maintenance-platform_rtu_db_data` 與 network `rtu-maintenance-platform_default`。
- Mac heavy lock：兩輪 smoke test 期間持有，都已由 wrapper 釋放；目前沒有人持有。
- 本機已下載 28 個鎖定的 image（約 11.7 GB），保留給之後的收集使用。
