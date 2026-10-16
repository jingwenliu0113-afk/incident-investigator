# 013 — Prediction 格式與分層評分（Pilot v1；正式版 2026-10-16）

- 狀態：Accepted for the Pilot Set（2026-10-08）；在任何 baseline 或 Agent 執行之前寫定。
  **held-out 資料收集之前**要依 Pilot 的經驗凍結成正式版（最多改一次，寫 decision log）；看到 held-out 結果後永遠不改。
  **正式版（2026-10-16）**：見文末「正式版（2026-10-16，held-out 之前凍結；013 唯一的一次修訂）」，在任何 held-out 資料、`heldout-plan` 與 freeze 之前寫定。
  這是 013 在 Pilot 上**唯一的一次修訂**（decision 023 第 16 行：§7 的 paired 比較與 Gate 判準寫進 013 正式版），沒有其他由 Pilot 引起的 013 修改；
  只轉述已決定、已實作的規則並標出程式行號，**不新增任何指標、門檻、規則或解讀**，文件與程式的出入記錄在正式版 F13。
  F13 的 7 項依使用者 2026-10-16 的決定（NEXT A11：純文件的直接修正，涉及評分邏輯或研究協定的先問）：第 2、4、5、6 項已處理（只改文字，第 5 項是程式的錯誤訊息文字；
  計分與規則都不變）；第 1、3、7 項使用者 2026-10-16 都選 (i)（原話「第 1、3、7 項都選 (i)，繼續 freeze」）：維持程式現在的行為、把它寫成規則
  （F1、F4、F5、F9 與 F13；只改文字，程式、測試、schema 都不變，Pilot 數字不變；017、022 沒有在 Pilot 上修訂，A9 的 waived 不變，見 F13 開頭）。
  freeze 的 Pilot 修訂宣告寫 `"013": {"status": "used", "decision": "docs/decisions/013-prediction-format-and-layered-scoring.md"}`
  （`collect/freeze.py:161-162` 強制 013 是 used）。正式版在 frozen commit 裡，freeze 之後本文件不再修改（026 解讀 7）。
  下面 §1–§4 是 Pilot v1 的原文，保留為歷史；其他文件引用的「013 §1–§4」仍指這四段，它們的規則在正式版不變（對應正式版 F1–F4）。
- 影響範圍：所有方法（4 組 baseline 與 Agent）的輸出格式、評分、evidence existence、報告的彙總方式（SPEC Core §8–§10、EXPERIMENT_RULES「先固定 metrics」）；
  正式版另含 held-out 的 paired 比較與 Gate 判準（023 §7）。

## 背景

- SPEC §8：至少分開評 injected fault / origin service / affected services / user symptom，不要壓成單一 root_cause string。
- SPEC §9：evidence 分 existence 與 relevance 兩層。§10：Pilot 不進 test、同一個 run group 不跨 split、報 confidence interval 或 bootstrap。
- label 的詞彙已固定：fault_type / fault_family（decision 006）、18 個 SUT 服務（decision 011）、user symptom 的 4 種 kind。

## 決策

### 1. Prediction 格式（`schemas/prediction.schema.json`，`eval.score.check_prediction`）

每個方法對每個 incident 輸出一份：
- `fault`：`fault_type`（decision 006 的 9 種之一或 null）、`fault_family`（可以只給 family；null 時由 fault_type 推得）。
- `origin_candidates`：**排序過**的服務清單，最多 5 個，最可能的在前；空清單 = 放棄作答。
- `affected_services`：服務集合；`user_symptom.kinds`：`errors` / `latency` / `degraded_feature` / `none` 的集合。
- `evidence`：引用的 record id（`s-` / `l-` / `m-` / `p-` / `t-`，`m-` 可加時間範圍 `t0` / `t1`）。
- `usage`：tokens（in / out / proxy）、工具呼叫、retrieval 次數、latency、成本（沒有的填 null）。
- 服務必須是 snapshot 的 18 個 SUT 服務；**沒有自由文字的答案欄位**。

### 2. 每個 incident 的分數（`eval.score.score_incident`）

| 層 | 指標 |
|---|---|
| injected fault | `fault_type`（完全相同 = 1）、`fault_family`（完全相同 = 1） |
| origin | `origin_top1`、`origin_top3`、`origin_rr`（reciprocal rank；不在清單內 = 0） |
| affected | 集合的 precision、recall、F1、Jaccard（預測空集合時 precision = 0） |
| user symptom | `symptom_exact`（集合完全相同）、`symptom_jaccard` |

- 放棄作答（null / 空清單）一律算錯，不排除在分母之外。
- **主要指標（每一層各一個，報告時並列，不加權合成）**：`fault_type`、`origin_top1`、`affected_f1`、`symptom_exact`。
  其他指標（family、top-3、RR、precision / recall / Jaccard）是輔助指標，一起報告。

### 3. 彙總（`eval.score.aggregate`）

- 每個指標報平均值與 95% 區間：以 **run group 為單位的 cluster bootstrap**（有放回抽 run group，同一 run group 的 incident 一起進出），
  10,000 次、seed 0、percentile 區間。
- Pilot Set 與 held-out 分開報，永不合併。

### 4. Evidence existence（`eval.evidence.existence`）

- 引用的 id 中，`open_snapshot().resolve(id, t0, t1)` 找得到 record 的比例（`m-` 有時間範圍時，範圍內要有點）；沒有引用時是 null，不是 0 或 1。
- relevance（candidate pool、弱標籤、人工 gold subset）是另一層，之後另寫 decision；兩者永不合成一個數字。

## 為什麼

- 主要指標每層一個、並列，讓「Agent 是否更準」不會被某一層掩蓋，也符合 SPEC「不壓成單一 string」。
- origin 用排序清單，可以同時報 top-1（嚴格）與 top-3 / RR（給統計 baseline 這種天然產生排名的方法公平的比較）；限制 5 個以免灑網。
- 放棄算錯：避免方法靠拒答提高準確率。
- cluster bootstrap：同一 run group 的 incident 不獨立（SPEC §10），以 incident 為單位抽會低估變異。

## 放棄的替代方案

- **單一加權總分**：權重任意，而且會掩蓋層與層之間的取捨。
- **affected 用完全相同**：太嚴，一個服務的差異就是 0 分；F1 保留部分正確的資訊。
- **origin 允許無限長清單**：可以把所有服務列出來拿 top-k。

## 對實驗的影響

- 所有方法（含之後的 Agent）都要能輸出這個格式；baseline 的 prompt / 規則只能看 frozen snapshot（decision 011）。
- Pilot 上的數字只用於 pipeline 驗證與「baseline 難度檢查」，不作為研究結論。

## 正式版（2026-10-16，held-out 之前凍結；013 唯一的一次修訂）

- **時間**：Pilot 的收集、label review、leakage audit、四個方法的 Pilot 執行與評分、evidence gold（2026-10-16 標完並重新評分）都完成之後；
  任何 held-out 資料、`collect heldout-plan` 與 `collect heldout-freeze` 之前。held-out 還沒有收集，沒有任何 held-out 資料或結果。
- **性質**：這是 013 在 Pilot 上的那一次修訂（023 第 16 行：§7 的 paired 比較與 Gate 判準寫進 013 正式版，用掉 013 唯一的一次修訂）。
  內容只轉述**已決定、已實作**的規則，每一項列出出處與程式行號（以本 commit 的程式為準；freeze 釘住 commit 與所有程式，026 解讀 7）：
  上面的 v1 §1–§4、023 §2–§7 與「使用者決定」及其追加、023「實作說明：Gate 計算」與解讀 1–14、026 解讀 17–20、23、24、30、017（含兩則補註）、
  022（含補註）、024、030。**沒有新增任何指標、門檻、規則或解讀**；文件與程式的出入列在 F13（寫定時只記錄、不選邊、不改程式；2026-10-16 依使用者決定處理純文件的項目，
  評分邏輯或研究協定的第 1、3、7 項由使用者選 (i)：照程式現在、已實作的行為寫明，不是新的規則，見 F13）。
- **與 v1 的關係**：v1 §1–§4 的規則都不變（正式版 F1–F4 是同一份規則加上程式行號）；正式版多出來的只有兩類：
  併入 023 §7 的 paired 比較與 Gate 判準（F7、F8，原本只寫在 023）；把 017、022、024、026、030 已決定、與評分和報告有關的規則在這裡列出出處（F4–F6、F9–F11）。
