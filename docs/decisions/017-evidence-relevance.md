# 017 — Evidence relevance：candidate pool、弱標籤與人工 gold subset

- 狀態：Accepted（2026-10-08）；在任何方法對任何 incident 產生 evidence 之前寫定（decision 013 §4 延後的那一層）。
  與 decision 013 一樣，held-out 收集之前可依 Pilot 經驗修訂一次（寫 decision log）；看到 held-out 結果後永遠不改。
- 影響範圍：SPEC Core §9（evidence relevance）；所有方法的報告表；ground truth 側新增 `evidence_gold.json`。

## 背景

- SPEC §9：relevance 不能直接把「故障服務 + 故障時間窗」當 gold evidence；要自動建立 candidate evidence pool、用弱標籤表示 temporal / service relevance、
  人工標註一部分 gold evidence，報告時把 gold subset relevance 與 weak-label score 分開列。
- decision 013 §4：existence 已實作；relevance 是另一層，兩者永不合成一個數字。
- 方法引用的 evidence 是 snapshot 的 record id（`s-` span、`l-` log、`m-` metric series 可加 `t0` / `t1`、`p-` metric point、`t-` trace）。

## 決策

### 1. candidate evidence pool

每個 incident 的 pool = 所有方法對它引用、而且 existence 成立的 evidence 的聯集（以 `(id, t0, t1)` 去重；IR 評測的 pooling）。
pool 隨方法增加而變大；已標註的項目不會因此改變。

### 2. 弱標籤（自動、ground-truth 側）

對每個引用（existence 成立、同一個方法內去重）：
- **時間**：record 的時間 = span 的開始時間、log 的 time（沒有時用 observed time）、point 的時間、`m-` 帶範圍時取 `[t0, t1]` 的中點、
  `t-` 取該 trace 最早的 span 開始時間；`m-` 沒有範圍時沒有時間。
  **temporal** = 時間落在 `[fault_start, fault_end + 60 s]`（label 的 host 時鐘加上該 run 量到的時鐘差，換到資料時鐘，與 decision 015 相同）。
  60 s 涵蓋 fault 結束時仍在進行中的請求（例如 lock contention 最多再鎖 30 s、shipping 延遲 10 s）。
- **service**：record 的服務（`t-` 是 trace 中所有 span 的服務）在 label 的 `affected_services` 裡；**origin**：包含 `origin_service`。
- **weak** = temporal 且 service。
- 每個方法、每個 incident 報 temporal / service / origin / weak 的比例（分母 = existence 成立的引用數；沒有時是 null）。

### 3. 人工 gold subset

- **抽樣**：每個 incident、每個方法，從它 existence 成立的引用中以固定種子（`<incident>:<method>`）抽最多 **5** 個；
  一個方法的樣本不因其他方法加入而改變。已標註的不重標。
- **盲標**：標註表（`python -m eval gold-todo --set pilot`，ground-truth 側 `evidence_gold_todo.json`）只列 record 的內容（render v1）、incident 的 label 與 fault 時間；
  **不列是哪個方法引用的，也不列弱標籤**。
- **判準**：relevant = 這筆 record 呈現了這個 fault 的故障行為本身，或它造成的錯誤、延遲、資源變化、重啟或訊息
  （和 normal period 相比是不一樣的）；not relevant = 正常行為、fault 之外也會出現的 ambient 失敗、與這個 fault 無關的服務。
- **標註者**必須是人（`human:<name>`）；判定一旦寫入 `ground_truth/incidents/<INC>/evidence_gold.json` 就不能改（要改需另寫 decision）。
  格式：`schemas/evidence_gold.schema.json`。
- **分數**：每個方法、每個 incident：gold precision = 被判 relevant 的引用數 / 已有 gold 判定的引用數（任何方法抽到的都算），
  並報 coverage = 已有 gold 判定的引用數 / existence 成立的引用數。沒有 gold 判定時 precision 是 null。

### 4. 報告

existence、弱標籤（temporal / service / origin / weak）、gold precision（含 coverage）分開列，各自報平均值與 run-group cluster bootstrap 95% 區間
（只計算該值不是 null 的 incident，並列出 n）；永不合成一個數字，也不與 decision 013 的主要指標合併。

## 為什麼

- pooling 讓人工只標各方法真的引用過的東西，標註量隨方法數線性成長，而且 precision 可以直接比較。
- 弱標籤只用 SPEC 指定的 temporal / service 兩個面向，事先固定、可自動計算；它的已知盲點（例如 fault 期間 origin 的正常 span 也會算 weak）
  正是需要 gold subset 的原因，所以兩者分開列。
- 每個方法固定抽 5 個：每個方法都有 gold 覆蓋，不會被引用量大的方法主導；Pilot（10 個 incident）只用統計 baseline 時約 50 筆，人工可負擔。
- 盲標避免標註者因方法名稱或弱標籤而偏向。

## 放棄的替代方案

- **把「故障服務 + 故障時間窗」當 gold**：SPEC §9 明確禁止。
- **與方法無關的自動 pool（例如 fault 專屬錯誤訊息的 record）**：需要另一套 relevance 定義，且無法直接評各方法引用的 precision；可在之後做 evidence recall 時再加。
- **加入「和 normal 相比是否異常」的自動標籤**：規則需要每種 record 的異常定義（span 延遲、log 樣板頻率、metric 範圍），本身就是另一個 baseline；交給 gold subset 判斷。
- **全部人工標註**：方法多、引用多時不可負擔，也不可重現。

## 對實驗的影響

- `python -m eval score` 的表多列弱標籤與 gold precision；Pilot 的 gold 由使用者在 Gate 時標註（約 50 筆起）。
- Agent 與 LLM baseline 加入後，各自的樣本要先標完，gold precision 才會出現在報告中（coverage 會顯示缺口）。
