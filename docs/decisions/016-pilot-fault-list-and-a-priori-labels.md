# 016 — Pilot fault 清單與 a priori label

- 狀態：Accepted（2026-10-08）；在收集任何 Pilot fault 之前寫定（此時沒有任何有效的 Pilot incident：RG-001 aborted_unstable，RG-002 尚未開始）。
- 影響範圍：Pilot Set 的組成（SPEC §5）；label 的 origin、affected services、user symptom 判定規則（補充 decision 006、010，適用所有 incident）；
  `collect run` / `collect label` 的檢查。

## 背景

- SPEC §5：第一批約 10 個 incident 是 Pilot Set，用來驗證 pipeline、label、leakage audit 與 baseline 難度，永遠不進 final test。
- decision 006「尚未決定」：每個 flag 的 a priori origin / affected / symptom，以及 `paymentUnreachable`、`kafkaQueueProblems`、
  `loadGeneratorFloodHomepage` 的 origin，要在 Pilot 清單時決定並寫 decision log。
- decision 010 只決定了第一個 incident（`paymentFailure` 100%）與 affected 規則 3。
- 背景研究：研究筆記 §8（讀 upstream 原始碼，並用 soak #5 量實際呼叫率與記憶體基準）。

## 決策

### 1. origin 的判定規則

`origin_service` = **flag 改變其程式碼或設定行為的那個服務**（flag 在那裡被讀取、故障行為在那裡執行），即使故障表現為「連不到別的服務」。
- `paymentUnreachable`：checkout 用錯誤的 payment 位址 → origin = **checkout**；payment 本身健康，只是收不到呼叫。
- `cartFailure`：cart 自己的第二個 store 指向壞的 host → origin = **cart**；valkey-cart 健康。
- `productCatalogLockContention`：鎖由 product-catalog 自己的程式與連線池持有 → origin = **product-catalog**；astronomy-db（Postgres）只是鎖所在的地方，行為正確。
- 依這條規則有**兩個**注入點的 fault（`kafkaQueueProblems`：checkout 多送 100 倍訊息、fraud-detection 每筆慢 1 s，缺一都不會積壓）沒有單一 origin，**不用於 Pilot**。
- origin 不在 snapshot 的 fault（`loadGeneratorFloodHomepage`：origin 是 load-generator，decision 011 排除）無法標註，**不用於 Pilot**。

### 2. affected 規則 3 的補充（decision 010）

- 對 origin 以外的服務，只有**它自己的** span / log / metric 出現因 fault 造成的**錯誤或延遲**才算 affected；
  連線數、consumer lag、資源用量、流量等其他變化不算（例如 lock contention 時 astronomy-db 的 backends 與 rollbacks）。
- 服務因 fault 被 OOM-kill 或重啟，算該服務的錯誤。
- origin 永遠在 affected 裡（decision 006 §5）。

### 3. user_symptom 的判定方式（decision 006 §6）

在 edge（frontend-proxy）看 traffic generator（Locust HTTP user 與 browser user）送出的請求：
失敗（5xx、timeout）→ `errors`；變慢 → `latency`；兩者都沒有 → `none`。
`degraded_feature` 保留給「回應成功但內容缺漏」，Pilot 的 a priori label 不使用（browser 上推薦或廣告區塊消失，同時也是 edge 的失敗請求，記為 `errors`）。

### 4. Pilot 清單（10 個 fault，各收 1 個有效 incident）

| # | flag | variant | fault_type | origin | affected_services | user_symptom |
|---|---|---|---|---|---|---|
| 1 | paymentFailure | 100% | error_response | payment | payment, checkout, frontend, frontend-proxy | errors |
| 2 | productCatalogFailure | on | error_response | product-catalog | product-catalog, checkout, frontend, frontend-proxy | errors |
| 3 | paymentUnreachable | on | unreachable_dependency | checkout | checkout, frontend, frontend-proxy | errors |
| 4 | cartFailure | 100% | unreachable_dependency | cart | cart, checkout | none |
| 5 | intlShippingSlowdown | 10sec | added_latency | shipping | shipping, checkout, frontend, frontend-proxy | latency |
| 6 | productCatalogLockContention | on | lock_contention | product-catalog | product-catalog, recommendation, checkout, frontend, frontend-proxy | latency, errors |
| 7 | adHighCpu | on | cpu_saturation | ad | ad | none |
| 8 | adManualGc | on | gc_pressure | ad | ad, frontend, frontend-proxy | latency |
| 9 | emailMemoryLeak | 1000x | memory_leak | email | email, checkout | none |
| 10 | recommendationCacheFailure | on | memory_leak | recommendation | recommendation, frontend, frontend-proxy | latency, errors |

- 完整的 a priori label（含描述與 notes）在 `collect/pilot.py`（`PLANS["pilot"]`）；第 1 列就是 decision 010。
- **variant 的選擇**：每個 flag 選在 10 分鐘內效果看得到、又不變成另一種 fault 的那個：
  - cartFailure 100%（10% / 25% 在 10 分鐘內只有約 3 / 7 次 EmptyCart）；
  - intlShippingSlowdown 10sec（仍低於 Envoy 15 s timeout，不變成錯誤）；
  - emailMemoryLeak 1000x（100x 以下被記憶體基準波動淹沒，10000x 每封都 OOM，變成 crash loop）。
