# 027 — 合成範例 `data/samples/synthetic/` 與 2 分鐘 demo

- 狀態：Accepted（2026-10-09）
- 影響範圍：新增 `data/samples/synthetic/`（進 git）、`collect/sample.py`、`python -m collect sample`、`eval/demo.py`、`python -m eval demo`、
  `.gitignore`、`tests/test_repo_hygiene.py`。**不改**任何協定、指標、split、門檻、預算、schema、normalize policy 或統計 baseline。

## 背景

- SPEC Core §2 的目錄建議有 `data/samples/`（「可進 git 的縮小範例」）；SPEC「GitHub 最終成果」要求 README 首屏有 dataset schema 與 2 分鐘 demo。
- 使用者決定：真實 incident 的 snapshot（包括縮小版）永遠不進 git；需要範例時只能是合成的、由程式產生的小 fixture。
- **與 SPEC 的差異（記錄，不改 SPEC）**：「縮小範例」可能被讀成「把真實 incident 縮小」。依使用者決定，以合成資料實現，不從任何真實 incident 縮小。

## 決策

1. **產生器** `collect/sample.py`（`uv run python -m collect sample --out data/samples/synthetic [--replace]`）：
   - 由程式產生 raw OTLP JSON：28 分鐘時間窗（normal 12、fault 10、recovery 6 分鐘，與正式協定的長度範圍一致）；每分鐘一個商品頁 request 與一個下單 request
     （load-generator → frontend-proxy → frontend → product-catalog / checkout → cart、payment），加上 payment 與 checkout 的 docker_stats CPU / memory。
     fault 期間 payment 的 Charge 全部失敗，錯誤一路傳到 frontend-proxy（模仿 `paymentFailure 100%`）。
   - raw 經過**專案真正的 normalize**（凍結且釘選的 policy v1；sha256 與重複數由 `scan_raw_file` 算，和正式 raw export 一樣），所以 snapshot 的格式與
     發布前的檢查（schema、詞彙、id、X1 load-generator span 與 X5 flag 評估事件的移除）都和正式 incident 相同。不手寫任何 canonical 檔。
   - raw 只放在暫存目錄、不進 git（可由程式重產）；`.gitignore` 另外忽略 `data/samples/**/raw/`。
   - ground truth：`injection.json`、catalog label（直接取 decision 016 的 `paymentFailure 100%` 登錄項目，`check_label` 必須通過）、normalize report。
   - 範例預測：統計 baseline 在範例上的 prediction；`usage.latency_s` 設為 null（唯一不可重現的值），其餘與 `predict()` 完全相同。
   - **逐 byte 可重現**：id 與 jitter 用 blake2b，不用 `random`；`tests/test_sample.py` 重新產生並逐 byte 比對 commit 的檔案。
     `--replace` 只會覆蓋 `sample.json` 寫明由 `collect.sample` 產生的目錄；`--out` 不能在 `data/external/` 之下。
2. **版面與正式資料相同、一樣物理隔離**：`incidents/INC-000/normalized/`（Agent 可讀，`DataLayout.is_agent_readable` 成立、`open_snapshot` 接受）
   與 `ground_truth/run_groups/RG-000/`、`ground_truth/incidents/INC-000/`（只有評分端）分開；另有 `predictions/stat-anomaly/INC-000.json`、
   `README.md`、`sample.json`（範例的 manifest：`synthetic: true`、產生器、每個檔案的 bytes 與 sha256）。
3. **id 用 `INC-000` / `RG-000`，不用 `INC-SAMPLE`**（保守解讀）：label、injection、prediction 的 schema 與 `collect.layout` 只接受
   `INC-[0-9]{3,}` / `RG-[0-9]{3,}`，而 label 必須通過 `check_label`。`collect.rungroup.next_id` 從 001 開始，000 永遠不會分配給收集到的 run，
   不會和真實 id（INC-001 起）混淆。時間用 2000-01-01（任何收集都不可能有的日期），也是一個標記。
