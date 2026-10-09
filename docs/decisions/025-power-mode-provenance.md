# 025 — 收集時的電力模式記錄在 provenance

- 狀態：Accepted（2026-10-08）；在任何正式 Pilot incident 收集之前寫定。只增加紀錄，不改收集協定、有效性判定或任何指標。
  **修訂 1（2026-10-09，使用者決定）**：正式收集固定為自動電力模式 + AC 供電，preflight 檢查（見文末）。
  **修訂 2（2026-10-09）**：run 期間每分鐘取樣電力狀態，incident 時間窗內任何一筆不符就判無效（見文末）。
  **修訂 3（2026-10-09，使用者決定）**：正式條件改為**高效能模式（`powermode` 2）+ AC 供電**；RG-002 撤回並重收（見文末）。
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

## 修訂 1（2026-10-09，使用者決定；在任何正式 Pilot incident 收集之前）

- **決定**：所有正式收集（Pilot 與 held-out）固定在 **自動電力模式（`pmset` 的 `powermode` = 0）+ AC 供電**；不要求高效能模式。
- **落地**：`collect.live.power_problems` 加進 `LiveStack.preflight`：
  - 電源不是 `AC Power` → 拒絕；
  - `powermode` 不是 `"0"`，或有 `lowpowermode` 且不是 `"0"` → 拒絕；
  - 讀不到 `pmset`、或 `powermode` 沒有列出 → 拒絕（不假設）。
  - 非正式的冒煙測試用同一個 preflight，也在相同條件下執行。
- 仍只記錄 run 開始時的狀態（決策 2）；run 中途被改的情況不在有效性判定內。
- 原本「§4：不在這裡規定」由本修訂取代。

## 修訂 2（2026-10-09，第一個正式 Pilot run 之後、在任何方法結果之前）

- **發現**：RG-002（paymentFailure 100%，01:29:39Z 開始時 `powermode` = 0）完成後，下一個 run 的 preflight（02:10:47Z）讀到 AC 的 `powermode` = 2（高效能），拒絕開始。
  系統 log 沒有切換時間；只知道切換發生在 01:29:39Z–02:10:47Z 之間。修訂 1 只檢查開始時的狀態，無法知道 RG-002 的時間窗內是否都在自動模式。
- **決定**（落實使用者「正式收集固定使用自動電力模式 + AC」的決策；只會讓更多 run 無效，不放寬任何條件）：
  1. run 期間與 Locust / memcg 取樣一起，約每分鐘取一筆 `power` 樣本（`pmset`，唯讀；讀不到記為 null）。
  2. 有效性判定（decision 009 §4 的延伸）：incident 時間窗（normal 開始到 end，host 時鐘）內任何一筆 `power` 樣本不符修訂 1 的條件，
     或時間窗內沒有任何 `power` 樣本 → 原因 `power_not_formal`，run 無效，依 009 §4 以新的 run group、新的 seed 重收。
     不符的樣本（最多 20 筆）記在 run record 的 `power_not_formal`；`power_samples` 記錄樣本數。
  3. 時間窗之前（暖機、穩定閘門）不判定：開始時的狀態由 preflight 檢查。
- **RG-002**：在本修訂之前收集，沒有 run 期間的電力樣本。依修訂 1 的書面規則它仍是有效 run（只看開始時的狀態），**是否重收由使用者決定**
  （使用者知道何時切換；若在 01:29:39Z–02:08Z 之間，INC-001 有一部分在高效能模式下收集）。

## 修訂 3（2026-10-09，使用者決定；Pilot 只有一個有效 run 之後、在任何方法結果之前）

- **決定**（使用者：「改高效能先跑」；「要不要重收，如果你認為需要就直接重收」）：所有正式收集（Pilot 與 held-out）改為
  **高效能模式（`pmset` 的 `powermode` = 2）+ AC 供電**。取代修訂 1 的「自動模式」；修訂 1 的其他規則（讀不到不假設、`lowpowermode` 必須是 0）與修訂 2 的時間窗取樣判定不變。
- **為什麼要求一致而不是要求某種模式**：電力模式改變 CPU 時脈，會改變 latency、CPU 等的絕對值；各方法都以同一個 snapshot 的前 10 分鐘為參考，看的是 fault 造成的變化，
  所以哪一種模式都可以，但同一個 set 必須全部相同，時間窗內也不能切換。
- **RG-002 / INC-001**：開始時是自動模式（`powermode` 0），與新的正式條件不一致 → **撤回**（`collect.pilot.withdraw`，在 ground-truth 側寫
  `run_groups/RG-002/withdrawn.json`：原因、決定者、時間）。所有檔案保留；撤回的 incident 不算 Pilot 的可用 incident、不算無效次數、
  不進任何方法執行與評分（評分表列在 excluded，原因 `withdrawn: …`）。paymentFailure 100% 以新的 run group、新的 seed 重收。
- 校準統計 baseline 門檻的 soak（#3、#5）沒有記錄電力模式；門檻是相對的 z 分數，視為已知限制，不因此修改門檻（decision 014）。