- **其他由 Pilot 引起的 013 修改：沒有**。F12 列出 Pilot 上與 013 有關的觀察，都不改 013。若使用者要併入其他修改，那是設計決定（NEXT A11），
  依 023 第 16 行必須和本修訂併在一起，也就是在 freeze 之前寫進本節。F13 第 7 項的 (ii)（改 013 的計分）會是這種修改；
  第 1、3 項的 (ii) 改的是 017（evidence 的鍵）與 022（失敗分類）的規則，不是 013 的修改，而是 017 / 022 在 Pilot 上的那一次修訂（見 F13 開頭）。
  使用者 2026-10-16 三項都選 (i)，所以沒有這種 013 修改，017 / 022 也沒有在 Pilot 上修訂。

### F1. Prediction 格式（v1 §1）

- 定義：`schemas/prediction.schema.json`；檢查：`eval.score.check_prediction`（`eval/score.py:19-32`）＝ schema 錯誤，加上 `origin_candidates` 與
  `affected_services` 中不在 18 個 SUT 服務的服務（`eval/score.py:29-31`；`collect.policy` 的 `sut_services`，snapshot 的 `services` 就是這份清單，`collect/normalize.py:481`）。
- 每一層都是 `additionalProperties: false`（schema :7 起），所以**沒有自由文字的答案欄位**。

  | 欄位 | 規則 | schema |
  |---|---|---|
  | `prediction_version` | 常數 1 | :20-22 |
  | `incident_id` | `INC-` 加至少 3 位數字 | :23-26 |
  | `method` | `name`、`version`（非空字串）。評分（方法取自指令的 `--method`）與 freeze 不讀它。`name` 是 gold 抽樣種子 `<incident>:<method>` 的 method 部分：`eval gold-todo` 以 prediction 的 `method.name` 分組（`eval/runner.py:1155`、`eval/relevance.py:97`；F4），所以它決定哪些引用被抽去盲標。`version` 只是 provenance，Pilot 上由 `eval version-check` 流程上檢查（`eval/runner.py:412`；021「修訂」第 4 點與「審查（2026-10-11）」） | :27-44 |
  | `fault.fault_type` | decision 006 的 9 種之一或 null | :53-66 |
  | `fault.fault_family` | 6 種 family 之一或 null（可以只給 family；null 時評分由 fault_type 推得，F2） | :67-77 |
  | `origin_candidates` | 排序過、最可能的在前、最多 5 個、不重複；空清單 = 放棄作答 | :80-88 |
  | `affected_services` | 不重複的服務集合 | :89-95 |
  | `user_symptom.kinds` | `errors` / `latency` / `degraded_feature` / `none` 的不重複集合 | :96-116 |
  | `evidence` | `{id, t0?, t1?}` 的清單；id 符合 `^[slmpt]-[0-9a-f]{16,32}$`；`t0` / `t1` 是整數（資料時鐘的 ns）。每一種 id 都可帶 `t0` / `t1`：`m-` 的範圍影響 existence 與弱標籤的時間；其他種類（`s-` / `l-` / `p-` / `t-`）的範圍不影響 existence 與時間，但和 `m-` 一樣是 017 的鍵 `(id, t0, t1)` 的一部分（F4；F13 第 1 項，使用者 2026-10-16 選 (i)） | :117-138 |
  | `usage` | `tokens_in`、`tokens_out`、`proxy_tokens`、`tool_calls`、`retrievals`、`latency_s`、`cost_usd`：≥ 0 的數字或 null。每個鍵都可以省略（schema 沒有 `required`）：報告以 `.get` 讀，缺鍵與 null 相同，都不計入 n（`eval/runner.py:741`）；cost 總和遇到任何一個缺值就寫 `-`；held-out 補位的放棄作答 usage 是 `{}`（`eval/runner.py:879`）。usage 只報告、不計分（F10）（F13 第 2 項） | :139-193 |

- 不合格的 prediction：Pilot 的 `eval run` 停止（`eval/runner.py:646-647`）；held-out 的嘗試以 `invalid_prediction` 結束、該 incident 關閉、
  計分時是放棄作答（`eval/runner.py:585-588`；026 解讀 17、19；F5）。LLM 方法在 harness 內先把問題回給模型、最多更正 2 次，之後是 `invalid_submission`
  （放棄作答；`agent/harness.py:18`、`:175-191`、`:203-243`；decision 020 §3）。
- 引用驗證：格式不合的 evidence id 在提交時被 schema 拒收；格式合但不存在的 id 在評分時計為 existence 未解析（F4）。兩者都不放寬（decision 021「不變的」）。

### F2. 每個 incident 的分層分數（v1 §2）

`eval.score.score_incident`（`eval/score.py:45-63`），用 F6 的有效 label：

| 層 | 指標 | 定義 |
|---|---|---|
| injected fault | `fault_type`（**主要**） | 與 label 完全相同 = 1，否則 0；null = 0（:47、:55） |
| | `fault_family` | 預測的 family；預測是 null 時用 fault_type 的 family（`collect.labels.FAULT_TYPES`），兩者都沒有時是 null；與 label 完全相同 = 1（:48、:56） |
| origin | `origin_top1`（**主要**） | label 的 origin 是第 1 個候選 = 1（:50、:57） |
| | `origin_top3` | origin 在前 3 個候選 = 1（`ORIGIN_TOP_K = 3`，:16、:58） |
| | `origin_rr` | 1 / origin 的名次；不在清單內 = 0（:59） |
| affected | `affected_precision`、`affected_recall`、`affected_f1`（**主要**）、`affected_jaccard` | 集合比較（`_sets`，:35-42）：預測空集合時 precision = 0；precision + recall = 0 時 F1 = 0；兩邊都空時 Jaccard = 1（label 的 affected 至少 1 個，`schemas/incident_label.schema.json:87`，所以不會發生） |
| user symptom | `symptom_exact`（**主要**） | kinds 集合完全相同 = 1（:61） |
| | `symptom_jaccard` | kinds 集合的 Jaccard（:62） |

- **主要指標每層一個**（`MAIN_METRICS`，`eval/runner.py:421`）：`fault_type`、`origin_top1`、`affected_f1`、`symptom_exact`，並列報告、不加權合成；
  其他 7 個是輔助指標，一起報告。計分的就是這 11 個：scores.json 每一列另有只報告、不計分的欄位（`REPORTED_ONLY`，`eval/runner.py:807`）
  與 evidence 欄位，彙總前拿掉（`eval/runner.py:904-906`）。
- 放棄作答一律算錯、留在分母（F5）。

### F3. 彙總與 bootstrap（v1 §3）

- 平均值：所有計分 incident 的平均（`eval/score.py:77`）。
- 95% 區間（`eval.score.aggregate`，`eval/score.py:66-82`）：
  - 以 run group 為單位的 cluster bootstrap：run group id 排序，`random.Random(0)` 抽 10,000 次，每次有放回地抽與 run group 數相同個數的 run group（:72-74）；
    每次的統計量 = 抽到的 run group 中所有 incident 的平均（重複抽到的 run group 重複計入，:78）。同一組 10,000 次重抽用在每一個指標上。
  - percentile 區間：10,000 個值排序後取 0 起算的第 `int(0.025 × 9,999)` = 249 個與第 9,750 個（:79）；數字四捨五入到 6 位（:80）。
  - held-out 每個 run group 只切一個 incident（009 §1、023 §2），所以等於以 incident 為單位重抽。
- 報告：scores.json 的 `aggregate` 與 table.md（`eval/runner.py:933-984`）列出每個指標的平均與區間、incident 數、run group 數；主要指標標 `(main)`。
- 難度分層（decision 015；023 §7）：主要指標在各難度層的平均；有 ≥ 10 個 run group 的層另報同一種 bootstrap 區間，其餘只報 n 與平均
  （`STRATUM_MIN_RUN_GROUPS`、`difficulty_strata`，`eval/runner.py:660-678`）。
- 各 fault 表（023 §7）：只描述、沒有區間（F8）。
- **Pilot Set 與 held-out 分開報，永不合併**：結果目錄是 `results/<set>/<method>/`；held-out 的 compare 與 gate 只接受目前 freeze 與清單的分數（F7、F8）。

