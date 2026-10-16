# Incident Investigator

**問題：LLM Agent 能不能可靠地只靠一份凍結的 telemetry snapshot 做 production 的 root-cause analysis？**

在 OpenTelemetry Demo 3.1.0（鎖定 image digest）上以 flagd 注入故障，收集 traces / logs / metrics，凍結成 Agent 唯一可讀的 snapshot，
再用分層指標比較 Agent 與三種 baseline。Ground truth 與 Agent 可讀資料在檔案系統上物理隔離。

> 狀態（2026-10-16）：Core 的工具鏈完成並測試（1,100+ 個測試）；**Pilot Set 的 10 個 incident 已正式收集並完成人工 label review**；
> 四個方法（統計 baseline 與三個 LLM 方法）都已在 Pilot 上執行並評分（下表；診斷用，不是 Gate 判定）。LLM 方法：付費 API 延後，使用者 2026-10-10 批准本機模型 qwen3.5 9B（Ollama，decision 029）；
> 2026-10-11 起模型在使用者的 RTX 5070 Ti 桌機上推論（029 修訂 1，eval 仍在 Mac）；dump-all 與 retrieval 依 decision 021 的 Pilot 修訂（2026-10-11，使用者決定）在 2026-10-15 重跑。
> 四個方法引用的 evidence 依 decision 017 抽出的樣本都已由使用者人工盲標（2026-10-10 統計 baseline 的 28 筆；2026-10-16 三個 LLM 方法的 91 筆，87 筆寫入、4 筆略），
> 並在 gold 之後重新評分（下面「Evidence」）。held-out 在 freeze 之後收集，Gate 只在 held-out 上判定；**Core 還沒完成，沒有進 Advanced**。
> 進度與待辦見 [`NEXT.md`](NEXT.md)，所有設計決策見 [`docs/decisions/`](docs/decisions/)。

## 結果

**Held-out 的最終結果**：[`docs/decisions/100-heldout-final-results.md`](docs/decisions/100-heldout-final-results.md)（decision 030 預留的固定檔名）。
這個檔案在 held-out 評測完成後才新增，**在那之前這個連結打不開**。README 在 held-out freeze 時封存、之後不再修改，所以下面只有 Pilot 的結果；
held-out 的數字只寫在那個檔案與同時新增的 decision 紀錄裡。

**Pilot Set（10 個 incident，每個 fault 一個；用途是驗證 pipeline、label 與 baseline 難度，不是 test，不進 held-out）**。
label 全部經人工 review（decision 018，review 時未看任何方法輸出）。區間：run-group cluster bootstrap 95%（n = 10，區間很寬）。

| 方法 | fault_type | origin_top1 | origin_top3 | affected_f1 | symptom_exact |
|---|---:|---:|---:|---:|---:|
| stat-anomaly（統計 baseline v2） | 0.30 [0.00, 0.60] | 0.60 [0.30, 0.90] | 0.90 [0.70, 1.00] | 0.77 [0.66, 0.87] | 0.50 [0.20, 0.80] |
| dump-all + LLM（021 修訂後） | 0.60 [0.30, 0.90] | 0.70 [0.40, 1.00] | 0.80 [0.50, 1.00] | 0.74 [0.59, 0.88] | 0.50 [0.20, 0.80] |
| retrieval + LLM（021 修訂後） | 0.60 [0.30, 0.90] | 0.80 [0.50, 1.00] | 0.80 [0.50, 1.00] | 0.73 [0.54, 0.89] | 0.50 [0.20, 0.80] |
| Agent + tools | 0.50 [0.20, 0.80] | 0.60 [0.30, 0.90] | 0.60 [0.30, 0.90] | 0.69 [0.46, 0.89] | 0.60 [0.30, 0.90] |
| *dump-all（修訂前，封存）* | *0.50* | *0.70* | *0.70* | *0.66* | *0.40* |
| *retrieval（修訂前，封存）* | *0.50* | *0.80* | *0.80* | *0.83* | *0.50* |

