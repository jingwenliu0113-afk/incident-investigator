# 018 — Label review（catalog → catalog+review）的程序與評分使用哪一份 label

- 狀態：Accepted（2026-10-08）；在任何 incident 被 review 之前寫定。
- 影響範圍：decision 006 §7、010 §2 的 review 程序；評分、leakage audit、evidence relevance 讀哪一份 label；decision 016 §5「fault 沒有被觸發」的落地方式。

## 背景

- decision 006 / 010：a priori（`catalog`）label 只依 fault 設計推得；之後由人對照 frozen snapshot 檢查，成為 `catalog+review` 並填 `telemetry_coverage`，
  與 a priori 的差異要記錄理由。`collect.labeling` 規定 label 永不覆寫、review 另外寫。
- decision 016 §5：review 要檢查清單上 a priori 不確定的項目，並確認 fault 有被觸發；沒有觸發的 incident 不進評分。
- 還沒寫定的：review 能改哪些欄位、review 時能看到什麼、review 的結果放在哪裡、評分用哪一份。

## 決策

1. **檔案**（都在 ground truth 側 `ground_truth/incidents/<INC>/`）：
   - `label.json`：a priori label，**永不改**。
   - `label_review_todo.json`：review 工作表（`python -m collect review-sheet --incident <INC>`）。
   - `label.reviewed.json`：`catalog+review` label（通過 `check_label`），只寫一次。
   - `label_review.json`：review 紀錄：reviewer、時間、`fault_exercised`、與 a priori 的每個差異（欄位、前、後、理由）、reviewer 是否看過任何方法對這個 incident 的輸出。
2. **review 能改的欄位**：`affected_services`、`user_symptom`（kinds 與描述）、`labeling.notes`，並**必須**填 `telemetry_coverage`。
   不能改：`origin_service`（由 fault 設計與 decision 016 §1 的規則決定，不依 telemetry 的樣子改）、`injected_fault`、時間、seed、traffic profile。
3. **判準**：affected 用 decision 010 規則 3 與 016 §2（服務自己的 telemetry 在 fault 期間出現因 fault 造成的錯誤或延遲；OOM / 重啟算錯誤）；
   user_symptom 用 016 §3（在 edge 看）；`telemetry_coverage` 用 decision 006 §7。每個與 a priori 不同的欄位都要寫理由，沒有理由就拒絕寫入。
4. **review 只能由人做**（`human:<name>`），而且應在看到任何方法對該 incident 的輸出之前完成；
   reviewer 在紀錄上回答是否已看過（`saw_method_outputs`），看過的會在報告表上註明。工作表不放任何方法的輸出。
5. **工作表內容**：a priori label、decision 016 §5 對該 fault 要檢查的項目、snapshot 每個服務在 normal / fault / recovery 的摘要
   （每分鐘 span 數、error 比例、server span p95 的中位數與最大值、每分鐘 WARN 以上 log 數、CPU 平均、記憶體最大值），以及 run record 中各時段的 container die / oom 事件。
   摘要只是方便查看；判斷以 snapshot 本身為準。
6. **`fault_exercised = false`**：該 incident 不進任何評分（報告表列出排除原因），依 decision 016 §5 以新的 run group 重收一次。
7. **評分、leakage audit、evidence relevance 用的 label**：有 `label.reviewed.json` 就用它，否則用 `label.json`；報告表列出各用了幾份。
   Pilot 可以在 review 之前先跑（驗證 pipeline）；held-out 的協定要規定所有 label 在任何方法執行前 review 完成（在 held-out 協定的 decision 寫定）。

## 為什麼

- a priori 與 review 分檔：a priori 是事先登錄的預測，保留下來才能報告「設計推得的答案」與「實際看到的答案」差多少（label 驗證是 Pilot 的用途之一，SPEC §5）。
- origin 不隨 review 改：origin 是設計事實；若依 telemetry 改 origin，等於用「看得到什麼」定義答案，會讓 telemetry 不足的 incident 變簡單。
- 摘要事先固定欄位：reviewer 每個 incident 看同樣的東西，判斷可重現；不放方法輸出避免答案被方法帶著走。

## 放棄的替代方案

- **review 直接覆寫 `label.json`**：失去 a priori，也違反「label 永不覆寫」。
- **由 Agent（Claude）做 review**：decision 006 / 010 規定由人檢查；Agent 只產生工作表。
- **review 可以改 origin**：見「為什麼」。

## 對實驗的影響

- Gate 前請使用者 review Pilot 的 label（每個 incident 一份工作表）；review 前的 Pilot 分數用 a priori label，表上會標明。
- 報告除了分數，也列出 a priori 與 review 的差異（label 驗證的結果）。