### F4. Evidence（v1 §4；relevance 依 017）

- **existence**（v1 §4；`eval/evidence.py:9-14`）：prediction 的每一個引用（不去重）中，`Snapshot.resolve(id, t0, t1)` 找得到 record 的比例；沒有引用時是 null。
  `resolve`（`collect/snapshot.py:84-97`）：`t-` = 該 trace 存在；`s-` / `l-` / `m-` / `p-` = id 在 snapshot 的索引裡；`m-` 帶範圍時範圍內要有該 series 的點；
  其他種類帶的範圍不檢查、不影響 existence（`collect/snapshot.py:93-96`；F13 第 1 項，使用者 2026-10-16 選 (i)）。
- **弱標籤**（017 §2；`eval/relevance.py:69-88`）：existence 成立、以 `(id, t0, t1)` 去重（`eval/relevance.py:21-35`）的引用中 temporal / service / origin / weak 的比例；
  沒有這種引用時是 null。這個鍵不分 id 的種類（017 §1；`key`，`eval/relevance.py:21-22`）：同一個非 `m-` id 帶不同範圍（或一個帶、一個不帶）是不同的鍵，
  在弱標籤與下面 gold 的抽樣、判定、分數中各自計算（F13 第 1 項，使用者 2026-10-16 選 (i)）。
  - 時間（:53-66）：span 的開始、log 的 time（沒有時用 observed time）、point 的 time、`m-` 帶完整範圍時取中點、`t-` 取該 trace 最早的 span 開始；`m-` 沒有範圍時沒有時間。
    `s-` / `l-` / `p-` / `t-` 帶的範圍不影響時間（:56-63）。
  - temporal = 時間在 `[fault_start, fault_end + 60 s]`（label 的 host 時鐘加上該 run 量到的時鐘差，換到資料時鐘；:75-76、`GRACE_S` :16）；
    service = record 的服務（`t-` 是 trace 中所有 span 的服務）在 label 的 affected 裡；origin = 含 origin；weak = temporal 且 service。
- **gold**（017 §3 與兩則補註）：
  - 抽樣（`gold_sample`，`eval/relevance.py:91-100`）：每個 incident、每個方法，existence 成立的不同引用排序後以 `random.Random("<incident>:<method>")` 打亂，
    取前 `GOLD_PER_METHOD` = 5 個（:17）；`<method>` 是 prediction 的 `method.name`，不是結果目錄名（`eval/runner.py:1155`；F1）；已判定的不再列出，一個方法的樣本不因其他方法加入而改變。
  - 盲標工作表（`eval gold-todo`，`eval/runner.py:1139-1178`）：record 內容與 label 的背景（fault_type、origin、affected、fault 的相對時間），不列是哪個方法引用的，也不列弱標籤。
  - 判定（`eval gold-add`，`eval/runner.py:1196-1213`；`merge_gold`，`eval/relevance.py:123-148`）：只接受 `human:<name>`；只附加，已判定的鍵不能改；「略」（null）不寫入。
  - 分數（`gold_score`，`eval/relevance.py:103-109`）：gold precision = relevant 數 / 已判定數（該方法 existence 成立的不同引用中有判定的，不分是誰的樣本抽到的）；
    沒有判定時是 null。gold coverage = 已判定數 / existence 成立的不同引用數。
- **彙總**（017 §4；`EVIDENCE_LAYERS`、`_evidence_aggregate`，`eval/runner.py:695-703`、`:797-804`）：existence、temporal、service、origin、weak、gold precision、
  gold coverage 各自報 n（該值不是 null 的 incident 數）、平均（每個 incident 等權）與 F3 的同一種 bootstrap 區間（只用這些 incident 的 run group）。
- **永不合成**：各層不合成一個數字，也不與 F2 的主要指標合併（v1 §4、017 §4）；evidence 不進任何 Gate 條件（F8）。
  各方法的 n 不同，gold precision 不是 paired 的比較（017「補註（2026-10-16）」）。
- 報告時機（017「對實驗的影響」）：一個方法的 gold 樣本全部判定之前，不報它的 gold precision，只報 coverage 並寫明原因。held-out 的 100 照這一條（030 §4 第 8 項）；
  Pilot README 也照這一條（使用者 2026-10-16 回答 NEXT A12 選 (b)：dump-all 的樣本有 4 筆略，只報它的 coverage 0.840；017「補註（2026-10-16，第二則）」；F13 第 6 項）。
  `scores.json` 照程式仍有每個 incident 與彙總的 gold precision 欄位（評分程式不變），報告不引用樣本沒有全部判定的方法的這個欄位。

### F5. 放棄作答與嘗試（v1 §2；023 §5、§6；026 解讀 17–19）

- **放棄作答** = `origin_candidates` 是空清單（schema :81）。方法可以自己提交空的清單；LLM 方法沒有合格的提交時，harness 寫 `agent/harness.py:69-72` 的 `_abstain`
  （fault 兩個 null、三個集合都空、沒有 evidence），出現在：更正 2 次仍不合格（`invalid_submission`）、沒有提交（`no_submission`）、預算或回合到上限、
  最後一次提示後仍沒有提交（`turn_limit`、`tool_budget`）（`agent/harness.py:175-191`、`:203-243`；decision 020 §2、§3）。
- **一律算錯、留在分母**（v1 §2「放棄作答（null / 空清單）一律算錯，不排除在分母之外」）：放棄作答的 incident 照常計分、留在每個指標的分母。
  程式沒有另外的放棄作答分支，照 F2 逐欄計分（`eval/score.py:45-63`）：
  - harness 或 runner 補上的 `_abstain`（fault 兩個 null；`origin_candidates`、`affected_services`、`user_symptom.kinds` 都是空的；沒有 evidence）：F2 的 11 個指標都是 0
    （label 的 affected 與 user symptom kinds 都至少 1 個，`schemas/incident_label.schema.json:87`、`:103`）；沒有引用，所以 evidence 各層是 null、不進 n（F4）。
  - 方法自己提交、`origin_candidates` 是空清單、其他欄位有值的 prediction：origin 的 3 個指標是 0，其他欄位照 F2 逐欄計分、可能得分；有引用時 evidence 照 F4 計分。
    例：Pilot 的 Agent INC-008（F12 第 2 項）fault 兩個 null、affected 是空的，但 `user_symptom.kinds` 是 `["none"]`，所以 `symptom_exact` = 1、`symptom_jaccard` = 1.0。
    這就是下面的讀法（F13 第 7 項）。
  - 兩種都是失敗（origin_top1 = 0），失敗類別都是 `no_answer`（022；`eval/failures.py:54-55`）。
  - **讀法**（F13 第 7 項，使用者 2026-10-16 選 (i)）：v1 §2 的「一律算錯」與 026 解讀 19 的「每一層都算錯」都照上面的逐欄計分讀——`origin_candidates` 空的 prediction
    在 origin 的 3 個指標都是 0、失敗類別是 `no_answer`、留在分母，其他欄位照提交的內容計分；harness 與 held-out 補位的 `_abstain` 每個欄位都是空的，所以 F2 的每一層
    （11 個指標）都是 0（沒有引用，evidence 各層是 null、不進 n）。
- **held-out 的嘗試**（`eval/runner.py:507-606`）：
  - 每個（方法, 列表內 incident）只跑一次：有 prediction 或嘗試已關閉就不再跑（:551）；prediction 與 transcript 原子寫入、永不覆寫，transcript 先寫、prediction 最後寫（:589-594）；
    每個方法一個 O_EXCL 的 `run.lock`（:524-532）。
  - 只有 `CallError` 且 reason 是 `api_error` / `transport_error` 時重試（`RETRYABLE`，:443；:571-575），依停止原因、不看輸出內容；每個（方法, incident）總共最多 2 次嘗試
    （`HELDOUT_MAX_ATTEMPTS`，:444）。其他錯誤、不合格的 prediction、中斷的嘗試都關閉該 incident（`_closed`，:493-499）。每次嘗試記進 `attempts.jsonl`，含用量。
  - **重試規則之後仍沒有 prediction → 放棄作答**（026 解讀 19）：評分時補上 `_abstain`（method version `none`、usage `{}`），留在分母、算 `no_answer`，
    列在 scores.json 的 `heldout.unanswered` 並附每次嘗試的結果（`eval/runner.py:877-880`）；不讀未完成的嘗試留下的 transcript（:885）。所有方法（包括 stat-anomaly）都一樣。
  - 還有列表內 incident 的嘗試可能繼續、或該方法的 `run.lock` 存在時，拒絕評分（:816-818、:827-829）。失敗嘗試的次數與用量另外加總報告（:830-834、:841）。
