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

## 補註（2026-10-16）：render 版本、使用者決定 1、2 與 gold precision 的算法（規則都不變）

本補註只記錄事實與使用者的決定，**不是 017 在 Pilot 上的那一次修訂**：pool、弱標籤、抽樣（每個方法、每個 incident 最多 5 筆，種子 `<incident>:<method>`）、
判準、標註者、分數與報告都不變。

- **render 版本**：§3 寫「render v1」，那是寫定本文時的 renderer。`collect/snapshot.py` 的 `RENDER_VERSION` 從 commit `5ab5363`（2026-10-09，
  decision 011「修訂：renderer v2」）起是 2：頂層欄位固定順序，時間、身分與訊息不會被 1024 bytes 的截斷切掉；其餘規則（相對時間、省略 null、≤ 1024 bytes）不變。
  這發生在任何 gold 判定之前（第一批 28 筆在 2026-10-10，human:jingwen），所以 `gold-todo` 的工作表與所有判定看到的都是 v2 的 render。
- **使用者決定（2026-10-16）**，原話（第 1、2 項）：
  > 1. Gold 背景資訊選 a，依 decision 017 顯示，但必須保持方法盲標。
  > 2. 重複證據維持原規則，不修改 91 筆工作表的標註單位；可以提醒我哪些是重複內容。
  1. **背景資訊**：照 §3：工作表的 `context`（label 的 fault_type、origin_service、affected_services 與 fault 的相對時間）與每一項 record 的內容；
     **不顯示是哪個方法引用的，也不顯示弱標籤**（方法盲標）。
  2. **重複**：標註單位照 §1、§3 是 `(id, t0, t1)`：鍵不同就是不同的項目，各自判定、各自計入引用它的方法的分數；91 筆的工作表不合併、不刪項目。
     主 session 顯示時提醒哪些項目的內容重複（例如同一筆 record 的不同時間範圍，或文字相同的不同紀錄）；只是提醒，不改變標註單位，也不替使用者判定。
- **gold precision 的算法**（`eval/relevance.py` 的 `gold_score`、`eval/runner.py` 的 `EVIDENCE_LAYERS`；§3、§4 的字面意思）：
  - 每個方法、每個 incident：relevant 的引用數 / 已有 gold 判定的引用數。引用以 `(id, t0, t1)` 去重；判定不分是誰的樣本抽到的（任何方法抽到、任何時候判定的都算）。
  - 跨 incident：只算該方法至少有一筆已判定引用的 incident，**每個 incident 等權**平均，報 n 與 run-group cluster bootstrap 95% 區間（§4）。
    例：stat-anomaly 的 0.906 = 8 個 incident 各自 precision 的平均（7 個 1.0、1 個 0.25）；把 28 筆合在一起算的 25 / 28 = 0.893 不是報告的數字。
  - 工作表上「略」的項目（`relevant: null`）不寫入 `evidence_gold.json`、不進分母，只讓 coverage（已判定 / existence 成立的引用）變低；之後的 `gold-todo` 會再列出。
  - 各方法的 n 不同（引用的 incident 不同），所以各方法的 gold precision 不是 paired 的，不能當成配對比較。

## 補註（2026-10-16，第二則）：Pilot 上 LLM 方法引用的 gold 標註與重新評分（規則都不變）

本補註只記錄這一輪標註的事實，**不是 017 在 Pilot 上的那一次修訂**：pool、弱標籤、抽樣、判準、標註者、分數與報告都不變。

- **標註者與時間**：使用者本人（`human:jingwen`），一次一個 incident。寫入時間（`annotated_at`，UTC）INC-002 到 004 是 2026-10-15T16:25Z – 16:41Z、
  INC-005 到 011 是 2026-10-16T00:41Z – 00:56Z（本地時間 2026-10-16 00:25–00:41 與 08:41–08:56）。
- **工作表**：2026-10-15 `eval gold-todo --set pilot` 產生的 91 筆（三個 LLM 方法——dump-all 與 retrieval 是 021 修訂後的執行——的引用依 §3 抽出；
  stat-anomaly 的樣本 2026-10-10 已全部判定）：INC-002 10、003 12、004 9、005 9、006 11、007 7、008 10、009 7、010 9、011 7。
