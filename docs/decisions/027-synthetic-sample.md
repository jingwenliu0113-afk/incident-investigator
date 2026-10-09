# 027 — 合成範例 `data/samples/synthetic/` 與 2 分鐘 demo

- 狀態：Accepted（2026-10-09）
  **修訂 1（2026-10-10，程式審查後）**：只修實作與文字，不改協定。hygiene 只接受 `data/samples/synthetic/` 一個目錄（§6）；`INC-000` 不是保留 id
  的說法更正（§3）；span 屬性改用真實 soak 的詞彙（§4）；demo 在記憶體裡跑 leakage audit、表頭標明合成（§5）；`generate()` 自己拒絕任何拼法的
  `data/external`、`--replace` 失敗時保住舊範例、不刪未列出的檔案；`incidents_in` 遇到範例的 id 直接拒絕（§1、§7）；Finder 的 `.DS_Store` 不算範例檔案。
  **補充（2026-10-10，合併審查；只改文字）**：「對實驗的影響」補上 Pilot 修訂 011 / 014 時重產範例的順序（修訂後 `tests/test_sample.py` 會失敗，直到範例重產）。
- 影響範圍：新增 `data/samples/synthetic/`（進 git）、`collect/sample.py`、`python -m collect sample`、`eval/demo.py`、`python -m eval demo`、
  `.gitignore`、`tests/test_repo_hygiene.py`；修訂 1：`eval/runner.py` 的 `incidents_in`（只多一個拒絕）。
  **不改**任何協定、指標、split、門檻、預算、schema、normalize policy 或統計 baseline。

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
     `--replace` 只會覆蓋 `sample.json` 寫明由 `collect.sample` 產生、而且只有清單上檔案的目錄（多出任何檔案就拒絕，例如被 gitignore 的 `raw/`，
     刪了無法從 git 救回；Finder 的 `.DS_Store` 除外）。替換是 fail-closed：新範例先完整寫好，舊目錄先改名移開、新目錄換進來，失敗就把舊的換回去。
   - `--out` 不能是 `data/external/` 或在它之下，由 `generate()` 自己檢查（直接呼叫也一樣）：resolve 之後逐層比對，名稱不分大小寫與 Unicode 正規化
     （APFS 不分大小寫，`data/EXTERNAL` 就是 `data/external`；在分大小寫的檔案系統上也拒絕，保守），並從最近存在的目錄比對 inode（firmlink）。
2. **路徑與正式資料相同、一樣物理隔離，但只有一部分檔案**：`incidents/INC-000/normalized/`（Agent 可讀，`DataLayout.is_agent_readable` 成立、
   `open_snapshot` 接受）與 `ground_truth/run_groups/RG-000/injection.json`、`ground_truth/incidents/INC-000/`（`label.json`、`normalize_report.json`；
   只有評分端）分開；另有 `predictions/stat-anomaly/INC-000.json`、`README.md`、`sample.json`（範例的 manifest：`synthetic: true`、產生器、
   每個檔案的 bytes 與 sha256）。正式 incident 另有的 `manifest.json`、`run.json` 與 harness 取樣、`label.reviewed.json` / `label_review.json`、
   `leakage_audit.json`、evidence gold 範例都**沒有**（README 與範例的 README 寫明）。
3. **id 用 `INC-000` / `RG-000`，不用 `INC-SAMPLE`**（保守解讀）：label、injection、prediction 的 schema 與 `collect.layout` 只接受
   `INC-[0-9]{3,}` / `RG-[0-9]{3,}`，而 label 必須通過 `check_label`。`collect.rungroup.next_id` 從 001 開始，000 永遠不會分配給收集到的
   run group 或 incident，不會和真實 id（INC-001 起）混淆。
   **更正（修訂 1）**：`INC-000` 不是只屬於範例的 id。`collect calibrate` 也把 soak 的 snapshot（沒有 fault、不屬於任何 set）寫在
   `data/external/calibration/<soak>/<ts>/incidents/INC-000/`，所以 id 本身不代表合成；範例由所在目錄、`sample.json`、2000-01-01 的時間窗
   （任何收集都不可能有的日期）與 resource 上的 `synthetic-sample` 標記辨認。測試列出程式中所有用到 `INC-000` / `RG-000` 的檔案
   （只有 `collect/sample.py` 與 `collect/calibrate.py`），新增用法會被發現。選擇保留 000 而不換成 900 之類：000 是 `next_id` 唯一確定不會給出的編號。
