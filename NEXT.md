# NEXT

## 目前位置（2026-10-09 08:05Z，台北 16:05）

**Core 的工具鏈都已完成並測試；Pilot 正式收集暫停：intlShippingSlowdown 連續 3 次無效，等人看（A0）；heavy lock 目前被 rust-hnsw 的正式 benchmark 占用。**
- **Pilot 有效 incident（高效能模式 + AC）**：INC-002 paymentFailure（RG-003）、INC-003 productCatalogFailure（RG-007）、INC-004 paymentUnreachable（RG-008）、
  INC-005 cartFailure（RG-010；RG-009 無效）。RG-002（INC-001）撤回。剩 intlShippingSlowdown 與之後 5 個 fault。
- **兩種失敗原因**：
  1. **grafana 下載 plugin 逾時**（RG-004–006、RG-011、RG-012）：暖機前 aborted_unstable，只浪費約 5 分鐘、不影響資料；網路慢時發生（grafana.com 3–9 s）。
  2. **fault 關閉沒生效**（RG-009 cartFailure、RG-013 intlShippingSlowdown，`flag_unconfirmed`）：開啟都在 0.1–0.7 s 內確認，關閉在 10 s 內沒確認；
     RG-013 的 raw trace 顯示關閉寫入 105 秒後 shipping 仍有 10 秒延遲 → flagd 根本沒讀到關閉的設定，fault 延續到 recovery。判無效是對的（否則 label 錯）。
     推測：harness 以「暫存檔 + rename」整檔替換 flag 檔，inode 改變，flagd v0.16 在 Docker Desktop bind mount 上偶爾失去對新檔的監看。
     待驗證（要 Docker，等 heavy lock 空出再做，不干擾別人的正式 benchmark）：用單獨的 flagd container 比較 rename 與 in-place 寫入各 20 次切換。
- **正式收集**：固定高效能模式 + AC 供電（decision 025 修訂 3；preflight 與時間窗內每分鐘取樣都檢查，不符就拒絕 / 判無效）。
  收集期間 main checkout 必須保持乾淨、不改 `collect/`、`env/`：其他開發在獨立的 git worktree / 分支上做，Pilot 收完後再合併。
- **LLM 方法**：付費 API 由使用者決定先延後（A1）；程式已就緒。
- **已完成的 Core 範圍**：

  | 項目 | decision |
  |---|---|
  | 環境鎖定與 soak | 001、004、007、008 |
  | run group 收集協定 | 009，含修訂 1–4 |
  | label 與 review | 006、010、016、018 |
  | canonical snapshot 與凍結的 policy v1 | 011；renderer v2 |
  | docker_stats 覆蓋 | 012 |
  | 分層評分 | 013 |
  | 統計 baseline v2 | 014 |
  | leakage audit | 015 |
  | evidence relevance | 017 |
  | Agent 工具與執行框架 | 019、020 |
  | dump-all 與 retrieval | 021 |
  | 失敗分類 | 022 |
  | held-out 協定（Proposed） | 023 |
  | 預算、用量與可見資料的報告 | 024 |
  | 收集時的電力模式紀錄 | 025 |
  | paired 比較 | 023 §7 |
  | 端到端測試 | — |
  | README | — |

- **本 session 的三輪審查**，找到並修正的都是真實資料才會出現的 bug：
  - 程式碼審查：10 項；
  - 時鐘與單位稽核：9 項；
  - 在無 fault 的真實 snapshot 上試跑：發現 CPU 量測 bug、統計 baseline 在無 fault 時大量誤報、render 把 46% log 行的時間截掉、leakage 樣板出現大量假的 fault 專屬樣板。
- **非正式冒煙測試 #1（`collect smoke`，資料只在 scratch，永不進任何 set）**：2026-10-08 18:08Z 完成，paymentFailure 100%，normal / fault / recovery 各 2 分鐘。
  - 收集 → normalize → replay（每個 id 都能解析）→ label → leakage audit（easy、詞彙命中 0）→ 評分**全部走通**；run group valid，時鐘差 0.014 / 0.021 s。
  - 資料上故障清楚：payment fault 期間 error ratio 1.0（每分鐘只有 4–6 個 span）、checkout 0.23、frontend 0.3%、frontend-proxy 0.2%；
    accounting 在 fault 期間 0 span（訂單失敗 → Kafka 沒訊息；依規則「流量變少不算 affected」，review 時要注意）。
  - review 工作表與 Agent 7 個工具在真實資料上正常（建索引 1.3 s、每次查詢 < 0.05 s）。
  - stat-anomaly **不作答**：時間窗只有 6 分鐘，參考段固定前 10 分鐘 → 沒有可評的分鐘（設計如此，不是 bug）。
    因此冒煙測試的 normal 改為 10 分鐘、並加上 review 工作表一步（開發工具，非實驗設計；正式收集協定不變）。