- **Pilot 沒有嘗試紀錄，也沒有放棄作答的補位**（F13 第 4 項）：Pilot 的評分要求每個計分的 incident（F6）都有該方法的 prediction 檔；缺檔時讀檔失敗
  （`eval/runner.py:882`），`eval score` 印 `error: …`、exit 2（`eval/__main__.py:134-136`），不寫 scores.json 與 table.md（之前的檔案不變），也不補 `_abstain`
  （補位只用於 held-out，026 解讀 19）。Pilot 上方法自己提交的放棄作答照常計分（上面）。
- 不付費重跑 Agent（023「使用者決定」4）；Gate 只用第一次執行的結果（023 §6）。

### F6. 計分的 incident（分母與排除）

- **Pilot**（`incidents_in`，`eval/runner.py:425-440`）：injection 的 split 是 pilot、有發布的 snapshot、沒有被撤回的 incident（撤回的列在 `excluded`，decision 025 修訂 3；
  :854-861）；合成範例的 id 一律拒絕（decision 027）。
- **held-out**：只用驗證過的 `heldout_incidents.json` 列出的 incident（:862；清單在任何方法執行之前寫一次，023 §5.5、026 解讀 24）；關閉的 slot 與詞彙命中的 incident
  不在列表內，永不執行（:547）。held-out run group 永不撤回（026 解讀 30）。
- **兩個 set 都一樣**：
  - 沒有 leakage audit 就拒絕評分（:863-865）；詞彙命中 > 0 的 incident 不進任何分數、列出（decision 015；:867-869）。
  - 有效 label = `label.reviewed.json`，沒有時 `label.json`（018 §7；`collect/review.py:175-182`）；`fault_exercised = false` 的 incident 不進任何分數、列出
    （018 §6；`eval/runner.py:870-873`）。held-out 的 label 在任何方法執行之前全部 review 完（023 §5、026 解讀 24）。
  - 其餘 incident 全部計分，包括放棄作答（F5）。
- 報告列出排除的 incident 與原因、reviewed 與 a priori 的 label 數、review 與 a priori 的差異、看過方法輸出才 review 的 incident（`eval/runner.py:939-940`、`:954-973`）。

### F7. Paired 比較（023 §7）

- 指令：`python -m eval compare --method <a> --against <b> --set <set>`（`eval/__main__.py:117-121`；`compare_methods`，`eval/runner.py:1272-1318`）：只讀兩個方法的 scores.json。
- **差異**（`eval.compare.paired`，`eval/compare.py:13-34`）：兩個方法都計分的 incident 上，每個 incident 的 a − b；依 run group（取 a 的列）分組；
  與 F3 相同的 bootstrap（`random.Random(0)`、10,000 次、有放回地抽 run group、percentile 取 249 / 9,750）重抽**差異**，所以兩個方法用同一組重抽的 run group。
  估計量 = 共同 incident 的平均差異（`mean_diff`）。只有一個方法計分的 incident 列在 `only_in_one`（held-out 的 Gate 不允許有，F8）。
- 比較的指標：四個主要指標（`metrics = MAIN_METRICS`，`eval/runner.py:1272`）。
- **LOFO**（`eval/compare.py:37-46`；只描述）：每次拿掉一個 fault（兩個方法的列中出現的 fault）重算 paired 差異；拿掉後沒有共同 incident 時 n = 0、沒有區間。
- 輸出 `results/<set>/compare-<a>-vs-<b>.json` / `.md`，記錄讀到的兩份 scores.json 的 sha256（:1296、:1303-1317）。held-out：第一個陳述是 `heldout_guard`、兩份分數都必須屬於目前的
  freeze 與清單（:1278-1294），輸出不列 incident 或 run group id（:1299-1302，F11）。**唯一的例外**（023「實作說明：Gate 計算」的「輸出」）：
  `paired` 的 `only_in_one` 列出只有一個方法計分的 incident id（`eval/compare.py:34`；寫進 compare 的 JSON，:1297；`eval compare` 也把 `paired` 印到 stdout，
  `eval/__main__.py:120-121`）。held-out 上兩份 scores.json 屬於同一份清單、每個列表內 incident 都計分（放棄作答也算），所以正常情況下它是空的；不是空的時 gate 拒絕（F8）。
- 不是 paired 的：各方法自己的區間（F3）、gold precision（F4）。

### F8. Gate 判準（023 §7；023「實作說明：Gate 計算」解讀 1–14；「追加（2026-10-10，第二次）」第 6 項）

- 指令：`python -m eval gate --method agent --against stat-anomaly --set <set>`（`eval/__main__.py:122-126`；`gate_methods`，`eval/runner.py:1321-1408`；純函式在 `eval/gate.py`）。
  只讀已寫好的 scores.json 與 compare 輸出，**不執行任何方法、不重抽 bootstrap**；`gate.md` 與 `gate.json` 都先產生完，再各自 atomic replace，`gate.md` 先、`gate.json` 最後（:1404-1407）。
- **前置檢查**（任何一項不符：exit 2、什麼都不寫；`eval/__main__.py:134-136`）：
  - held-out：第一個陳述是 `heldout_guard`（:1332）；每份 scores.json 都必須屬於目前的 freeze 與清單（:1357-1360）；兩個方法計分的 incident 必須相同，
    compare 的 `only_in_one` 不是空的就拒絕（:1378-1380；放棄作答本來就在分母）。
  - `--method` 只接受 agent（`GATE_METHOD`，:315；:1338-1340）；`--against` 必須是登錄的統計 baseline（`STATISTICAL_BASELINES` = `("stat-anomaly",)`，:314；:1341-1342），
    而且**每一個**統計 baseline 都要有分數與 compare，不略過、不當成通過（:1343-1381）。
  - scores.json 記錄的方法與 set 必須與路徑相符（:1354-1356）；compare 必須由目前的兩份 scores.json 算出（sha 相符）、set 與方法相符、origin_top1 的 bootstrap 是
    10,000 次、seed 0（`GATE_BOOTSTRAP`，`eval/gate.py:13`；:1371-1377）。缺少或過期 → 要求重跑 `eval compare`。
- **條件 1（唯一的主要檢定）**（`eval/gate.py:17-25`）：對每個統計 baseline，Agent − baseline 的 origin_top1 paired 差異（F7）的 95% 區間下界 **> 0**（嚴格）；
  對每一個都成立才成立。估計量是所有計分 incident 的平均（023 §7）。
- **條件 2（可重現的穩定失敗）**（`eval/gate.py:31-53`）：至少有一個 fault，Agent 的 origin_top1 答錯（≠ 1，包括放棄作答）的 incident 數 ≥ ⌈K/2⌉（且至少 1 個），
  而且這些 origin 答錯的失敗中**嚴格過半**（2/4 不算）屬於 022 的同一個類別（六類任一，包括 no_answer、coverage；只有 fault_type 錯的失敗不在分母）。
  - K（`eval/runner.py:1384-1387`）：只看 Agent 有計分 incident 的 fault。held-out = 驗證過的清單中該 fault 的 slot 數（設計的 K = 5；`collect/heldout.py:738-742`、
    `eval/runner.py:1007-1008`；`per_fault` 取 K 與計分數的較大者，`eval/gate.py:84`），缺格（關閉的 slot、詞彙命中排除）**不降低**門檻；
    Pilot = 該 fault 實際計分的 incident 數，K < 2（`PILOT_MIN_K`，`eval/gate.py:28`）的 fault 不評估（not evaluated，不算成立；使用者 2026-10-10 確認）。
    held-out 照 023 §7 原文（`min_k = 1`）。
  - origin 答錯、卻沒有失敗類別的列 → 拒絕，要求重新評分（`eval/gate.py:40-41`）。
- **條件 3（錯誤主要來自推理路徑）**（`eval/gate.py:56-62`）：Agent 的所有失敗（022 §1：origin 或 fault_type 錯）中，not_seen + seen_misread 的比例 **> 0.5**（嚴格）；
  沒有任何失敗時比例無定義、不成立。