- stat-anomaly 依難度（leakage audit）：easy 5 個、hard 5 個；origin_top1 兩者都是 0.60。
- stat-anomaly 的失敗（origin 或 fault type 錯）8 個：`mechanism`（origin 對、機制錯）4、`rule_limit`（統計規則本身的限制）4。
- LLM 方法：本機模型 qwen3.5 9B（q4_K_M、`num_ctx` 262,144、think 關、temperature 0、Ollama 0.35.0 釘選；decision 029），推論在使用者的 RTX 5070 Ti 桌機（decision 029 修訂 1：snapshot、ground truth 與評分留在 Mac，只有模型呼叫經 SSH tunnel 送到桌機）。**結論只限於這個本機模型。** origin 的候選數（失敗分析的發現 (b)，不改）：提出方案時的那次執行，三個方法每個 incident 最多一個候選（top3 = top1）；021 修訂後重跑，dump-all 在 INC-007 給了 2 個（origin_top1 0.70、top3 0.80），retrieval 仍每個 1 個（0.80 / 0.80），Agent（未重跑）每個 1 個、INC-008 沒有答案（0.60 / 0.60）。dump-all 修訂前有 2 個 incident 把概覽的每分鐘列當成證據（不是可引用的紀錄 id），更正兩次後放棄作答。使用者 2026-10-11 決定用 decision 021 在 Pilot 上的那一次修訂處理：概覽寫明它的列是彙總、沒有 id、不能引用（列本身、引用驗證、評分門檻、模型、資料、預算與推論主機都不變），dump-all 與 retrieval 在相同條件下重跑（2026-10-15），上表修訂前（封存）與修訂後並列；Agent 的輸入不變，不重跑。修訂後兩個方法的 20 個 incident 都提交了答案（沒有放棄作答），引用全部存在（existence 1.0）；但 dump-all 仍有 4 個 incident（INC-007、008、009、010）的第一次提交與第一次更正都引用概覽列，第三次、也就是最後一次允許的提交才改用紀錄 id——錯誤降低但沒有消除：最後一次允許的提交才改正。retrieval 修訂後沒有引用概覽列；它有 3 個 incident 的查詢沒有找到任何紀錄、沒有附證據（允許，不計入 evidence 分數）。Agent 的 existence 是 0.96（引用了不存在但格式正確的 id；020 的範圍，這次不改）。每個 incident 的平均 latency：retrieval 40 s、dump-all 139 s、Agent 188 s（中位數 76 s）。Evidence 的分數見下面「Evidence」。
- Gate 條件在 Pilot 上的診斷（不是 Gate 判定）：條件 1（Agent 的 origin_top1 顯著高於統計 baseline）不成立（差 0.00，95% [-0.50, 0.50]）；條件 2 在 Pilot 上不評估（每個 fault 只有 1 個 incident）；條件 3 不成立（3/6 = 0.50，未超過一半）。held-out（每個 fault 5 個）在 freeze 之後收集，Gate 只在 held-out 上判定。
  gold 不是 Gate 條件；gold 之後重算的 compare 與 gate（2026-10-16）結果不變。

**Evidence（Pilot；decision 013 §4、017）**：各層分開報，永不合成一個數字，也不與上表的主要指標合併。n = 有引用的 incident 數（Pilot 上四層的 n 相同）；
平均是這 n 個 incident 的**等權平均**，區間同上（run-group cluster bootstrap 95%）。**各方法的 n 不同（引用的 incident 不同），所以不是 paired 的比較。**

| 方法 | n | existence | 弱標籤：temporal 且 service | gold precision | gold coverage |
|---|---:|---:|---:|---:|---:|
| stat-anomaly（統計 baseline v2） | 8 | 1.000 [1.000, 1.000] | 1.000 [1.000, 1.000] | 0.906 [0.719, 1.000] | 1.000 [1.000, 1.000] |
| dump-all + LLM（021 修訂後） | 10 | 1.000 [1.000, 1.000] | 0.640 [0.340, 0.900] | 0.540 [0.240, 0.840] | 0.840 [0.710, 0.960] |
| retrieval + LLM（021 修訂後） | 7 | 1.000 [1.000, 1.000] | 0.571 [0.143, 0.857] | 0.571 [0.143, 0.857] | 0.667 [0.345, 0.892] |
| Agent + tools | 9 | 0.956 [0.867, 1.000] | 0.833 [0.611, 1.000] | 0.756 [0.444, 1.000] | 1.000 [1.000, 1.000] |

- **gold precision**：人工盲標的判定（017 §3）。每個方法、每個 incident = relevant 的引用數 / 已有 gold 判定的引用數（引用以 `(id, t0, t1)` 去重；
  判定不分是哪個方法的樣本抽到的）；跨 incident 是該方法至少有一筆已判定引用的 incident 的等權平均，不是把所有引用合在一起算
  （stat-anomaly 的 0.906 是 7 個 1.0、1 個 0.25 的平均；28 筆合在一起的 25 / 28 = 0.893 不是報告的數字）。