- **呈現**（上一則補註的使用者決定 1、2）：主 session 唯讀顯示每一項的 record 內容（render v2）與 §3 的背景（fault_type、origin_service、affected_services、
  fault 的相對時間）；**不顯示是哪個方法引用的，也不顯示弱標籤**（方法盲標）。重複的項目照 §1、§3 以 `(id, t0, t1)` 為單位、標明與哪一項重複、分開作答：
  INC-003 第 2/3 項與第 10/11 項、INC-004 第 2/3 項（都是同一筆紀錄的不同時間範圍）。INC-004 第 5 項是 2026-10-10 以另一個鍵判定過的紀錄，作答時沒有顯示先前的判斷。
- **寫入**：每個 incident 答完，主 session 把問答紀錄列給使用者確認，確認後才 `eval gold-add --annotator human:jingwen`；主 session 沒有替使用者判定任何一項。
  寫入的項目在 `note` 記錄使用者的理由或作答情境（INC-005 到 011 每一項都有；INC-002 到 004 只在需要說明的項目：INC-002 第 8、10 項、上述重複項目、INC-004 第 5 項）。
- **INC-002 第 10 項**：使用者作答前看過助理對這一項的補充說明（2026-10-15 的呈現）；寫入時記在該項的 `note`，判定（not relevant）仍是使用者的。
- **結果**：91 筆中寫入 87 筆、略 4 筆；gold 現有 115 筆判定（2026-10-10 的 28 筆 + 87 筆），75 筆 relevant，全部 `human:jingwen`。

  | incident | fault（origin） | 工作表 | 寫入 | 其中 relevant | 略 | 使用者的理由（摘要） |
  |---|---|---:|---:|---:|---:|---|
  | INC-002 | error_response（payment） | 10 | 10 | 9 | 0 | 第 1–9 項 relevant（第 8 項：下游錯誤症狀，依 §3「它造成的錯誤」）；第 10 項 not relevant（見上） |
  | INC-003 | error_response（product-catalog） | 12 | 11 | 11 | 1 | 第 2/3、10/11 項分開標註 |
  | INC-004 | unreachable_dependency（checkout） | 9 | 7 | 7 | 2 | 第 2/3 項分開標註 |
  | INC-005 | unreachable_dependency（cart） | 9 | 9 | 9 | 0 | cart 的 Redis 連線錯誤是直接故障證據；checkout 的錯誤是下游症狀 |
  | INC-006 | added_latency（shipping） | 11 | 11 | 3 | 0 | 3 筆 shipping span 約 10 秒延遲；其餘 8 筆未呈現可確認的故障行為（不因服務相關或位於故障時間窗就判 relevant） |
  | INC-007 | lock_contention（product-catalog） | 7 | 7 | 4 | 0 | 4 筆故障期間的下游錯誤與約 15 秒延遲（下游症狀，不直接證明 lock contention）；3 筆在故障前、無異常 |
  | INC-008 | cpu_saturation（ad） | 10 | 10 | 0 | 0 | 全部在 fault 開始前，沒有 CPU 飽和或異常（不因服務名稱與 origin 相符就判 relevant） |
  | INC-009 | gc_pressure（ad） | 7 | 6 | 0 | 1 | 1 筆沒有異常；5 筆在故障前、與故障服務無直接關聯 |
  | INC-010 | memory_leak（email） | 9 | 9 | 0 | 0 | 1 筆是寄送數量的累積計數器、沒有記憶體異常；8 筆是正常 span |
  | INC-011 | memory_leak（recommendation） | 7 | 7 | 7 | 0 | 4 筆依下游症狀標準（與推薦 API 錯誤的時間關聯，不是直接根因證據）；2 筆推薦 API 錯誤；1 筆 recommendation 的 DNS 解析失敗。整體支持推薦服務異常，但不足以直接證明 memory leak |
  | 合計 | | 91 | 87 | 50 | 4 | |

- **略的 4 筆與使用者的理由**（`relevant: null`，不寫入 `evidence_gold.json`，所以理由只記在這裡；之後的 `gold-todo` 會再列出）：
  - INC-003 第 9 項：單憑可見證據無法確認 `/api/recommendations` 的錯誤與 Product Catalog 故障的關聯。
  - INC-004 第 1、8 項：發生在故障結束後約 0.7 秒，可能是殘留影響，但無法確認。
  - INC-009 第 2 項：故障期間呼叫 AdService 約 1.31 秒，但缺少正常時段的基準，無法確認與 GC 壓力的關係。

  這 4 筆都只出現在 dump-all 的引用裡，而且都在 dump-all 的 §3 樣本中（dump-all 在 INC-003、004、009 各引用 5、4、2 筆，不超過 5 筆）；
  stat-anomaly、retrieval、Agent 的樣本全部判定。