4. **「每個檔案都說它是合成的」的實作**：
   - 格式有空間的檔案在內容裡標明：每個 resource 帶 `deployment.environment.name: synthetic-sample`，spans / logs / metric series 每一行的 scope
     名稱含 `synthetic-sample`；label 的 `labeling.notes`、injection 的 `controller.notes`、`README.md`、`sample.json` 都寫明 SYNTHETIC。
   - 格式沒有空間的檔案（`snapshot.json`、`metric_points.jsonl`、prediction：`additionalProperties: false` 或由 normalize 固定）不改格式，
     由所在目錄 `data/samples/synthetic/` 與 `sample.json` 的 sha256 清單標明。
   - **屬性詞彙與真實 snapshot 相同（修訂 1）**：span 與 resource 的屬性 key 都取自凍結 policy 的 `attribute_key_inventory`（真實 soak 看到的 key）：
     frontend-proxy 用 Envoy 的 `http.method` / `http.url` / `http.status_code`，checkout 與 product-catalog 用 `rpc.system.name` / `rpc.method`，
     cart 用 `grpc.method`，payment 用 `rpc.system` / `rpc.service` / `rpc.method`。範例的 normalize report 裡唯一的新 key 是刻意加上的
     `deployment.environment.name` 標記（每個 resource 一個），測試釘住這一點；正式流程中這個新 key 會依 decision 015 交人看，範例不經過那一步。
   - injection 的 `split` 是 schema 必填，填 `pilot`；`controller.notes` 寫明範例不屬於任何 set。flag 檔 digest 是全 0 的佔位值（同樣寫在 notes）。
5. **demo** `uv run python -m eval demo`（`eval/demo.py`）：先確認 `sample.json` 說 `synthetic: true` 且每個檔案的 sha256 相符、沒有未列出的檔案
   （Finder 的 `.DS_Store` 不算），然後照評分端的順序：`open_snapshot` → 統計 baseline → 預測存在之後才讀 label（label 的 bytes 在檢查 sha256 時
   已被雜湊，但內容在預測之後才解析；測試釘住這個順序）→ leakage audit（decision 015，在記憶體裡算、不寫 `leakage_audit.json`；有 lexicon hit 就拒絕，
   對應 runner 把這種 incident 排除在所有分數之外）→ 分層分數（decision 013）、evidence existence 與弱標籤 relevance（decision 017）、
   失敗分類（decision 022），印成一張表。第一行與最後一行都聲明這是合成資料、**數字不是結果**；表頭本身也寫 `SYNTHETIC sample, not a result`，
   只複製表格也帶著標記。不寫任何檔案、不碰 `data/external/`。demo 不是 `eval run` / `eval score`：沒有 run manifest、label review、gold，
   也不經過 Pilot 的 incident 清單。
6. **防止真實資料進 git**（`tests/test_repo_hygiene.py`，修訂 1 收緊）：`data/samples/` 下 git 會追蹤的每個檔案都必須在
   `data/samples/synthetic/` 這**一個**目錄裡（其他目錄即使附上自稱 `synthetic: true` 的 `sample.json` 也拒絕）；它的 `sample.json` 說
   `synthetic: true`、產生器是 `collect.sample`；每個檔案以相同 sha256 列在清單中；檔名與內容裡出現的 incident / run group id 只能是
   `INC-000` / `RG-000`；所有範例合計不超過 1 MiB。這個目錄也是 `tests/test_sample.py` 重新產生、逐 byte 比對的目錄，所以手動加檔或改清單
   會讓那個比對失敗。hygiene 的自我測試涵蓋：其他目錄附偽造 manifest、`synthetic: false`、別的產生器、未列出的檔案、缺 manifest、
   其他 id、超過 1 MiB。
7. **正式讀取端 fail-closed（修訂 1）**：範例的 injection 寫 `split: pilot`（schema 必填）。若範例被放進正式根目錄，
   `eval.runner.incidents_in`（Pilot 的 run / score / leakage / gold-todo 都經過它）遇到 `RG-000` 或 `INC-000` 就丟出錯誤、CLI exit 2，
   不會把它當成 Pilot incident；held-out 端本來就因 `RG-000` 沒有 `run.json` 而停止。收集端（`next_id`）不改。

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

- 沒有。範例不在 `data/external/`，任何 set、leakage audit、方法執行與評分都看不到它（被放進去時 `incidents_in` 拒絕）；demo 的數字不是結果，
  不放進 README 的結果表。修訂 1 對真實資料沒有任何行為改變：`incidents_in` 只多一個對 `RG-000` / `INC-000` 的拒絕，而 `next_id` 從不給出 000。
- 範例的分數全對是因為合成 fault 刻意明顯，不代表統計 baseline 的能力；統計 baseline 的門檻與規則不依範例調整（decision 014）。
- 範例的 byte 會隨 normalize、policy、統計 baseline 或 decision 016 登錄項目改變；屆時重產並與該變更一起 commit（不是實驗資料的變更）。
- **Pilot 修訂時的順序**（補充 2026-10-10）：023 §6 允許 011（normalize policy）與 014（統計 baseline）各在 Pilot 上修訂一次。
  修訂改了 policy 或統計 baseline，`tests/test_sample.py` 的逐 byte 比對與範例 prediction 的測試就會失敗；而 `generate()` 拒絕未凍結或未釘選的 policy，
  所以範例只能在 policy 重新凍結、`collect/policy.py` 的 `POLICY_SHA256` 重新釘選之後重產。順序：修訂程式 →（011）凍結 policy v2 並釘選 sha →
  `uv run python -m collect sample --out data/samples/synthetic --replace` → 重產的範例與修訂放在**同一個 commit** → 跑測試 → push。
  014 只改統計 baseline 時，最多只有 `predictions/stat-anomaly/INC-000.json` 與 `sample.json` 的 sha 清單會變（demo 也比對 commit 的範例 prediction，重產前同樣失敗）。重產不影響 Pilot 的收集與評分指令，範例的數字也不是結果。