- **判定**（`eval/gate.py:110-123`）：只在 held-out。三個條件都成立是 `pass`，否則 `not_passed`；只用第一次執行的結果（023 §5、§6）。
  Pilot 照樣計算三個條件，但 `decision` 是 null，輸出寫明「DIAGNOSTIC ONLY, NOT a Gate decision」（SPEC §5）。
- **不是 Gate 條件、只描述**（`descriptive`，`eval/runner.py:1390-1397`）：
  - fault_type、affected_f1、symptom_exact 的 paired 差異（fault_type 對 stat-anomaly 有結構性差異；不宣稱做過多重比較校正，023 §7）；
  - origin_top1 的 LOFO 下界；
  - 對每個統計 baseline、每個 fault 的 origin_top1 答對數 k / K 與差異方向（+ / 0 / −，只在兩者都計分的 incident 上；`eval/gate.py:93-107`）；
  - coverage 次數 / 失敗數、沒有 review 就分類的失敗數、失敗數 / 計分數（`eval/gate.py:65-71`；SPEC「收尾或改題」，沒有門檻）；
  - Agent 與每個統計 baseline 的各 fault 表：各 fault 平均、有計分 incident 的 fault 的等權平均、所有計分 incident 的平均、缺格清單（`eval/gate.py:74-90`、`eval/runner.py:987-1018`）。
  「Agent 幾乎全對」沒有數值門檻，程式不判斷；那時要另開新的集合並寫新的 decision（023 §7）。
- 不付費重跑 Agent（023「使用者決定」4）；若使用者另外批准重跑，結果另列、不取代第一次（023 §7）。
- bootstrap 能說明與不能說明的範圍照 023 §7「其他」：能說明同一個 stack、traffic profile、這 10 個 fault（含 variant）、fault 10 分鐘的條件下重新收集的變異；
  不能推廣到其他 fault、variant 或系統；不分層重抽相對於固定設計偏保守；n 很小或比例接近 0、1 時 percentile 區間覆蓋不足。

### F9. 失敗分類（022）

- 失敗 = origin_top1 或 fault_type 答錯（022 §1；affected 與 symptom 的錯只在分層分數中報告）。每次失敗只歸一類，依 022 §2 的條件（`classify`，`eval/failures.py:50-64`；
  `CATEGORIES`，:13）：
  - `no_answer`：`origin_candidates` 空，或 transcript 的停止原因不是 `submitted` / `submitted_after_limit`（:14、:54-55）；
  - `coverage`：label 是 `catalog+review`，而且 `telemetry_coverage` 每一種 signal 都不是 `origin`（:56-58）；沒有 review 的 label 不能判為 coverage；
  - `mechanism`：origin 對、fault_type 錯（:59-60）；
  - `not_seen` / `seen_misread`：exposure 裡沒有 / 有 origin 在 fault 期間的證據（:63-64；`origin_evidence_seen`，:21-47：`stats:*`、origin 的 `stats:<服務>:<分鐘>-<分鐘>`
    與 fault 期間的分鐘重疊、origin 的 `m-`、時間在 `[fault_start, fault_end + 60 s]` 內的 origin 的 `s-` / `l-` / `p-`）。「fault 期間」在三種證據都是同一個窗
    `[fault_start, fault_end + 60 s]`：每分鐘統計的「fault 期間的分鐘」是這個窗的開始到結束所在的分鐘（:24-27、:34；F13 第 3 項，使用者 2026-10-16 選 (i)；022「補註（2026-10-16）」）；
  - `rule_limit`：沒有 exposure 紀錄（沒有 transcript）的方法，也就是統計 baseline，其餘的失敗（程式在判斷 exposure 之前先看有沒有 transcript，:61-62）。
- 報告（`eval/runner.py:909-915`）：各類別的次數、佔失敗數的比例、依難度分層、每次失敗的 incident 與類別、沒有 review 就分類的失敗數（022 §2、§3）。
- Gate：條件 2 用 Agent 各 fault origin 答錯的類別，條件 3 用 not_seen + seen_misread 的比例，coverage 的比例只描述（F8）。
- 022 的已知限制（「看過 origin 在 fault 期間的任何 record」比「看過能證明故障的 record」寬鬆）照舊；022 在 Pilot 上的那一次修訂沒有使用（022 補註）。

### F10. 預算、用量與可見資料（024；只報告，不計分）

- 每次 `eval run` 在任何 prediction 之前寫 `run_config.json`：method、set、model、該次的預算、可見資料範圍；本機模型另有 `llm`（decision 029）；
  held-out 另有 freeze 與清單的 sha256，續跑必須完全相同（`eval/runner.py:534-544`、`:632-634`）。
- 表的「Budgets, usage and visible data」（`_usage_aggregate`、`_usage_lines`，`eval/runner.py:736-745`、`:1085-1136`）：預算與可見資料範圍（取自 run_config）；
  usage 7 欄在計分 incident 上的 n / mean / median / max（null 不計入 n）；cost 總和（任何一個是 null 時寫 `-`）；停止原因次數；
  exposure 的 `records_seen`、`records_share`、`overview_share`（`exposure_of`，`eval/runner.py:709-726`）；推論主機的 latency 條件與不符的 incident（decision 029、029 修訂 1；
  `eval/runner.py:748-794`）。
- 這些數字描述「方法實際看了多少、用了多少」，**不是指標**，不進任何方法比較或 Gate 判定（024 §3）。

### F11. Held-out 的報告規則（023 §5–§7；026 解讀 20、23；030）

- 每個 held-out eval 路徑（run、score、gold-todo、對 held-out incident 的 gold-add、compare、gate）的第一個陳述是 `heldout_guard`：freeze 檢查通過、清單驗證過
  （`eval/runner.py:448-465`；026 解讀 20）。
- 每個方法的 scores.json / table.md 另有 held-out 段（`eval/runner.py:925-927`、`:1041-1065`）：freeze 紀錄與清單的 sha256、Pilot 之後移除的 fault（附依據）、
  關閉的 slot、不在清單的 incident（附原因）、放棄作答與每次嘗試的結果、失敗嘗試的次數與用量、latency 不是正式條件的失敗嘗試。
- **compare 與 gate 的輸出不列 incident id 或 valid run group id**（023「實作說明：Gate 計算」的「輸出」；026 解讀 23）：關閉的 slot 只列 slot、fault 與原因，
  排除的 incident 只列 slot 與原因（`eval/runner.py:1263-1269`、`:1299-1302`、`:1399-1402`）；incident id 只在清單與各方法自己的結果（prediction、`attempts.jsonl`、scores.json、table.md）裡。
  唯一的例外照 023：compare 的 `paired` 的 `only_in_one`（F7）；held-out 上正常情況下它是空的，不是空的時 gate 拒絕（F8）。
- **只用第一次執行的結果**；方法 bug 的修正版只能另列為探索性結果；評分或稽核的 bug 依 023 §6 修正後所有方法重新評分、Gate 用修正後的數字、前後都報告——
  但 freeze 之後沒有修正路徑：使用者 2026-10-10 對 026「待使用者決定」2 選「沒有偏好」，維持現況，freeze 之後發現 bug 時 held-out 評測停止，由使用者當時決定（NEXT A4）。
- 門檻、prompt、預算、指標、incident 清單永不因 held-out 結果修改（023 §6）；看到 held-out 結果之後本文件永不修改。
- **發布**（decision 030）：README 在 freeze 時封存；結果只寫進 `docs/decisions/100-heldout-final-results.md` 與同一個 commit 的一份新 decision（031–099），
  內容照 030 §4 從凍結工具寫出的檔案轉寫、不手算、不新增指標或分析，寫入範圍照 030 §5。
- Pilot 的數字只是診斷、不是 Gate 判定，永不與 held-out 合併（SPEC §5、v1 §3、030 §4 第 11 項）。

### F12. Pilot 上與 013 有關的經驗（都不改 013）