- **非正式冒煙測試 #2**（2026-10-08 18:35Z，normal 10、fault 2、recovery 2 分鐘，commit `f00a983`）：整條 pipeline 走通，含 review 工作表；run group valid。
  stat-anomaly 第一次在真實 fault 資料上作答：fault_type、origin_top1 對；affected precision 1.0 / recall 0.5（漏 frontend、frontend-proxy）；
  symptom 錯（edge 的 error ratio 約 0.3%，低於門檻）；evidence 4 筆都存在、弱標籤 temporal / service / origin 全 1.0。
  **這是非正式資料，不依它調整任何門檻或規則**（統計 baseline 只能在 Pilot 上修訂一次，decision 014）。
- **離線檢查（冒煙測試 #1 的真實資料，不需 lock、沒有付費 API）**：dump-all 打包 119.7k proxy tokens（0.5 s），fault 的 error 群組都在；
  retrieval 的 BM25 查詢「error」第一筆就是 payment 的 fault span；用照腳本行動的假模型跑 Agent 執行框架 → 評分 → evidence → 失敗分類，
  答對與答錯（`not_seen`）兩條路徑都正確；錯誤的 fault_family 被正確拒收 3 次後記為放棄作答。
  觀察（不需改）：frontend-proxy 的 Envoy access log 本文含絕對時間戳，不會洩漏 fault 時間（normal 長度有 jitter、seed 只在 ground truth）。
- **decision 024（SPEC §7 報告）**：每次 `eval run` 把預算、model、可見資料範圍寫進 `run_config.json`；評分表新增「Budgets, usage and visible data」
  （usage 各欄的 n / mean / median / max、總成本、停止原因、實際看過的 record 與概覽比例）。只報告、不計分。
  另加測試：dump-all / retrieval 送給模型的所有文字都通過詞彙檢查、不描述收集協定（decision 015 §6）。測試 604 passed。
- **`collect pilot-loop`**（SPEC Week 1「自動化 collect → normalize → label」）：next → 一個 run（只在 run 期間持有 lock）→ process，重複到收齊或需要人；
  之後自動 leakage → stat-anomaly。只是把既有步驟串起來，不改任何協定；重新啟動時先補處理「有效但還沒有 label」的 incident。測試 615 passed。**今晚不執行**（電力模式，A7）。
- **decision 025**：run record 與 manifest 記錄收集開始時的電源與 `pmset` 電力設定（唯讀，不改任何設定）；`collect status` 列出每個有效 run 的模式。
  要用哪一種模式收集是使用者的決定（A5）。測試 608 passed。
- **held-out 工具（decision 023 實作說明、026；分支 `heldout-protocol`，Pilot loop 結束、main checkout 閒置後才合併）**：
  `collect heldout-plan` → `heldout-freeze` → 每個 slot `next` → `run --set heldout`（不接受 `--seed`）→ `process` → `eval leakage --set heldout`
  → review → `collect heldout-list` → `eval run|score --set heldout`。沒有 freeze 紀錄時所有 held-out 收集與方法執行一律拒絕；
  **plan、freeze 與收集都被 A1 擋住**（要求 LLM 方法已批准並在 Pilot 上跑過）。freeze 之前必須 commit：API adapter、Gate 條件 2 / 3 的程式、
  各 fault 等權平均與缺格表、013 正式版、需要乾淨 checkout 的 review 說明；freeze 之後只能改 NEXT.md 與新增 decision 檔。
  待人處理的 slot 只記 slot id 與非 valid 的 run group id。
  已合併 main 的 decision 025 修訂 2、3（2026-10-09）：電力條件對 held-out 一樣成立（026 解讀 29）。
  **026 修訂 1（程式審查後）**：held-out run group 一律不能撤回（撤回只用於 Pilot；手寫的撤回紀錄讓所有 held-out 步驟停止）；
  方法的 `run.lock` 存在時拒絕評分；transcript 先寫、prediction 最後寫；`up_at` 在 run 任何可能失敗的步驟之前記錄。
  **freeze 之前要使用者決定**（026「待使用者決定」，程式行為不變）：(1) 待人處理的 slot 如何解除（現在一個卡住的 slot 就讓清單永遠寫不出來，
  估計約 55% 會發生）；(2) freeze 之後的修正路徑（現在 023 §6 的 bug 修正與使用者決定 6 的排除在 freeze 後都做不到）；(3) 是否要 held-out 撤回。測試 847 passed。