- **樣本與 coverage**：017 每個方法、每個 incident 以固定種子抽**最多 5 筆**引用給人判定；coverage = 已判定 / 存在的引用。標註時「略」的項目不寫入、
  不進分母，只降低 coverage。retrieval 的 0.667 來自引用多的 incident（INC-002、005、006 各 45、22、25 筆，只有抽到的樣本有判定）；dump-all 的 0.840 一部分來自
  4 筆略（INC-003 1 筆、INC-004 2 筆、INC-009 1 筆），它們都在 dump-all 的樣本裡，所以 **dump-all 的樣本沒有全部判定**；stat-anomaly、retrieval、Agent 的樣本全部判定。
- **標註**：全部由使用者（human:jingwen）方法盲標（不知道是哪個方法引用的、看不到弱標籤）：2026-10-10 統計 baseline 的 28 筆；2026-10-16 三個 LLM 方法的 91 筆
  （一次一個 incident），87 筆寫入、4 筆略（理由見 decision 017「補註（2026-10-16，第二則）」）。gold 共 115 筆判定、75 筆 relevant。
  017 的判準把 fault 造成的下游錯誤與延遲也算 relevant，所以 relevant 不表示這筆紀錄證明了根因機制（使用者在 INC-007、INC-011 的註記）。
- **各 incident**：gold precision 是 0 的 incident——dump-all INC-006、008、009、010，retrieval INC-006、008、010，Agent INC-009、010；stat-anomaly 最低是 INC-006 的 0.25。
  弱標籤會把故障時間窗內、affected 服務上看起來正常的紀錄也算進去，所以與 gold 分開報（decision 017）。
- 修訂前（封存）的 dump-all / retrieval 不補標、不重新評分，這裡不報它們的 gold precision（封存的分數只含評分當時與既有判定重疊的 gold：dump-all n = 1、
  coverage 0.025，retrieval n = 0）。

## Pipeline

```text
locked OTel Demo stack ──flagd fault──> run group（warm-up → 穩定閘門 → normal 10–15 分 → fault 10 分 → recovery 5–10 分）
        │ raw OTLP export（collector 第一站，loss accounting）                      decision 008, 009
        ▼
  ground_truth/ (injection、run record、label、review)      incidents/<INC>/normalized/ (Agent 唯一可讀)
        │                                                          │ canonical snapshot ctel/1           decision 011
        │                                                          ▼
        │                       stat-anomaly │ dump-all + LLM │ retrieval + LLM │ Agent + tools        decision 014, 019–021
        │                                                          │ prediction（無自由文字答案欄位）    decision 013
        └──────────────── 分層評分、evidence existence / relevance、leakage audit、失敗分類 ◀────── decision 013, 015, 017, 022
```

- **故障**：10 個 Core fault（error response、unreachable dependency、added latency、lock contention、CPU、GC、memory leak），
  每個都事先登錄 a priori label（origin / affected / user symptom，decision 016），收集後由人 review（decision 018）。
- **防洩漏**：normalize 在發布前移除 flag / harness 痕跡並做詞彙檢查；snapshot 的時間窗長度與 fault 時間無關；
  每個方法只拿到「前 10 分鐘正常」這一句框架（decision 014）；leakage audit 依「誰發出只在 fault 期間出現的錯誤」分 Easy / Medium / Hard（decision 015）。

## Dataset schema

| 檔案 | 內容 | 可讀者 |
|---|---|---|
| `incidents/<INC>/normalized/` | `snapshot.json`（時間窗、服務、各檔 sha256）、`spans.jsonl`、`logs.jsonl`、`metric_series.jsonl`、`metric_points.jsonl`、`resources.jsonl`（`schemas/canonical_telemetry.schema.json`） | 所有方法 |
| `incidents/<INC>/manifest.json` | commit、env lock、機器、traffic profile、checksum（`schemas/run_manifest.schema.json`） | provenance（方法不讀） |
| `ground_truth/run_groups/<RG>/` | `injection.json`（fault、排程、seed、集合）、`run.json`（有效性判定與觀察）、harness 取樣 | 只有評分端 |
| `ground_truth/incidents/<INC>/` | `label.json`（a priori）、`label.reviewed.json`、`label_review.json`、`leakage_audit.json`、evidence gold | 只有評分端 |

Label 欄位（`schemas/incident_label.schema.json`）：fault_type / fault_family（封閉用詞）、origin_service、affected_services、
user_symptom、fault_start / fault_end、traffic_profile、seed、telemetry_coverage。

