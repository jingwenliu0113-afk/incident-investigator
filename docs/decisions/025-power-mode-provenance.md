# 025 — 收集時的電力模式記錄在 provenance

- 狀態：Accepted（2026-10-08）；在任何正式 Pilot incident 收集之前寫定。只增加紀錄，不改收集協定、有效性判定或任何指標。
- 影響範圍：run record 與 incident manifest 的 `machine`（`schemas/run_manifest.schema.json` 新增可選的 `machine.power`）；`collect status` 的輸出。

## 背景

- SPEC §1：manifest 必須記錄實際收集的機器。decision 002 記錄 role、OS、CPU、記憶體與 Docker，但沒有電力模式。
- 2026-10-09（台北時間晚上）使用者說明：Mac 使用自動電力模式時，會產生 performance-sensitive 正式結果的 Mac 實驗（正式 incident 收集、正式 benchmark）要延後。
  電力模式（自動 / 低耗電 / 高效能）會改變 CPU 時脈與排程，也就改變 latency、CPU 使用率等 telemetry；同一個 set 的 incident 必須在相同條件下收集才能比較。
- 目前沒有任何紀錄可以事後確認一個 run group 是在哪種模式下收集的。

## 決策

1. `collect.provenance.power_facts`：在 Mac 上以唯讀的 `pmset -g`（使用中的設定）與 `pmset -g batt`（電源）取得
   `{"source": "AC Power" | "Battery Power" | …, "settings": {"powermode" | "lowpowermode" | "highpowermode": 原始字串}}`；
   只記錄 `pmset` 實際列出的鍵，不推測。不是 Mac 或沒有 `pmset` 時為 null。**不修改任何電源設定。**
2. `machine_info` 在 run 開始（provenance，`up` 之前）記錄 `machine.power`；run record 與 manifest 都帶這個欄位。
   manifest schema 的 `machine.power` 為可選（之前寫的 manifest 仍然有效）。只記錄開始時的狀態。
3. `python -m collect status --set pilot` 列出每個有效 run group 的電力設定（沒有紀錄的舊 run 為 null），讓混用不同模式的 set 一眼可見。
4. **不在這裡規定正式收集必須用哪一種模式**：那是使用者的決定（NEXT「Blocked / 需要使用者」）。決定之後，再以新的 decision 加上 preflight 檢查。
   在那之前，一個 set 的所有正式 run group 應在同一種模式下收集；不一致時在報告中列出，由使用者決定如何處理。

## 為什麼

- 紀錄的成本幾乎為零，而缺少紀錄時，事後無法區分「方法的差異」與「收集條件的差異」。
- 原始 `pmset` 值不做解讀：不同機型的鍵與數值意義可能不同（例如 `powermode` 0 / 1 / 2 與 `lowpowermode`），保留原值才不會記錯。

## 放棄的替代方案

- **現在就在 preflight 拒絕自動模式**：使用者平常用哪一種模式還不知道；自行訂定門檻等於改收集協定。
- **run 期間持續取樣電力模式**：需要改 run group 的取樣流程；模式在一次 run 中途被改的機會很小，先只記錄開始時的狀態。

## 對實驗的影響

- 從下一個 run group 起，所有 run record 與 manifest 都帶 `machine.power`；2026-10-08 以前的 run（含 RG-001 與兩次冒煙測試）沒有這個欄位。
