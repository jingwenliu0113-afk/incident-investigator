# 005 — Known ambient failure sources；OpenSearch 不得作為 snapshot / source of truth

- 狀態：Accepted（2026-10-08，使用者決定）
- 影響範圍：baseline 的判讀、M2 snapshot 的資料來源、之後的 leakage audit 與評測

## 背景（證據，見 `docs/smoke-tests/2026-10-08-m1-mac-smoke.md`）

1. Load generator 的 `ask_agent` task 固定打 `http://agent:8010/prompt`，但我們鎖定的 compose 組合沒有 agent stack，
   所以會持續出現 `NameResolutionError` / `gaierror(-2)`（run 2：959 個 request 中 79 次，約 5.4 次/分，8.2%）。這跟任何注入的 fault 無關。
2. OpenSearch exporter 因 `attributes.http` 的 mapping 衝突持續拒收 log（run 1：308 個 export request 失敗、逐筆拒收 1,624 次；
   run 2：430 個 request 失敗、逐筆拒收 3,073 次）。collector 判定為 permanent error，不會重試。

## 決策

1. **`ask_agent` 標記為 known ambient failure source。**
   - 現在**不**刪除、不停用、不 patch（不改 image、不加 agent stack）。
   - soak test 與之後的 baseline 判讀中，記錄它的數量，但不算 unexpected failure。
   - **M2 之後**再根據實際的 snapshot 判斷它會不會污染 RCA 評測（例如 Agent 或 baseline 是否把它當成根因），屆時另開 decision log 決定處理方式。
2. **OpenSearch 不得作為正式 snapshot 或 source of truth。**
   - M2 raw export 以**不經 OpenSearch 損失**的原始 telemetry 為主（具體做法在進 M2 時另寫 decision log，見研究筆記 §4）。
   - OpenSearch、Jaeger、Grafana 只能作為人工檢視的 UI，不得作為 Agent / baseline 的資料來源，也不得用來判斷 telemetry 是否完整。

## 放棄的替代方案

- **現在就停用 `ask_agent`**（Locust class picker 或 patch locustfile）：會改變 traffic profile 或 image；在還沒看到它對評測的實際影響前，先不改。
- **修 OpenSearch mapping**（預先建立 index template）：屬於修改 upstream observability 設定；而且 OpenSearch 本來就不該是 source of truth，修它不解決根本問題。

## 對實驗的影響

- Baseline 中「正常」的定義包含這兩個已知來源：`ask_agent` 的錯誤 span / log，以及 OpenSearch 不完整。
- Leakage audit 與 failure taxonomy 要能區分「ambient failure」與「注入的 fault」。
