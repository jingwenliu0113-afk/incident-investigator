# 022 — 失敗分類 v1（telemetry 不足 vs 沒找到 vs 看到了但判斷錯）

- 狀態：Accepted（2026-10-09）；在任何方法產生任何結果之前寫定。可在 Pilot 上修訂一次（寫 decision log）；held-out 之前凍結。
- 影響範圍：SPEC Core §10「失敗分類必須是正式產出」；Gate 的「錯誤主要來自推理路徑，不是 telemetry 不足」與「失敗主要來自 telemetry coverage 不足」的判斷。

## 決策

### 1. 什麼算失敗

一個方法在一個 incident 上，origin（`origin_top1`）或 injected fault（`fault_type`）答錯，就是一次失敗（decision 013 的兩個主要指標，用 decision 018 的有效 label）。
affected 與 symptom 的錯誤照常在分層分數中報告，不另外分類。

### 2. 每次失敗只歸入一類（依下面的順序，第一個符合的）

| 類別 | 條件 | 意義 |
|---|---|---|
| `no_answer` | 放棄作答（origin_candidates 為空），或停止原因不是提交（預算、回合、提交不合格） | 沒有答案 |
| `coverage` | review 過的 label 的 `telemetry_coverage` 三種 signal 都不是 `origin`（origin 在 snapshot 裡看不到故障） | telemetry 不足 |
| `mechanism` | origin 答對、fault_type 答錯 | 找到地方，機制判斷錯 |
| `not_seen` | 方法看過的資料（exposure）裡沒有 origin 在 fault 期間的證據 | 沒找到（探索 / 檢索失敗） |
| `seen_misread` | exposure 裡有 origin 在 fault 期間的證據，origin 仍答錯 | 看到了但判斷錯（推理失敗） |
| `rule_limit` | 沒有 exposure 紀錄的方法（統計 baseline）其餘的失敗 | 規則本身的限制 |

- **origin 在 fault 期間的證據**（exposure 中任一項）：
  - origin 服務的 span / log，時間在 `[fault_start, fault_end + 60 s]`（資料時鐘，與 decision 017 的 temporal 相同）；
  - origin 服務的 metric series（`m-`），或該 series 在同一時段內的 point（`p-`）；
  - origin 服務的每分鐘統計，涵蓋至少一個 fault 期間的分鐘（Agent 的 `service_minute_stats` 呼叫；dump-all 與 retrieval 的概覽區塊涵蓋所有服務與整個時間窗）。
- **exposure** 來自方法的 transcript（decision 019 §6、020 §5、021）：工具輸出中出現的 record id、`stats:<service>:<第一分鐘>-<最後一分鐘>`；
  dump-all 是打包進去的 record 加上 `stats:*`，retrieval 是檢索到的 record 加上 `stats:*`。
- 沒有 review 過的 label（只有 a priori）時，`coverage` 無法判斷，直接往下一類；報告列出有多少失敗是在沒有 review 的情況下分類的。

### 3. 報告

每個方法：各類別的次數與比例（佔失敗數），依 Easy / Medium / Hard 分層；並列出每次失敗的 incident 與類別（ground truth 側不需要隱藏，方法輸出已經產生）。
Gate 的判斷用 `coverage` 與 `not_seen + seen_misread` 的比例；`seen_misread` 是「推理路徑」失敗的主要證據。

## 為什麼

- 依序歸一類：每次失敗只算一次，比例加總為 1，容易比較。`coverage` 排在前面，因為 snapshot 看不到的東西，任何方法都不該被算成推理錯。
- 以 exposure 判斷「看過沒有」：不需要人工、可重現；把「沒找到」與「看到了但判斷錯」分開，正是 Gate 要回答的問題。
- 證據的定義與 decision 017 的弱標籤一致（時間 + origin 服務），並加上 metric 與每分鐘統計，讓資源類 fault（CPU、記憶體）也算得到。

## 放棄的替代方案

- **人工逐一分類**：Pilot 之後的規模不可重現；人工的失敗模式分析（anchoring、premature stopping 等）屬於 Advanced 的 trajectory 分析。
- **用 gold evidence 判斷「看過正確證據」**：gold 只覆蓋抽樣的引用，無法涵蓋 exposure；保留為之後的檢查。
- **把 affected / symptom 的錯也分類**：主要問題是「有沒有找到原因」；其他層的錯誤已有分層分數。

## 已知限制

- 「看過 origin 在 fault 期間的任何 record」比「看過能證明故障的 record」寬鬆：`seen_misread` 可能包含「看到的只是 origin 正常的 span」。
  Pilot 上會抽查，必要時用那一次修訂收緊（例如只算 error 等級的 record 或 gold relevant 的 record）。

## 補註（2026-10-11，使用者決定）：Pilot 上的 (b)、(c) 保留為失敗分析的發現，不修改

- 使用者原話（節錄；全文見 decision 021「Pilot 上的修訂（2026-10-11，使用者決定）」）：「選方案 (a)。」……「方案 (b)、(c) 暫時不修改，保留在 failure analysis。」
- **(b)** 三個 LLM 方法都只給一個 origin 候選（top3 = top1；stat-anomaly 的 origin_top3 是 0.90）。
- **(c)** Agent 到回合上限：RTX 5070 Ti 的執行 INC-009、INC-010 以 `submitted_after_limit` 結束（在 accounting 的長 span 上打轉）；被取代的 Mac 執行
  INC-006 重複呼叫查無資料的工具。
- 兩者都**不改**：020 的任務說明與 harness、019 的工具、所有預算照舊（021 只為 (a) 加了一行說明）；它們是 Pilot 失敗分析的發現，報告中照實列出。
  (a)（概覽列被當成證據引用）由 decision 021 在 Pilot 上的那一次修訂處理。
- 本補註只是紀錄：本文件的分類規則不變，**022 在 Pilot 上的那一次修訂沒有使用**。