**範例（合成資料，decision 027）**：[`data/samples/synthetic/`](data/samples/synthetic/) 是程式產生的 incident `INC-000`，**不是收集到的資料**：
產生的 raw OTLP JSON 經過真正的 normalize，得到上表第一列完整的 `incidents/INC-000/normalized/`，以及 ground truth 的一部分
（`ground_truth/run_groups/RG-000/injection.json`、`ground_truth/incidents/INC-000/` 的 catalog `label.json` 與 `normalize_report.json`）；
上表其餘的檔案（`manifest.json`、`run.json` 與 harness 取樣、`label.reviewed.json` / `label_review.json`、`leakage_audit.json`、evidence gold）範例都沒有。
另有統計 baseline 的範例預測與 `sample.json`（`synthetic: true`、每個檔案的 sha256）。真實 incident 的 snapshot 永遠不進 git。

**2 分鐘 demo**（只讀合成範例、不寫檔；印出的分數來自合成資料，**不是結果**）：

```bash
uv run python -m eval demo
```

## 評分

- 分層、不合成一個數字：**fault_type、origin_top1、affected_f1、symptom_exact**（主要），加上 family、top-3、RR、precision / recall（decision 013）。
- 區間：run-group cluster bootstrap（10,000 次、seed 0）；兩個方法比較用同一組重抽的 paired 差異（decision 023）。
- Evidence：existence（引用的 id 是否存在）與 relevance（弱標籤 temporal / service，加上人工盲標的 gold subset）分開報（decision 017）。
  **gold precision**：每個方法、每個 incident = relevant 的引用數 / 已有 gold 判定的引用數（引用以 `(id, t0, t1)` 去重；判定不分是哪個方法的樣本抽到的）；
  跨 incident 是該方法至少有一筆已判定引用的 incident 的**等權平均**（報 n 與區間），不是把所有引用合在一起算。標註時「略」的項目不寫入、不進分母，只讓
  coverage（已判定 / 存在的引用）變低。各方法的 n 不同，所以不是 paired 的比較。
- 每個方法的表也列出可見資料範圍、預算、usage（tokens、工具呼叫、retrieval、latency、cost）與實際看過多少資料；只報告、不計分（decision 024）。
- Gate（SPEC Gate，decision 023 §7）：`python -m eval gate` 只讀已寫好的 scores.json 與 `eval compare` 的輸出（不跑任何方法），寫 `results/<set>/agent/gate.json` 與 `gate.md`。
  **held-out 上才是 Gate 判定**（pass / not passed，只用第一次執行的結果）；Pilot 上只是診斷，**不是 Gate 判定**。

## 失敗分類（decision 022）

每次 origin 或 fault type 答錯，依序歸入一類：

| 類別 | 意義 |
|---|---|
| `no_answer` | 沒有提交答案（預算、回合、格式） |
| `coverage` | review 判定 snapshot 在 origin 上看不到故障（telemetry 不足） |
| `mechanism` | origin 對、機制錯 |
| `not_seen` | 方法從沒看過 origin 在 fault 期間的資料（探索 / 檢索失敗） |
| `seen_misread` | 看過了仍答錯（推理失敗） |
| `rule_limit` | 統計 baseline 的規則限制 |

## 使用方式

```bash
uv run pytest -q -m "not network and not docker_daemon"
```

```bash
uv run python -m collect pilot-loop --labeler agent:claude-code
```

（整個 Pilot：每個 fault 一個 run，只在 run 期間持有 Mac heavy lock，之後 normalize → replay → label；收齊後 leakage audit 與統計 baseline。）單步：

```bash
uv run python -m collect next --set pilot
```

```bash
./tools/with-mac-lock uv run python -m collect run --set pilot --flag paymentFailure --variant 100%
```

```bash
uv run python -m collect process --incident INC-001 --labeler agent:claude-code
```

```bash
uv run python -m eval leakage --set pilot
```

```bash
uv run python -m eval run --method stat-anomaly --set pilot
```

```bash
uv run python -m eval score --method stat-anomaly --set pilot
```

正式收集需要 Mac heavy lock（`MACHINE_POLICY.md`）；完整 telemetry、raw 與結果都在 `data/external/`，不進 git。

### Held-out（decision 023、026）

Pilot 收完、review、leakage audit 完成，而且 LLM 方法已批准並在 Pilot 上跑過之後才能開始（LLM 方法 2026-10-10 已批准，2026-10-11 在 Pilot 上執行，
dump-all 與 retrieval 依 021 的修訂在 2026-10-15 重跑；freeze 之前還剩的步驟見 [`NEXT.md`](NEXT.md)「下一步」）。
freeze 另要求目前 env lock 有通過的 soak，以及每個 LLM 方法的 Pilot 結果用的正好是要凍結的設定（decision 026 修訂 3）。
沒有 freeze 紀錄時，所有 `--set heldout` 的收集與方法執行一律拒絕。

