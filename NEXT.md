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
- normalize policy v1 **已凍結**（`sha256:95bc4b07…`）；normalize 會檢查 status、釘選 sha、乾淨 checkout。
- Day 1 清單：1 ✅、2 ✅、3 ✅、4 ✅（待凍結）、5 工具就緒、6 工具就緒。
- 評分與 baseline（decision 013–015）：prediction 格式與分層評分、時間框架（只給「前 10 分鐘正常」）、統計 baseline v1、leakage audit v1；`python -m eval run|score|leakage`、`python -m collect label|freeze`。
- **Pilot 清單已預先登錄（decision 016）**：10 個 fault 與各自的 a priori label（`collect/pilot.py`）；origin 規則（flag 改變誰的程式 / 設定）、
  規則 3 補充（非 origin 只算錯誤或延遲，OOM / 重啟算錯誤）、user_symptom 在 edge 判定、fault 沒被觸發就重收。`collect run --set pilot` 只收清單上的 fault，`collect label` 只從清單取答案。
- **evidence relevance（decision 017）**：pool = 各方法引用的聯集；弱標籤 temporal（fault 窗 + 60 s）/ service / origin；人工 gold 每個方法每個 incident 盲抽 5 筆、只能由人標、不可改；
  `python -m eval gold-todo --set pilot` → 填表 → `python -m eval gold-add --incident … --file … --annotator human:<name>`；score 表分層列出 existence、弱標籤、gold precision。
- 評分必須先有 leakage audit；詞彙命中不是 0 的 incident 不進任何評分、表上列出；主要指標依 Easy / Medium / Hard 分層（decision 015）。
- **label review（decision 018）**：`python -m collect review-sheet --incident <INC>`（ground truth 側工作表：a priori、要檢查的項目、各服務 normal / fault / recovery 摘要、container 事件）→
  使用者填表 → `python -m collect review --incident <INC> --file … --reviewer human:<name>`；寫出另一份 `label.reviewed.json`（a priori 不變、origin 不可改、每個差異要有理由）；
  評分 / leakage / relevance 優先用 review 過的 label，`fault_exercised = false` 的 incident 不進評分。
- **統計 baseline v2（decision 014 修訂 1）**：在無 fault 的校準 snapshot 上試跑發現 v1 把 18 個服務全判 affected：
  docker_stats 的 `container.cpu.utilization` 在這個 stack 是累積比例（量測 bug）→ CPU 改用 `container.cpu.usage.total` 的增量（derive v4）；
  門檻改為每個特徵在無 fault 資料上的最大 z（error 3、warn 3、cpu 3.6、memory 34、p95 45）。只用無 fault 資料，不占「Pilot 上修訂一次」的額度。
- **leakage 樣板修訂（decision 015 修訂 1）**：含數字的整個字遮成 `<n>`（商品 id 不再產生大量假的 fault 專屬樣板；無 fault 資料上 472 → 2）。
- **Agent 工具 v1（decision 019，`agent/tools.py`）**：decision 011 §5 的 7 個資料存取工具、sqlite 索引（依 content digest 快取在 `data/external/cache/`）、
  時間排序 + 子字串比對（沒有排名）、呼叫數 / proxy token 預算、exposure log。尚未接任何 LLM（模型與預算數值待使用者決定）。
- **Agent 執行框架 v1（decision 020，`agent/prompt.py`、`agent/harness.py`）**：共用任務說明（只有 decision 014 那一句框架與答案空間）、
  tool-use 迴圈、`submit_diagnosis` 結構化提交（驗證失敗最多更正 2 次，否則算放棄作答）、回合 / 工具預算到了強制提交、usage 與 transcript。
  只有模型介面，**沒有接任何付費 API**。
- **Dump-all 與 retrieval baseline（decision 021）**：共同的概覽區塊；dump-all = 概覽 → error 等級 record 依樣板分組 → 每分鐘輪流的時間分層樣本，在 B 內從尾端截；
  retrieval = 模型提 ≤ q 個查詢 → 每個 BM25（FTS5）取 k 筆 → 依時間排序交回 → 提交。預算建議值（B 120k、q 8、k 25、Agent 40 次工具 / 120k tokens / 30 回合）**待使用者決定**。
- **失敗分類 v1（decision 022）**：origin 或 fault_type 錯 = 失敗，依序歸一類：no_answer → coverage（review 的 telemetry_coverage 看不到 origin）→ mechanism →
  not_seen（exposure 沒有 origin 在 fault 期間的證據）→ seen_misread（看到了仍判錯 = 推理失敗）→ rule_limit（統計 baseline）。score 表列出各類次數。
- 沒有進入 Advanced / Optional；沒有任何付費用量。測試：575 passed（`-m "not network and not docker_daemon"`）。

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