Pilot：10 個 incident、每個 fault 1 個；四個方法都已執行並評分（stat-anomaly v2；dump-all 與 retrieval 是 decision 021 修訂後 2026-10-15 的重跑；Agent 是 2026-10-11 的執行，
都在 RTX 5070 Ti 上，decision 029 修訂 1）；evidence gold 在 2026-10-16 標完（115 筆判定、75 筆 relevant，全部 human:jingwen）。數字以 `data/external/results/pilot/*/table.md`
為準，NEXT「目前位置」與 README 有摘要。與 013 有關的觀察：

1. **格式**：LLM 方法把 evidence 寫成 id 字串的清單、或把概覽的每分鐘列拼成 `m-` id（例如 `m-ad+012:00`），都在提交時被 schema 拒收。處理都在方法側
   （decision 020「修正（2026-10-10）」的更正訊息、decision 021 在 Pilot 上的修訂），**格式、id pattern 與引用驗證都沒有放寬**（021「不變的」）。
   修訂前 dump-all 的 INC-009、INC-010 因此以 `invalid_submission` 放棄作答，照 v1 §2 算錯、留在分母（修訂前的結果封存、照樣報告）。
2. **放棄作答**：Agent 在 INC-008 自己提交了 origin 候選、fault 與 affected 都空的答案（`user_symptom.kinds` 是 `["none"]`；停止原因 `submitted`；失敗類別 `no_answer`），
   照 v1 §2 留在 n = 10 的分母（Agent origin_top1 0.600）。程式照 F2 逐欄計分：origin、fault、affected 的指標都是 0，`symptom_exact` = 1、`symptom_jaccard` = 1.0
   （計入 Agent 的 symptom_exact 0.60；F5、F13 第 7 項）。它沒有引用，所以 Agent 的 evidence 各層 n = 9。
3. **origin 候選數**：LLM 方法多半只給一個候選（dump-all 只有 INC-007 給了 2 個；retrieval 每個 incident 1 個；Agent 除了 INC-008 的 0 個，每個 1 個），它們的 origin_top3 / RR 幾乎等於 top-1
   （stat-anomaly 的 origin_top3 是 0.900）。保留為失敗分析的發現（022 補註 (b)、021），不改 top-3 / RR 的定義或輔助指標的地位。
4. **existence**：Agent 0.956（n = 9，[0.867, 1.000]）；未解析的引用照 v1 §4 留在 existence 的分母，沒有移除。dump-all 與 retrieval 修訂後都是 1.000。
5. **引用的時間範圍**：Pilot 的 prediction 有 43 個 `s-` / `l-` 引用帶 `t0` / `t1`（agent 8、retrieval 30、dump-all 5）；existence 不看這個範圍，gold 以 `(id, t0, t1)` 為單位
   （INC-003、INC-004 的重複項目就是同一筆紀錄的不同範圍，分開判定，017「補註（2026-10-16，第二則）」）。見 F13 第 1 項。
6. **Gate 的 Pilot 診斷**（F8 的程式）：條件 1 不成立（agent − stat-anomaly 的 origin_top1 差 0.000，95% [−0.500, 0.500]，n = 10）；條件 2 不評估（每個 fault K = 1 < 2）；
   條件 3 不成立（3 / 6 = 0.50，不是嚴格大於 0.5）。2026-10-16 gold 之後重算，結果不變（gold 不進任何條件）。
7. **gold**：coverage 低於 1（017 每個方法、每個 incident 最多抽 5 筆；dump-all 的樣本有 4 筆略）；各方法的 n 不同（stat-anomaly 8、dump-all 10、retrieval 7、agent 9），
   不是 paired 的比較（017 兩則補註）。dump-all 的樣本沒有全部判定，Pilot 的報告只報它的 coverage、不報 gold precision（使用者 2026-10-16，F4、F13 第 6 項）。

以上都**沒有**改變 013 的格式、指標、彙總、bootstrap、比較或 Gate 判準。

### F13. 文件與程式的差異（寫定時只記錄；2026-10-16 依使用者決定處理）

依 CLAUDE.md「發現 SPEC 與程式現況不一致，先記錄差異」：寫定時照實記錄、不選邊、不改任何程式或規則。同日使用者決定（NEXT A11，原話「A11：Freeze 前檢查七處差異；
純文件問題直接修正，涉及評分邏輯或研究協定的問題先詢問我。」）：
- **分類**（嚴格）：**純文件** = 文件寫錯或沒寫程式已有的行為，改文字不改變任何計分、分類、evidence 的鍵、驗證或協定的結果；其他都是**評分邏輯或研究協定**，先問使用者。
- **結果**：第 2、4、5、6 項是純文件，**已處理（2026-10-16）**——只改文字（第 5 項是程式的錯誤訊息文字，行為不變），Pilot 的分數不需要重算。
  第 1、3、7 項是評分邏輯或研究協定，先問使用者（寫定時程式與規則都沒有改；使用者 2026-10-16 三項都選 (i)，見下面「使用者的回答」）。
  每一項兩個選項：(i) 維持程式現在的行為，把它寫成規則（只改文字，Pilot 數字不變）；
  (ii) 改程式或規則（下面寫明改什麼、哪些 Pilot 數字會變——以 `data/external/results/pilot/` 的 prediction、transcript 與 gold 唯讀重算，**沒有重新評分**）。
  選 (ii) 改的是哪一份 decision 的規則，依項目不同（2026-10-16 審查補正；原本把三項都寫成 013 的修改）：
  - **第 7 項**改 013 的計分（v1 §2），是由 Pilot 引起的 013 修改，依 023 第 16 行要和本修訂併在一起（013 已宣告 used，宣告不變）。
  - **第 1 項**改 017 §1 的鍵 `(id, t0, t1)`（`eval/relevance.py:21-22` 的 `key`），**第 3 項**改 022 §2 第 3 項的分鐘窗（`eval/failures.py:25-27`、`:34`）。
    017 與 022 各自「可在 Pilot 上修訂一次」（017 開頭、022 開頭）。在看過 Pilot 結果（2026-10-16 的 gold 與失敗分類）之後改它們，依 A9 確認前提時用的同一個標準
    （decision 023「追加（2026-10-16）」第 1 項：看過 Pilot 結果之後改了該 decision 的規則 = 用掉額度）就是 **017 / 022 在 Pilot 上的那一次修訂**：
    freeze 的宣告要改成 `"017": {"status": "used", "decision": <寫下這次修訂的 decision 檔>}`（第 3 項則是 `"022": …`），
    使用者 A9 的 waived（原話「前提是確認沒有使用任何 Pilot 修訂額度」）對該項就不再成立。第 3 項若使用者認為 (ii) 只是讓程式符合 022 的原文、不算修訂，
    也要使用者明確決定；沒有決定時照上面的標準算 used。
  - **只有第 1、3 項都選 (i)**，A9 的五項 waived（NEXT「下一步」6 與 023 追加的 JSON）才維持不變。
  - 不論哪一項選 (ii)：freeze 之前改程式、測試與本節（以及 017 / 022 的修訂紀錄），重新評分 Pilot（主要指標以外的 Pilot 數字照實更新）；
    freeze 之後 013、017、022 都不能改（026 解讀 7）。（三項都選 (i)，所以這一點沒有發生。）
- **使用者的回答（2026-10-16，freeze 之前）**，原話：
  > 第 1、3、7 項都選 (i)，繼續 freeze

  三項都採用 (i)：維持程式現在、已實作的行為，把它寫成規則（不是新的規則）——第 1 項寫在 F1 的 `evidence` 列與 F4，第 3 項寫在 F9 與 022「補註（2026-10-16）」，
  第 7 項寫在 F5。只改文字：程式、測試、schema 都沒有改，Pilot 的分數、compare、gate 都不變、不需要重新評分。第 1、3 項都選 (i)，所以 017、022 沒有在 Pilot 上修訂，
  A9 的五項 waived 維持不變（023「追加（2026-10-16）」第 1 項的 JSON 照原樣）；第 7 項選 (i)，013 的計分不變（013 的宣告仍是 used，不受影響）。
  下面各項的 (ii) 保留為當時呈現給使用者的選項與唯讀重算的影響，沒有採用。