4. **「每個檔案都說它是合成的」的實作**：
   - 格式有空間的檔案在內容裡標明：每個 resource 帶 `deployment.environment.name: synthetic-sample`，spans / logs / metric series 每一行的 scope
     名稱含 `synthetic-sample`；label 的 `labeling.notes`、injection 的 `controller.notes`、`README.md`、`sample.json` 都寫明 SYNTHETIC。
   - 格式沒有空間的檔案（`snapshot.json`、`metric_points.jsonl`、prediction：`additionalProperties: false` 或由 normalize 固定）不改格式，
     由所在目錄 `data/samples/synthetic/` 與 `sample.json` 的 sha256 清單標明。
   - injection 的 `split` 是 schema 必填，填 `pilot`；`controller.notes` 寫明範例不屬於任何 set。flag 檔 digest 是全 0 的佔位值（同樣寫在 notes）。
5. **demo** `uv run python -m eval demo`（`eval/demo.py`）：先確認 `sample.json` 說 `synthetic: true` 且每個檔案的 sha256 相符、沒有未列出的檔案，
   然後照正式順序：`open_snapshot` → 統計 baseline → 預測存在之後才讀 label → 分層分數（decision 013）、evidence existence 與弱標籤 relevance
   （decision 017）、失敗分類（decision 022），印成一張表；第一行與最後一行都聲明這是合成資料、**數字不是結果**。不寫任何檔案、不碰 `data/external/`。
6. **防止真實資料進 git**（`tests/test_repo_hygiene.py`）：`data/samples/` 下 git 會追蹤的每個檔案都必須在 `data/samples/<name>/` 裡、該目錄的
   `sample.json` 說 `synthetic: true`，而且這個檔案以相同 sha256 列在清單中；所有範例合計不超過 1 MiB。複製進來的真實 snapshot 不在任何合成清單裡，
   測試就會失敗；而 `sample.json` 本身是產生器的輸出，手動加列會讓逐 byte 比對失敗。

## 為什麼

- 使用者決定真實 snapshot 不進 git；合成範例仍能讓讀者看到真正的格式、隔離方式與評分流程。
- 經過真正的 normalize（而不是手寫 canonical 檔），範例就不會和程式脫節：normalize、policy、baseline 或 decision 016 登錄項目一改，逐 byte 比對就提醒重產。
- 用既有的 id 格式與既有函式（`check_label`、`open_snapshot`、`score_incident`、`existence`、`weak_score`、`classify`），不為範例改任何資料格式。

## 放棄的替代方案

- **`INC-SAMPLE` / `RG-SAMPLE`**：要改 label、injection、prediction、manifest、gold 五個 schema 的 id pattern 與 `collect.layout`，等於為範例改資料格式，
  也會讓正式流程接受非數字 id。
- **從真實 incident 縮小**：違反使用者決定。
- **手寫 canonical 檔**：無法保證與 normalize 一致，也不會隨程式改變而被測試發現。
- **把 raw 一起 commit**：大小約加倍，而且 raw 可由程式重產；raw 一律不進 git 比較簡單。
- **在 `snapshot.json` 或 prediction 加 `synthetic` 欄位**：要改 normalize 的輸出或 schema（decision 011、013）。
- **demo 用 `eval run` / `eval score`**：它們依 split 從 ground truth 列出 incident、寫入 `data/external/results/`；demo 只讀範例、不寫檔。

## 對實驗的影響

- 沒有。範例不在 `data/external/`，任何 set、leakage audit、方法執行與評分都看不到它；demo 的數字不是結果，不放進 README 的結果表。
- 範例的分數全對是因為合成 fault 刻意明顯，不代表統計 baseline 的能力；統計 baseline 的門檻與規則不依範例調整（decision 014）。
- 範例的 byte 會隨 normalize、policy、統計 baseline 或 decision 016 登錄項目改變；屆時重產並與該變更一起 commit（不是實驗資料的變更）。