- **relevant 的範圍**：§3 的判準包含 fault 造成的下游錯誤與延遲，所以 relevant 只表示「這筆紀錄呈現了這個 fault 的故障行為或它造成的變化」，
  不表示它證明了根因機制（使用者在 INC-007、INC-011 的註記）。
- **重新評分**（2026-10-16，評分程式沒有改）：`eval version-check --set pilot` 通過；`eval score` dump-all、retrieval、agent；`eval compare` 與 `eval gate`
  （Pilot 診斷）重跑。主要指標不變，Gate 的三個條件的結果不變。gold（n = 有已判定引用的 incident 數，等權平均，run-group cluster bootstrap 95%；§4）：

  | 方法 | n | gold precision | gold coverage |
  |---|---:|---:|---:|
  | stat-anomaly | 8 | 0.906 [0.719, 1.000] | 1.000 |
  | dump-all（021 修訂後） | 10 | 不報（樣本沒有全部判定；見下面「使用者的回答」） | 0.840 [0.710, 0.960] |
  | retrieval（021 修訂後） | 7 | 0.571 [0.143, 0.857] | 0.667 [0.345, 0.892] |
  | agent | 9 | 0.756 [0.444, 1.000] | 1.000 |

  coverage 低於 1 有兩個來源：§3 每個方法、每個 incident 最多只抽 5 筆（retrieval 在 INC-002、005、006 各引用 45、22、25 筆），以及上述 4 筆略（dump-all）。
  各方法的 n 不同，不是 paired 的比較（上一則補註）。修訂前（封存）的 dump-all / retrieval 不補標、不重新評分。
- **與「對實驗的影響」字面的差異（只記錄，不改規則）**：「對實驗的影響」寫「各自的樣本要先標完，gold precision 才會出現在報告中」；decision 030 §4 第 8 項照這句寫
  held-out 的 100「一個方法的樣本全部判定之前不報它的 gold precision」。Pilot 上 91 筆都已呈現並作答（「略」也是使用者的回答），但 dump-all 的樣本有 4 筆沒有判定。
  使用者 2026-10-16 要求重新計算 gold precision 與 coverage（已完成，上表）；寫這則補註時 Pilot README 的草稿報出 dump-all 的 gold precision（標明 4 筆略與 coverage），
  要不要這樣報列為待使用者確認（NEXT A12，freeze 的前置條件）。
- **使用者的回答（2026-10-16，freeze 之前；NEXT A12 選 (b)）**，原話：
  > A12 選 b：不報 dump-all 的 Gold Precision，只報 Coverage 0.840，保留四筆「略」及原因，遵守 Decision 017。

  照本文「對實驗的影響」的字面：dump-all 的樣本沒有全部判定，所以 **Pilot 的報告不報 dump-all 的 gold precision**，只報它的 gold coverage 0.840（n = 10），
  並寫明原因（上述 4 筆略都在 dump-all 的 §3 樣本裡）與 4 筆略的使用者理由（上面「略的 4 筆與使用者的理由」，README 的「Evidence」同樣列出）。
  - 套用範圍：README「Evidence」（表中 dump-all 的 gold precision 欄寫「不報」，「各 incident」不列 dump-all 的 per-incident gold precision）、本補註上面的表
    （原本列出數字，依這個回答改成「不報」）、NEXT「目前位置」的表。stat-anomaly、retrieval、Agent 的樣本全部判定，照常報（數字不變）。
  - **不改的**：評分程式、`scores.json` 與 `table.md`（`eval score` 照 §3、§4 對每個有已判定引用的 incident 算出 gold precision，dump-all 的欄位仍在檔案裡；
    報告依本文不引用它）、4 筆略的處理（不寫入、不進分母，之後的 `gold-todo` 會再列出；使用者沒有選 (c) 再判定）、pool、弱標籤、抽樣、判準、標註者與 held-out 的規則
    （030 §4 第 8 項不變）。這是照 017 現行規則的報告方式，**不是 017 在 Pilot 上的那一次修訂**（freeze 宣告 `"017": waived`，見 decision 023「追加（2026-10-16）」；
    013 正式版 F13 第 1 項的 (ii)——改 §1 的鍵——會是 017 的那一次修訂、宣告改成 used；使用者 2026-10-16 選 (i)，原話「第 1、3、7 項都選 (i)，繼續 freeze」：
    §1 的鍵 `(id, t0, t1)` 不分 id 的種類、維持不變——非 `m-` 引用帶的範圍不影響 existence 與弱標籤的時間，但是鍵的一部分，在弱標籤與 gold 是另一個鍵——
    所以沒有修訂，宣告維持 waived）。