- **合成範例與 2 分鐘 demo（decision 027；分支 `synthetic-sample`，從 `heldout-protocol` 分出，與它一樣等 Pilot loop 結束、main checkout 閒置後才合併）**：
  `uv run python -m collect sample --out data/samples/synthetic` 以程式產生 raw、經真正的 normalize 寫出 `INC-000` / `RG-000`（28 分鐘、280 spans、
  38 logs、112 metric points、全部約 248 KB；snapshot 與 ground truth 分開），`uv run python -m eval demo` 只讀範例、印出分層分數並聲明不是結果。
  真實 snapshot 永不進 git：hygiene 測試要求 `data/samples/` 下每個檔案都以相同 sha256 列在 `synthetic: true` 的 `sample.json`。
  id 用 `INC-000` 而不是 `INC-SAMPLE`（schema 只接受數字 id；000 永遠不會分配給收集到的 run）。測試 871 passed。
- **回來時請先看下面的「Blocked / 需要使用者」**。

## 上次完成

### 2026-10-08 晚 – 10-09（session 4）：細項紀錄

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
- **Held-out 協定（decision 023，Proposed）**：與 Pilot 相同的 10 個 fault、每個 K 個（使用者決定）、隨機 block 順序、方法執行前 review、freeze 紀錄、Gate 用單一 paired 檢定。
  已實作與 K 無關的分析：`python -m eval compare --method A --against B --set pilot`（paired run-group bootstrap、leave-one-fault-out）。
- 沒有進入 Advanced / Optional；沒有任何付費用量。測試：602 passed（`-m "not network and not docker_daemon"`）。

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
4. **每個 Pilot fault 的流程**（decision 016 的順序；`uv run python -m collect status --set pilot` 看進度）。
   **一次跑完整個 Pilot**：`uv run python -m collect pilot-loop --labeler agent:claude-code`（**不要**包 with-mac-lock：迴圈只在每個 `collect run` 期間持有 lock，
   run 之間釋放；lock 被占用時每 5 分鐘重試、最多 4 小時，不搶；需要人看的 fault、run 被拒、process 失敗都會停下；全部收齊後自動 leakage → stat-anomaly run / score；
   每一步的輸出在 `data/external/logs/pilot-loop/`；exit 0 完成、3 需要人、75 lock 一直被占用）。開始前會印出目前的電力模式（decision 025）。
   手動的單步流程：
   1. `uv run python -m collect next --set pilot` → 印出下一個 `--flag F --variant V`（全部收齊時不印；exit 3 = 某個 fault 需要人看：
      連續 3 個 run group 無效，或 fault 兩次沒被觸發）。
   2. `./tools/with-mac-lock uv run python -m collect run --set pilot --flag F --variant V`（約 45 分鐘；lock 被占用時 exit 75，不搶）。
      run group 無效 → 記錄原因，`next` 會再給同一個 fault（新 seed，decision 009 §4）。
   3. 有效時：`uv run python -m collect process --incident INC-nnn --labeler agent:claude-code`（normalize → Day 1 #6 replay → a priori label，做過的步驟跳過）。
   4. 收完或告一段落時：`uv run python -m eval leakage --set pilot` → `uv run python -m eval run --method stat-anomaly --set pilot` →
      `uv run python -m eval score --method stat-anomaly --set pilot`（v2；表在 `data/external/results/pilot/stat-anomaly/table.md`）。
   - 目前：RG-001（2026-10-08 15:21Z，paymentFailure）aborted_unstable（暖機中 grafana exit 1 重啟、payment healthcheck 連續失敗，payment 140/140 MiB）→ 下一個仍是 paymentFailure 100%。
   - 每次 run 之間 lock 會釋放（wrapper 一次只包一個 run），其他 Project 可以在空檔取得。
   - 非正式的整條 pipeline 檢查：`./tools/with-mac-lock uv run python -m collect smoke --root <scratch>`（normal 10、fault / recovery 各 2 分鐘，
     資料只寫在 scratch，永不進任何集合；跑完自動 normalize → replay → label → review 工作表 → leakage → 統計 baseline）。
     **冒煙測試進行中整個 working tree 都要保持乾淨**（normalize 檢查 `git status --porcelain`，不只 `collect/`、`env/`）。
   - **run 進行中不改 `collect/`、`env/`**（run 會在中途延遲 import 這些模組；改了會讓一個 run 混用兩個版本），也要保持 working tree 乾淨
     （preflight 與 normalize 都拒絕 dirty tree）；可以改 `eval/`、`agent/`、`baselines/`、文件。
5. **Gate 前請使用者做的人工作業**：label review（`python -m collect review-sheet --incident <INC>`，decision 018）與 evidence gold 標註（`python -m eval gold-todo --set pilot`，decision 017）。
6. LLM 方法（dump-all / retrieval / agent）已登錄在 `python -m eval run`，但 `eval/llm_methods.json` 是 `proposed`：未經使用者批准模型、預算與成本前一律拒絕執行，
   也還沒有 API adapter（decision 020 §6）。
