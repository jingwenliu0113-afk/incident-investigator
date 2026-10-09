# Incident Investigator

**問題：LLM Agent 能不能可靠地只靠一份凍結的 telemetry snapshot 做 production 的 root-cause analysis？**

在 OpenTelemetry Demo 3.1.0（鎖定 image digest）上以 flagd 注入故障，收集 traces / logs / metrics，凍結成 Agent 唯一可讀的 snapshot，
再用分層指標比較 Agent 與三種 baseline。Ground truth 與 Agent 可讀資料在檔案系統上物理隔離。

> 狀態（2026-10-09）：Core 的工具鏈完成並測試（600+ 個測試），兩次非正式冒煙測試在真實 stack 上走通整條 pipeline；Pilot Set（10 個 incident）待收集，**目前還沒有任何方法的結果**。
> 進度與待辦見 [`NEXT.md`](NEXT.md)，所有設計決策見 [`docs/decisions/`](docs/decisions/)。

## 結果

尚無結果。Pilot 收集與 label review 完成後，這裡會放：各方法在 Pilot 上的分層分數（含 run-group bootstrap 95% 區間）、
依難度（Easy / Medium / Hard）分層的主要指標、失敗分類的比例。LLM 方法要等模型、預算與成本經使用者批准後才會執行。

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
產生的 raw OTLP JSON 經過真正的 normalize，得到與上表相同的兩棵樹（`incidents/INC-000/normalized/` 與 `ground_truth/`），
另有統計 baseline 的範例預測與 `sample.json`（`synthetic: true`、每個檔案的 sha256）。真實 incident 的 snapshot 永遠不進 git。

**2 分鐘 demo**（只讀合成範例、不寫檔；印出的分數來自合成資料，**不是結果**）：

```bash
uv run python -m eval demo
```

## 評分

- 分層、不合成一個數字：**fault_type、origin_top1、affected_f1、symptom_exact**（主要），加上 family、top-3、RR、precision / recall（decision 013）。
- 區間：run-group cluster bootstrap（10,000 次、seed 0）；兩個方法比較用同一組重抽的 paired 差異（decision 023）。
- Evidence：existence（引用的 id 是否存在）與 relevance（弱標籤 temporal / service，加上人工盲標的 gold subset）分開報（decision 017）。
- 每個方法的表也列出可見資料範圍、預算、usage（tokens、工具呼叫、retrieval、latency、cost）與實際看過多少資料；只報告、不計分（decision 024）。

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

Pilot 收完、review、leakage audit 完成，而且 LLM 方法已批准並在 Pilot 上跑過之後才能開始（目前被 NEXT A1 擋住）。
沒有 freeze 紀錄時，所有 `--set heldout` 的收集與方法執行一律拒絕。

```bash
uv run python -m collect heldout-plan --amendments <amendments.json>       # 寫一次 docs/heldout/plan.json，之後 commit
uv run python -m collect heldout-freeze --pilot-revisions <revisions.json> # 寫一次 slots.json 與 freeze.json，只把這兩個檔案 commit 成一個 commit
uv run python -m collect next --set heldout                                # 下一個 slot（stderr 是 slot 與待人處理的 slot）
./tools/with-mac-lock uv run python -m collect run --set heldout --flag F --variant V   # 不接受 --seed
uv run python -m collect process --incident <INC> --labeler agent:claude-code
uv run python -m eval leakage --set heldout                                # 全部 slot 收完、process 之後
uv run python -m collect review-sheet --incident <INC>                    # 使用者 review，saw_method_outputs 必須是 false
uv run python -m collect heldout-list                                      # 寫一次 heldout_incidents.json（只印數量）
uv run python -m eval run --method stat-anomaly --set heldout              # 每個方法、每個 incident 只跑一次
uv run python -m eval score --method stat-anomaly --set heldout
uv run python -m collect status --set heldout
```

## Repo

`env/`（版本鎖定、soak）、`collect/`（收集、normalize、label、review）、`eval/`（評分、leakage、relevance、失敗分類、比較）、
`baselines/`（統計、dump-all、retrieval）、`agent/`（工具、執行框架）、`schemas/`、`data/samples/`（只有合成範例）、`docs/decisions/`（001–027）、`docs/heldout/`（held-out 的 plan、slot 清單、freeze 紀錄；Pilot 後才產生）、`tests/`。