- **不用於 Pilot**：
  - kafkaQueueProblems、loadGeneratorFloodHomepage（§1）；
  - adFailure（只有 1/10 的 GetAds 失敗，Locust 只看到約 0.4 次 / 分；error_response 已有兩個不同 origin）。
- **涵蓋**：9 種 fault_type 中的 7 種（沒有 queue_backlog、traffic_flood）；error_response 與 unreachable_dependency 各有兩個 origin；
  origin 涵蓋 payment、product-catalog、checkout、cart、shipping、ad、email、recommendation。

### 5. 執行與檢查

- `collect run --set pilot` 只接受清單上的 flag / variant；`collect label` 的 origin / affected / symptom 只從清單取，不再由命令列輸入（避免看了資料才填）。
- 依表的順序收集；每個 run group 都從乾淨的 stack 開始（preflight 拒絕已存在的 container），所以順序不影響結果。無效的 run group 依 decision 009 §4 以新的 run group、新的 seed 重收。
- **review**（`catalog+review`，decision 006 §7、010 §2）由人對照 frozen snapshot 做，記錄與 a priori 的每個差異與理由。下面這些 a priori 不確定的地方要特別檢查：

| fault | 要檢查的 |
|---|---|
| cartFailure | 失敗的 EmptyCart 花多久；若造成 checkout / edge 的延遲或 timeout，依規則 2、3 改 affected 與 symptom |
| productCatalogLockContention | astronomy-db 是否 OOM / 重啟（規則 2：算錯誤）；astronomy-db metric 是否有缺口 |
| adHighCpu | ad 或 edge 是否真的沒有延遲 |
| adManualGc | 延遲幅度、ad 是否 OOM；stack trace 類別名稱與 GC cause 是否說出 fault（洩漏面） |
| emailMemoryLeak | OOM 的次數與時間；checkout 是否真的出現送信錯誤 |
| recommendationCacheFailure | OOM 重啟次數 |

- **fault 沒有被觸發**：review 若發現 fault 期間沒有任何請求走到故障路徑（例如 intlShippingSlowdown 期間沒有非美國地址的訂單，機率約 5%），
  該 incident 不進任何評分，以新的 run group 重收一次；兩者都記錄在 review 與本文件的結果。這條規則在收集之前固定，不依結果判斷「看起來不夠明顯」。

## 為什麼

- origin 規則以「哪裡的程式碼或設定被改壞」為準，和 RCA 要找的東西一致；「連不到別人」的 fault 若把 origin 標成被連的那一方，
  等於把健康的服務當答案。同一條規則也讓 cartFailure、paymentUnreachable、lock contention 的判定一致。
- 規則 2 的補充延續 decision 010 的理由：只有錯誤與延遲是可重現、不隨呼叫鏈或負載變動膨脹的判準。
- user_symptom 在 edge 判定：Locust 與 browser 看到的都是 frontend-proxy 的回應，而 snapshot 裡沒有 load-generator 的資料；這也是 review 能拿來檢查的唯一來源。
- 把 a priori label 寫成程式資料並由 CLI 強制使用：label 在收集前就固定，事後只能經 review 修改並留下差異紀錄。

## 放棄的替代方案

- **paymentUnreachable 的 origin = payment**：payment 沒有任何異常，Agent 若「答對」反而是猜錯機制。
- **kafkaQueueProblems 的 origin 選 fraud-detection 或 checkout 其中一個**：兩者都是必要條件，任何一個答案都說得通，origin 這一層會變成擲硬幣。
- **把 lock contention 的 origin 標成 astronomy-db**：鎖是 product-catalog 的程式下的，Postgres 的行為正確。
- **用 adFailure 取代其中一個**：量太少，而且和 paymentFailure、productCatalogFailure 重複 fault_type。
- **比較小的 variant**（cartFailure 10%、emailMemoryLeak 100x）：10 分鐘內幾乎看不到，Pilot 只會量到「沒資料」。
- **隨機收集順序**：每個 run group 都從乾淨的 stack 開始，順序沒有影響；固定順序比較容易追蹤。

## 對實驗的影響

- Pilot 需要 10 個有效 run group，每個約 45 分鐘、都要 Mac heavy lock。
- Pilot 沒有 queue_backlog、traffic_flood 的 incident；held-out 的 fault 清單在它自己的協定決定，不能從 Pilot 結果反推答案。
- leakage audit（decision 015）在 productCatalogFailure 預期會看到 "Error: Product Catalog Fail Enabled" 的殘留（decision 011 已接受）；
  adManualGc 若出現說出 fault 的字串，記錄為 policy 的缺口，在 held-out 之前以 policy v2 處理（policy v1 已凍結）。
- 統計 baseline 的 fault_type 只對應 error_response / added_latency / cpu_saturation / memory_leak，在其他 fault 上 injected fault 層一定答錯；這是 baseline 的設計，不因 Pilot 結果修改（decision 014）。