7. 之後：第一張 baseline 表（Pilot）、LLM baseline / Agent：**第一次呼叫付費 API 前依 MACHINE_POLICY 報告用途、請求數、
   token 量與預估成本並等批准**；模型選擇與 dump-all 的預算數值（decision 011「延後」第 2 項）屬於要由使用者決定的事項。

## Blocked / 需要使用者（回來時一次處理）

### A. 需要使用者決定或批准
0. **intlShippingSlowdown 連續 3 次無效（RG-011、RG-012 grafana；RG-013 fault 關閉沒生效）→ 依規則由人看過才再收**。建議處理：
   - fault 關閉沒生效是 harness 的 bug（flag 寫入方式），我會先用 probe 驗證，若 in-place 寫入可靠就改 harness（寫 decision；有效性規則不變：仍須 10 s 內確認）。
   - grafana：Pilot 已有 4 個有效 incident 在現在的 env lock 下收集，**Pilot 期間不改 env lock**；網路好時重試。held-out freeze 前再決定是否關掉 grafana 的 plugin 下載（改 lock、新 soak）。
   - 需要你：確認看過、同意 intlShippingSlowdown 在修好 harness 後重試（`collect ack-failures`）。
1. **付費 LLM API 方法（dump-all / retrieval / agent）：使用者決定先延後（2026-10-09）**。在批准模型、預算與成本之前一律拒絕執行；
   scripted fake model 只做 harness 驗證，不產生方法結果。不阻塞 Pilot 收集。
2. **Pilot 的人工作業**（資料產生後由使用者處理）：每個有效 incident 的 label review（decision 018，`python -m collect review-sheet --incident <INC>`）
   與 evidence gold 標註（decision 017，`python -m eval gold-todo --set pilot`）。
3. **decision 023 的 gold 標註量**：使用者決定其餘項目照保守預設 → 目前依 017 現行規定（不修訂）。若要改為抽樣（每個 fault 2 個 incident），須在 held-out freeze 之前決定。

已處理（2026-10-09 使用者決定）：held-out K = 5（decision 023 Accepted，其餘依保守預設）；正式收集固定高效能模式 + AC 供電（decision 025 修訂 3；原本的自動模式由使用者改掉，RG-002 撤回重收）；
真實 snapshot sample 不進 git（需要時用 synthetic fixture）；`/usr/bin/git` 已由使用者修好；電力模式限制解除。

### B. LLM 方法的估算（第 A1 項用）

建議值在 `eval/llm_methods.json`（`proposed`）。每個 incident 的 token 量估算（proxy token ≈ UTF-8 bytes / 4；實際 tokenizer 的數字可能高 0–30%，未實測）：

| 方法 | 呼叫數 / incident | input tokens / incident | output tokens / incident |
|---|---|---|---|
| dump-all（B = 120k） | 1（+ 最多 2 次更正） | 約 12–16 萬 | 約 1–2 千 |
| retrieval（q = 8、k = 25） | 2 | 約 9 萬（概覽約 1.8 萬 × 2 + 檢索結果約 5 萬） | 約 2–3 千 |
| agent（40 次工具、工具輸出 ≤ 120k、30 回合） | ≤ 31 | 典型約 40–60 萬，最壞約 180 萬（每回合重送整段對話；prompt caching 可大幅降低） | 約 1–3 萬 |

- **實測（2026-10-09，soak #5 的 38 分鐘無 fault snapshot，用計量用的假模型，proxy tokens）**：dump-all 一次請求 131k；
  retrieval 兩次請求 17k + 19k（無 fault 時查詢命中很少；有 fault 時第二次最多再加約 50k）；agent 模擬 25 次工具呼叫的探索：26 回合、input 累計 422k、
  最後一回合 59k、工具輸出 51k（工具輸出用滿 120k 時累計約 0.8–1M）。實際 tokenizer 的數字尚未量（需要 API）。
- Pilot（10 個 incident）× 3 個方法：input 約 0.6–2 千萬 tokens（agent 佔大部分）。held-out 的數量在其協定決定。
- 成本 = tokens × 所選模型的單價（使用者確認目前價格）；建議先在 1–2 個 Pilot incident 上跑一次，量到實際 token 後再估全部。
- 需要決定：模型、上面的預算數值、是否用 prompt caching、批准預估成本。

### C. 暫時無法進行（不需要使用者，條件解除後自動繼續）
- 目前沒有。heavy lock 被其他 Project 占用時，`collect pilot-loop` 每 5 分鐘重試（最多 4 小時），不搶、不刪。
- 已解除：`/usr/bin/git` 失效（2026-10-08 17:05Z 起，使用者已處理）；Mac 自動電力模式下延後正式收集（2026-10-09 使用者解除；正式收集條件後來改為高效能模式 + AC，decision 025 修訂 3）。

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