```bash
uv run python -m eval version-check --set pilot                            # 只讀：每筆 Pilot prediction 都是方法目前的版本（021）；exit 1 = 有問題
uv run python -m collect heldout-plan --amendments <amendments.json>       # 寫一次 docs/heldout/plan.json，之後 commit
uv run python -m collect heldout-freeze --pilot-revisions <revisions.json> # 寫一次 slots.json 與 freeze.json，只把這兩個檔案 commit 成一個 commit
uv run python -m collect next --set heldout                                # 下一個 slot（stderr 是 slot 與待人處理的 slot）
./tools/with-mac-lock uv run python -m collect run --set heldout --flag F --variant V   # 不接受 --seed
uv run python -m collect process --incident <INC> --labeler agent:claude-code
uv run python -m collect ack-failures --set heldout --slot <slot> --reason <…> --decided-by <person>   # 待人處理的 slot：人看過 run record 之後
uv run python -m eval leakage --set heldout                                # 全部 slot 收完、process 之後
uv run python -m collect review-sheet --incident <INC>                    # 使用者 review 的工作表，saw_method_outputs 必須是 false
uv run python -m collect review --incident <INC> --file <filled.json> --reviewer human:<name>   # 寫 label.reviewed.json 與 label_review.json
uv run python -m collect heldout-list                                      # 寫一次 heldout_incidents.json（只印數量）
uv run python -m eval run --method stat-anomaly --set heldout              # 每個方法、每個 incident 只跑一次
uv run python -m eval score --method stat-anomaly --set heldout
uv run python -m eval compare --method agent --against stat-anomaly --set heldout   # Gate 條件 1 的 paired 差異
uv run python -m eval gate --method agent --against stat-anomaly --set heldout      # SPEC Gate 判定：gate.json / gate.md
uv run python -m eval gold-todo --set heldout                              # evidence gold 工作表（017，人盲標）；gold-add 之後重新 score → compare → gate（gold 不影響 Gate 條件）
uv run python -m collect status --set heldout
```

- held-out 的 `collect review` 也要乾淨的 checkout（freeze 檢查）；`heldout-list` 要求每個 incident 都有 `label.reviewed.json` 與 `label_review.json`。
- 一個 slot 累計 3 個沒有被確認的非 valid run group 就「待人處理」，`collect next` 跳過它（同時 3 個就全部停止）。人看過 run record 之後用
  `collect ack-failures --set heldout --slot <slot>` 記錄確認（與 Pilot 的 `ack-failures` 相同，只附加、不刪任何紀錄），該 slot 重新計數再收；
  `heldout-list` 寫出之後拒絕（使用者決定 2026-10-10，decision 026 解讀 11）。held-out run group 不能撤回（decision 026 解讀 30）。
- review 判定 `fault_exercised = false` 的 slot 會回到 open：再 `collect next --set heldout` → `run` → `process` → `eval leakage --set heldout` → review 一次；
  再次未觸發就關閉並列出（decision 023 §5.3）。全部 slot 都是 filled 或 closed 之後才寫 `heldout-list`。
- `eval run` / `score` 對每個方法都要做（統計 baseline 與三個 LLM 方法；LLM 方法的 `eval run` 要在 `./tools/with-remote-ollama` 之下，每個方法一次，decision 029 修訂 1）；`compare` 對每個統計 baseline 各做一次；`gate` 做一次，讀全部統計 baseline 的 compare（缺任何一個就拒絕、不寫檔）。
- `version-check` 是流程上的檢查：`eval score` 與 `heldout-freeze` 都不呼叫它（freeze 分不出 021 修訂前後的 Pilot 執行，decision 021「審查（2026-10-11）」），
  所以在 Pilot 評分之前與 freeze 之前各跑一次。
- freeze 之後 README 不能再改（只允許 NEXT.md 與新的 decision 檔），所以這段在 freeze 之前定稿。held-out 的結果只寫在
  `docs/decisions/100-heldout-final-results.md` 與同時新增的 decision 紀錄（decision 030）。

## Repo

`env/`（版本鎖定、soak）、`collect/`（收集、normalize、label、review）、`eval/`（評分、leakage、relevance、失敗分類、比較）、
`baselines/`（統計、dump-all、retrieval）、`agent/`（工具、執行框架）、`schemas/`、`data/samples/`（只有合成範例）、`docs/decisions/`（001–030；100 保留給 held-out 最終結果，decision 030）、`docs/heldout/`（held-out 的 plan、slot 清單、freeze 紀錄；Pilot 後才產生）、`tests/`。