1. **非 `m-` 引用的時間範圍**（評分邏輯：evidence 的鍵；**使用者 2026-10-16 選 (i)**）：v1 §1 只寫 `m-` 可加 `t0` / `t1`；schema 允許每一種 id 帶範圍（`schemas/prediction.schema.json:117-138`），
   Pilot 上確實出現（F12 第 5 項）。程式：`Snapshot.resolve` 只對 `m-` 檢查範圍，其他種類的範圍不影響 existence（`collect/snapshot.py:93-96`）；弱標籤的時間對 `s-` / `l-` / `p-`
   不看範圍（`eval/relevance.py:58-63`）；但弱標籤與 gold 的去重鍵 `(id, t0, t1)` 包含範圍（`eval/relevance.py:21-22`），所以同一個非 `m-` id 帶不同範圍是不同的項目、各自進分母、各自盲標。
   這個鍵本身是 017 的規則，不是只寫在程式裡：017 §1「以 `(id, t0, t1)` 去重」（不分 id 的種類），017「補註（2026-10-16）」的 gold precision 算法同樣以 `(id, t0, t1)` 去重；
   使用者 2026-10-16 較早的決定 2（原話「重複證據維持原規則，不修改 91 筆工作表的標註單位」）也已確認標註單位是 `(id, t0, t1)`，鍵不同就是不同的項目、
   各自判定（017「補註（2026-10-16）」第 2 點；INC-003、INC-004 的重複項目就是照這樣分開標註）。真正沒寫到的只有 013 v1 §1（只說 `m-` 可帶範圍）與 F1、F4。
   所以依 F13 開頭的嚴格分類，第 1 項的 (i) 其實接近純文件；但它涉及 evidence 的鍵，寫定時列為評分邏輯，仍請使用者確認（2026-10-16 審查補正）；使用者選 (i)。
   - (i) 維持（**採用**）：就是 017 §1 與使用者決定 2 已決定的現狀；只在 F1、F4 補寫「每一種 id 都可帶 `t0` / `t1`；非 `m-` 的範圍不影響 existence 與時間，但是 017 的鍵的一部分」。
     Pilot 數字都不變，A9 的 `"017": waived` 不變。
   - (ii) 改（沒有採用）：非 `m-` 引用的鍵只用 id（範圍忽略；`m-` 不變），弱標籤、gold 的判定、`gold_score` 與 `gold-todo` 的抽樣都用這個鍵（`eval/relevance.py` 的 `key`）。
     這會推翻使用者決定 2，而且是 017 在 Pilot 上的那一次修訂（`"017"` 要改宣告為 used，見 F13 開頭）。
     Pilot 上：每個方法自己的引用都沒有同一個非 `m-` id 帶不同範圍，所以 existence 與弱標籤（含 n）不變，`gold-todo` 的樣本也不變；
     gold 的 115 筆判定中有 4 個 id 各以兩個鍵判定、兩次都是 relevant（INC-003 `l-183383e77b3fcbbb`、`s-f104de301de60d25`；INC-004 `l-eb65d558d1e75819`、
     `s-51f116ed17bcc2ec`，後者一次在 2026-10-10），合併後是 111 個鍵、71 個 relevant，沒有互相衝突的判定（gold 是只附加的檔案，合併的寫法另外要決定）；
     2026-10-15 的 91 筆工作表會是 87 筆（INC-003 第 2/3、10/11 項與 INC-004 第 2/3 項各合成一項，INC-004 第 5 項已判定、不再列出）。
     分數：只有 retrieval 的 INC-005 多 2 個引用算已判定（同一個 id 以別的鍵判定過），它的 gold coverage 5 / 22 → 7 / 22，retrieval 的 gold coverage
     0.667 [0.345, 0.892] → 0.680 [0.384, 0.903]；各方法的 gold precision（retrieval INC-005 是 5 / 5 → 7 / 7，仍是 1.0）、其他 coverage、主要指標、compare 與 gate 都不變。
   - **處理（2026-10-16，(i)）**：F1 的 `evidence` 列與 F4（existence、弱標籤的鍵與時間）照程式寫明：每一種 id 都可帶 `t0` / `t1`，鍵是 `(id, t0, t1)`、不分 id 的種類
     （`eval/relevance.py:21-22`），帶範圍的非 `m-` 引用在弱標籤與 gold 是另一個鍵；existence（`collect/snapshot.py:93-96`）與弱標籤的時間
     （`eval/relevance.py:56-63`）不看非 `m-` 的範圍。程式、017 都不變，Pilot 數字不變，`"017": waived` 不變（017 維持放棄 Pilot 修訂）。
2. **usage 的 null**（純文件；**已處理 2026-10-16**）：v1 §1 寫「沒有的填 null」；schema 不要求任何 usage 鍵（`schemas/prediction.schema.json:139-193` 沒有 `required`），報告以 `.get` 讀，
   缺鍵與 null 相同（`eval/runner.py:741`）；held-out 補位的放棄作答 usage 是 `{}`（`eval/runner.py:879`）。處理：F1 的 `usage` 列照程式的行為寫明（每個鍵都可以省略，缺鍵與 null 相同、
   都不計入 n，cost 總和遇到缺值寫 `-`）；v1 §1 是保留的原文，以 F1 為準。usage 只報告、不計分（F10），沒有任何結果改變。
3. **022 的「fault 期間的分鐘」**（研究協定：失敗分類；**使用者 2026-10-16 選 (i)**）：022 §2 第 1 項的窗是 `[fault_start, fault_end + 60 s]`，第 3 項寫「涵蓋至少一個 fault 期間的分鐘」；
   程式第 3 項用同一個含 60 s 的窗算分鐘範圍（`eval/failures.py:25-27`、`:34`）。
   - (i) 維持（**採用**）：把「fault 期間」在 022 §2 的三種證據都定為第 1 項的窗 `[fault_start, fault_end + 60 s]`（寫進 022 的對應與 F9）。Pilot 數字都不變，A9 的 `"022": waived` 不變。
   - (ii) 改（沒有採用）：第 3 項的分鐘範圍只算 `[fault_start, fault_end]`（`eval/failures.py:27` 的 `last_minute` 用不含 60 s 的 end；span / log / point 的窗不變）。
     這是在看過 Pilot 的失敗分類之後改 022 的分類程式，照 F13 開頭的標準是 022 在 Pilot 上的那一次修訂（`"022"` 要改宣告為 used；若使用者認為不算修訂，要明確決定）。
     Pilot 上**沒有任何失敗的類別改變**：dump-all（INC-006、007、010）與 retrieval（INC-006、010）的 seen_misread 都來自 exposure 的 `stats:*`；Agent 的 3 次 seen_misread
     （INC-004、009、010）在不含 60 s 的分鐘範圍下仍然成立；stat-anomaly 沒有 exposure（rule_limit）。失敗表、Gate 條件 2、條件 3（3 / 6）都不變。
     只會在 held-out 上有差別（某個 Agent 失敗唯一的 origin 證據是 fault 結束後那一分鐘的每分鐘統計時，會從 seen_misread 變成 not_seen）。
   - **處理（2026-10-16，(i)）**：F9 與 022「補註（2026-10-16）」寫明 022 §2 第 3 項的「fault 期間的分鐘」用第 1 項的同一個窗 `[fault_start, fault_end + 60 s]`
     （`eval/failures.py:24-27`、`:34`）。這是使用者確認的既有實作（`eval/failures.py` 最後一次改動在 Pilot 之前），**不是 022 在 Pilot 上的那一次修訂**；
     程式與分類都不變，Pilot 的失敗表與 Gate 診斷不變，`"022": waived` 不變。
4. **Pilot 上缺 prediction 檔**（純文件；**已處理 2026-10-16**）：放棄作答的補位（026 解讀 19）只寫 held-out，沒有文件寫 Pilot 的這個情況。程式在 Pilot 缺檔時讀檔失敗、`eval score` exit 2，
   不補放棄作答（`eval/runner.py:882`）。處理：F5 照程式寫明（印 `error: …`、exit 2、不寫 scores.json 與 table.md、不補 `_abstain`；2026-10-16 以暫時的測試資料確認過）。
   Pilot 的 10 個 incident 每個方法都有 prediction，沒有任何結果改變。
5. **過期的錯誤訊息**（程式的訊息文字；**已處理 2026-10-16**）：`eval/runner.py:1349` 在 LLM 方法沒有分數時原本提示「once the paid LLM methods are approved, NEXT A1」；原 A1 已處理
   （本機模型，decision 029；NEXT「已處理」）。處理：訊息改成「`python -m eval run|score --method <m> --set <set>` first: the LLM method's results must exist on the <set> set」，
   不再提付費批准或 NEXT A1；行數、例外類別與行為不變（exit 2、什麼都不寫）。測試 `tests/test_gate.py::test_without_agent_scores_the_gate_names_the_missing_llm_results_not_a_paid_approval`
   （先寫、看到失敗才改）。
