# 002 — Run 紀錄拆成「provenance manifest」與「隔離的 fault injection record」

- 狀態：Accepted（2026-10-08）
- 影響範圍：資料格式、目錄結構、Agent / baseline 可讀範圍

## 背景

- SPEC Core §1 要求記錄 fault config、random seed、收集時間窗等。
- SPEC Core §2 建議 `data/external/incidents/INC-001/manifest.json` 與 `raw/`、`normalized/` 放在一起。
- SPEC Core §3 與 CLAUDE.md 要求 ground truth 與 Agent 可讀資料**物理隔離**。

如果把 fault config（flag 名稱、variant、fault on/off 時間）直接寫進 incident 目錄裡的 `manifest.json`，
只要 Agent sandbox 掛錯一層目錄、或 baseline 的 retrieval 多讀了一個檔案，答案就直接外洩。

## 決策

1. 一份 run 的紀錄拆成兩種文件：
   - `data/external/incidents/<INC-nnn>/manifest.json`：只放 provenance
     （project commit、env lock sha256、實際機器、compose 指令、traffic 設定、seed、收集時間窗、檔案 checksum）。
     格式：`schemas/run_manifest.schema.json`。
   - `data/external/ground_truth/run_groups/<RG-nnn>/injection.json`：fault config
     （flagd flag、variant）與實際的 `normal_start / fault_on / fault_off / end` 時間。
     格式：`schemas/fault_injection.schema.json`。
2. 一個 **run group** = 一次 fault 執行（一次 stack 啟動 + 一次故障）；一個 **incident** = 從 run group 切出的一個 telemetry 時間窗。
   `injection.json` 列出它切出的 `incident_ids`，所以 split 以 run group 為最小單位（SPEC §3）。
3. ID 一律是不透明的流水號（`INC-001`、`RG-001`），路徑本身不能透露 fault。
4. 防呆機制（`collect/records.py`、`collect/layout.py`）：
   - manifest schema 的頂層 `additionalProperties: false`，`fault`、`run_group_id`、`fault_start`、`origin_service` 這類欄位寫進去就驗證失敗。
   - `check_manifest(..., flag_catalog=...)` 會掃描整份 manifest，只要出現任何 flagd flag 名稱就報錯。
   - `DataLayout.is_ground_truth(path)` 讓之後的 Agent 工具與 baseline 可以拒絕讀 ground truth 路徑。
5. 正式（formal）收集額外要求：project 有 commit 且不是 dirty、env lock sha256 與當前 lock 一致、有 Docker engine 資訊。

## 為什麼

- 隔離靠「目錄樹分開 + schema 拒收」，而不是靠「大家記得不要讀那個欄位」。
- 收集時間窗留在 manifest（provenance 需要它），但 fault 的**時間**屬於答案的一部分，只放在 ground truth。

## 放棄的替代方案

- **單一 manifest 加一個 `fault` 區塊，只要求 Agent 只讀 `normalized/`**：一次掛載錯誤就會外洩，不符合「物理隔離」。
- **把 ground truth 加密後跟 snapshot 放在一起**：多一套金鑰管理，沒有比目錄分開更安全。
- **ground truth 放到 repo 之外的另一顆磁碟**：之後真的需要再做；目前用 `data/external/ground_truth/` 加上 sandbox 只掛 `incidents/<id>/normalized/` 就足夠。

## 對實驗的影響

- Agent 與所有 baseline（M7）只能拿到 `incidents/<id>/normalized/`；`manifest.json` 給人和 eval 用。
- SPEC 差異記錄：SPEC §1 把 fault config 列在「必須記錄」，§2 把 manifest 放在 incident 目錄。
  我們的解讀是 fault config **有**記錄，但記錄在 ground truth 那一側；manifest 只放不含答案的 provenance。這是解讀，不是改規格。
- 已知的殘留洩漏面（留給 Core §6 leakage audit 和 M2 收集協定處理）：
  - 若 normal period 固定長度，時間窗本身就暗示了 fault_on 時間 → 收集時用 seed 隨機化 normal period 長度。
  - 原始 telemetry 裡可能有 flag evaluation 的 span / log（例如 `feature_flag.key`）→ normalize 階段與 leakage audit 必須處理。
  - flagd-ui 的 scheduler 啟動事件只寫 stdout（不進 OTLP），但 flagd 本身的 trace 可能帶 flag key → 同上。


## 修訂（2026-10-08，第一個 incident 收集之前；review 確認的問題）

- 「決策」第 1 點把 `seed` 放在 manifest。decision 009（含修訂）之後，seed 是 normal period 與 recovery 長度的**唯一**隨機來源
  （`collect.rungroup._draws`），而 manifest 的 `window.start` 就是 normal 開始：有 seed 加上 repo 的程式，就能把 fault_on / fault_off 算到秒，
  等於把 ground truth 放在 manifest。
- 改為：**seed 只放在 ground-truth 側**（`injection.json`、`run.json`、label）。manifest 不再有頂層 `seed`，`traffic.seed` 一律是 `null`；
  schema 會擋下兩者。label 的 seed 仍與 `injection.json` 比對（SPEC Core §1「記錄 random seed」仍然成立，只是記在 ground-truth 側）。
- 仍然存在、而且由協定公開的資訊：window 長度與「fault_on 在 window 開始後 10–15 分鐘」這個範圍（decision 009）。