1. ✅ **soak #5 PASSED**（`data/external/soak/20261008T143533Z/`）：這個 lock 可以收集（decision 008「結果」）。
2. ✅ 校準：soak #3 與 soak #5 在 commit `131446d` 上 F1–F6 全過。
3. ✅ **policy v1 已凍結**：`sha256:95bc4b07…`（decision 011「凍結紀錄」）。之後任何改動都是 v2。
4. **每個 Pilot fault 的流程**（decision 016 的順序；`uv run python -m collect status --set pilot` 看進度）：
   1. `uv run python -m collect next --set pilot` → 印出下一個 `--flag F --variant V`（全部收齊時不印；exit 3 = 某個 fault 需要人看：
      連續 3 個 run group 無效，或 fault 兩次沒被觸發）。
   2. `./tools/with-mac-lock uv run python -m collect run --set pilot --flag F --variant V`（約 45 分鐘；lock 被占用時 exit 75，不搶）。
      run group 無效 → 記錄原因，`next` 會再給同一個 fault（新 seed，decision 009 §4）。
   3. 有效時：`uv run python -m collect process --incident INC-nnn --labeler agent:claude-code`（normalize → Day 1 #6 replay → a priori label，做過的步驟跳過）。
   4. 收完或告一段落時：`uv run python -m eval leakage --set pilot` → `uv run python -m eval run --method stat-anomaly --set pilot` →
      `uv run python -m eval score --method stat-anomaly --set pilot`（v2；表在 `data/external/results/pilot/stat-anomaly/table.md`）。
   - 目前：RG-001（2026-10-08 15:21Z，paymentFailure）aborted_unstable（暖機中 grafana exit 1 重啟、payment healthcheck 連續失敗，payment 140/140 MiB）→ 下一個仍是 paymentFailure 100%。
   - 每次 run 之間 lock 會釋放（wrapper 一次只包一個 run），其他 Project 可以在空檔取得。
5. **Gate 前請使用者做的人工作業**：label review（`python -m collect review-sheet --incident <INC>`，decision 018）與 evidence gold 標註（`python -m eval gold-todo --set pilot`，decision 017）。
6. LLM 方法（dump-all / retrieval / agent）已登錄在 `python -m eval run`，但 `eval/llm_methods.json` 是 `proposed`：未經使用者批准模型、預算與成本前一律拒絕執行，
   也還沒有 API adapter（decision 020 §6）。
7. 之後：第一張 baseline 表（Pilot）、LLM baseline / Agent：**第一次呼叫付費 API 前依 MACHINE_POLICY 報告用途、請求數、
   token 量與預估成本並等批准**；模型選擇與 dump-all 的預算數值（decision 011「延後」第 2 項）屬於要由使用者決定的事項。

## Blocked / 需要使用者（回來時一次處理）

### A. 需要使用者決定或批准
1. **LLM 方法的模型、預算與成本**（決定之前 dump-all / retrieval / agent 一律拒絕執行；見下面的估算）。
2. **Pilot 的人工作業**（Gate 前）：每個有效 incident 的 label review（decision 018）與 evidence gold 標註（decision 017）。

### B. LLM 方法的估算（第 A1 項用）

建議值在 `eval/llm_methods.json`（`proposed`）。每個 incident 的 token 量估算（proxy token ≈ UTF-8 bytes / 4；實際 tokenizer 的數字可能高 0–30%，未實測）：

| 方法 | 呼叫數 / incident | input tokens / incident | output tokens / incident |
|---|---|---|---|
| dump-all（B = 120k） | 1（+ 最多 2 次更正） | 約 12–16 萬 | 約 1–2 千 |
| retrieval（q = 8、k = 25） | 2 | 約 9 萬（概覽約 1.8 萬 × 2 + 檢索結果約 5 萬） | 約 2–3 千 |
| agent（40 次工具、工具輸出 ≤ 120k、30 回合） | ≤ 31 | 典型約 40–60 萬，最壞約 180 萬（每回合重送整段對話；prompt caching 可大幅降低） | 約 1–3 萬 |

- Pilot（10 個 incident）× 3 個方法：input 約 0.6–2 千萬 tokens（agent 佔大部分）。held-out 的數量在其協定決定。
- 成本 = tokens × 所選模型的單價（使用者確認目前價格）；建議先在 1–2 個 Pilot incident 上跑一次，量到實際 token 後再估全部。
- 需要決定：模型、上面的預算數值、是否用 prompt caching、批准預估成本。

### C. 暫時無法進行（不需要使用者，條件解除後自動繼續）
- **2026-10-08 15:30Z：Mac heavy lock 被 `llm-serving-lab` 持有**（15:27:40Z 起，`batch_9b_pilot.sh`）。RG-002（paymentFailure 100% 重收）等 lock 釋放；依 MACHINE_POLICY 不搶、不刪。期間做不需要 lock 的 Core 工作（Pilot 清單、leakage audit 工具、baseline 表）。

### D. 歷史紀錄與環境狀態
- （歷史）soak #3 曾等 heavy lock（`llm-serving-lab` 11:14:59Z–12:04:19Z 持有），釋放後由本 Project 的 wrapper 取得。
- 歷史紀錄（已解除）：Docker Desktop 在 2026-10-08 09:32:48Z 被另一個 Claude Code session（`rtu-maintenance-platform` 專案，
  執行 `docker compose stop db && docker desktop stop`）停止。使用者回覆「可以再繼續用了」後，本 session 執行 `docker desktop start`
  （理由：跑 decision 004 的 soak test；當時 daemon 是停止狀態，沒有其他 workload 在跑），接著先 `compose down --volumes` 清掉本 Project 被 restart policy 拉起的 container。
- 遠端 RTX 5070 Ti：Core 不需要，沒有使用。
- Docker Desktop：依 `MACHINE_POLICY.md`，在 Core 階段是本 Project 專用。
  機器上不屬於本 Project 的 Docker 資源都保持原狀：`pgvector/pgvector:pg17` image、`rtu-maintenance-platform-db-1`（停止中）container、它的 volume `rtu-maintenance-platform_rtu_db_data` 與 network `rtu-maintenance-platform_default`。
- 本機已下載 28 個鎖定的 image（約 11.7 GB），保留給之後的收集使用。
- Docker Desktop VM 的 kernel log（`~/Library/Containers/com.docker.docker/Data/log/vm/init.log*`）約 2.5 分鐘輪替一次，只保留約 25 分鐘；
  OOM 證據要在 run 期間抓（soak 工具的 `docker-events.jsonl`）。