6. **gold precision 的報告時機**（**已處理 2026-10-16**，使用者回答 NEXT A12 選 (b)）：017「對實驗的影響」寫「各自的樣本要先標完，gold precision 才會出現在報告中」，
   030 §4 第 8 項照字面用於 held-out；寫定時 freeze 之前的 Pilot README 草稿報出樣本有 4 筆略的 dump-all 的數字。處理：Pilot README 也照 017 的字面，不報 dump-all 的
   gold precision、只報 coverage 0.840 並寫明原因與 4 筆略的理由（017「補註（2026-10-16，第二則）」的「使用者的回答」；F4）。Pilot 與 held-out 用同一條規則，沒有差異；
   評分程式與 scores.json 不變。
7. **放棄作答「一律算錯」的範圍**（評分邏輯；**使用者 2026-10-16 選 (i)**）：v1 §2 寫「放棄作答（null / 空清單）一律算錯」，026 解讀 19 對重試之後仍沒有 prediction 的補位寫「每一層都算錯」；
   程式沒有放棄作答的分支，照 F2 逐欄計分（`eval/score.py:45-63`）。補位的 `_abstain`（`agent/harness.py:69-72`；held-out 評分時的補位 `eval/runner.py:877-880`）
   每個欄位都是空的，所以 F2 的每一層（11 個指標）都是 0（沒有引用，evidence 各層是 null、不進 n），與兩處文字一致；方法自己提交、`origin_candidates`
   是空清單但其他欄位有值的 prediction，其他欄位照常得分（Pilot Agent INC-008 的 `symptom_exact` = 1；F5、F12 第 2 項）。
   兩種讀法下 origin 的各指標都是 0、失敗類別都是 `no_answer`；差別只在其他欄位。
   - (i) 維持（**採用**）：「一律算錯」指 origin（`origin_candidates` 空 = origin 各指標 0、`no_answer`、留在分母），其他欄位照 F2 逐欄計分；補位的 `_abstain` 在 F2 的每一層
     （11 個指標）都是 0（evidence 各層是 null、不進 n）。Pilot 數字都不變。
   - (ii) 改（沒有採用）：`origin_candidates` 是空清單的 prediction 在 F2 的 11 個指標都算 0、不論其他欄位（`eval/score.py` 的 `score_incident` 加一個放棄作答的分支）。
     Pilot 上只有 Agent 的 INC-008 是這種 prediction（stat-anomaly、dump-all、retrieval 的計分 prediction 都有 origin 候選；修訂前封存的 dump-all INC-009、010 是 `_abstain`，
     已經都是 0，也不重新評分）：它的 `symptom_exact` 1 → 0、`symptom_jaccard` 1.0 → 0。Agent 的 symptom_exact 0.60 [0.30, 0.90] → 0.50 [0.20, 0.80]（README 的 Pilot 表要改）、
     symptom_jaccard 0.70 [0.45, 0.95] → 0.60 [0.35, 0.85]；依難度（hard）與各 fault（adHighCpu）的表中 INC-008 所在的格；compare agent − stat-anomaly 的 symptom_exact
     （只描述）0.10 [−0.30, 0.50] → 0.00 [−0.50, 0.50]；compare 的 LOFO symptom_exact 列（只描述）：拿掉 adHighCpu 的那一列不變（INC-008 不在裡面），
     其他 9 列的平均差各少 0.111（例如拿掉 adManualGc：0.000 → −0.111），下界變成 −0.333（拿掉 cartFailure、emailMemoryLeak）或 −0.556（其他 7 列；原本 −0.222 到 −0.444）；
     Pilot `gate.md` 的描述段：「other main metrics」的 symptom_exact 0.100 [−0.300, 0.500] → 0.000 [−0.500, 0.500]，Agent 的各 fault 表 adHighCpu 的 symptom_exact
     1.000 → 0.000、equal weight 與 incidents 列 0.600 → 0.500（`gate.md` 的 LOFO 只有 origin_top1，不變）。以上用 `eval/compare.py` 的 `paired`、`lofo` 對記憶體裡的分數唯讀重算
     （現在的值與 `compare-agent-vs-stat-anomaly.md` 逐列相同），沒有寫任何檔。origin、fault、affected 的指標、失敗類別、evidence 與 Gate 的三個條件都不變。
   - **處理（2026-10-16，(i)）**：F5 寫明讀法——v1 §2 的「一律算錯」與 026 解讀 19 的「每一層都算錯」照 `eval/score.py` 的逐欄計分讀：
     origin 空的 prediction origin 各指標 0、`no_answer`、留在分母，其他欄位照提交的內容計分；harness / held-out 補位的 `_abstain` 每個欄位都是空的，所以 F2 的每一層
     （11 個指標）都是 0（沒有引用，evidence 各層是 null、不進 n）。013 的計分與程式都不變，Pilot 數字不變（Agent INC-008 的 `symptom_exact` 仍是 1）。

### 為什麼

- 023 第 16 行規定 §7 寫進 013 正式版、用掉 013 唯一的一次修訂；freeze 檢查強制 013 宣告為 used（`collect/freeze.py:161-162`）。
- 一份文件寫齊 held-out 用的格式、評分、比較與 Gate，每一項指向出處與程式行號：freeze 之後程式與文件一起被釘住（026 解讀 7），held-out 的報告（030 §4）可以逐項對照。
- 只轉述既有規則：正式版寫在 Pilot 結果之後，任何新的指標、門檻或解讀都可能受 Pilot 結果影響（EXPERIMENT_RULES「先固定 metrics」；CLAUDE.md「不得看到結果後偷偷修改指標」）。
- 出入先記錄：CLAUDE.md「先記錄差異，再處理，不要默默改規格」；改程式或規則是另一個決定。2026-10-16 使用者決定純文件的直接修正、評分邏輯或研究協定的先問（F13），所以只有不改變任何結果的文字被修正；
  先問的第 1、3、7 項使用者選 (i)，同樣只把既有的實作寫明。

### 放棄的替代方案

- **依 Pilot 的觀察順便調整 013**（例如因為 LLM 方法多半只給一個 origin 候選而改 top-3 / RR 的地位，或改放棄作答的計分）：都是看過 Pilot 結果之後的設計變更，
  屬於使用者的決定（NEXT A11）；本修訂不做（F13 第 7 項的 (ii) 就是改放棄作答的計分，使用者 2026-10-16 選 (i)，沒有採用）。
- **把正式版寫成新的 decision 檔**：freeze 的宣告可以指名 frozen commit 中任何 decision 檔，但 023、026 都寫「013 正式版」，其他文件以「013 §n」引用；留在 013 讓引用不斷。
- **在出入處直接改程式或文件的規則**：會在 Pilot 結果之後改變評分或規則，而且不經使用者；寫定時只記錄，2026-10-16 只處理純文件的項目，第 1、3、7 項由使用者在 (i)、(ii) 之間決定（同日三項都選 (i)；F13）。

### 對實驗的影響

- 寫定時程式、schema、測試都沒有改。2026-10-16（F13 第 5 項）只改了 `eval/runner.py:1349` 的錯誤訊息文字並新增一個測試；評分程式、schema 不變，Pilot 的分數、compare、gate 都不需要重算。F13 第 1、3、7 項使用者 2026-10-16 都選 (i)：只改文字（F1、F4、F5、F9、F13 與 022 的補註），程式不變，Pilot 不需要重新評分；017 / 022 沒有在 Pilot 上修訂，freeze 宣告的 017 / 022 維持 waived（F13 開頭）。
- freeze 的 Pilot 修訂宣告：`"013": {"status": "used", "decision": "docs/decisions/013-prediction-format-and-layered-scoring.md"}`（NEXT「下一步」6）。
- 正式版在 frozen commit 裡；freeze 之後本文件不能改（026 解讀 7），之後的紀錄只能寫進 NEXT 或新的 decision。
- held-out 的評分、compare、gate 與 100 的報告都照本節（也就是照上面列出的出處與程式）。
