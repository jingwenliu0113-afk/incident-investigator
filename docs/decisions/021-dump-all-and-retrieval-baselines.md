# 021 — Dump-all 與 Retrieval baseline 的結構（打包順序、檢索方式）

- 狀態：Accepted（結構，2026-10-09）；在任何 LLM baseline 執行之前寫定。**預算數值與模型由使用者決定**（decision 011「延後」），
  下面的數字只是建議值；第一次呼叫付費 API 之前依 MACHINE_POLICY 報告成本並等批准。可在 Pilot 上修訂一次，held-out 之前凍結。
  **Pilot 上的那一次修訂已於 2026-10-11 使用**（使用者決定；文末「Pilot 上的修訂（2026-10-11，使用者決定）」：概覽寫明它的列不能引用）。
- 影響範圍：SPEC Core §7 第 1 組（dump-all + LLM）與第 2 組（retrieval + LLM）。

## 背景

- 一個 incident 的 snapshot 約 300 MB（soak #5 的 38 分鐘：約 19 萬個 span、11 萬筆 log、40 MB 的 metric point），換算約 7,500 萬 proxy tokens；
  任何模型都放不下，「dump-all」必須是一個固定、與 incident 無關的打包規則，在預算 B 內盡量放進「全部」。
- 所有 LLM 方法共用 decision 020 的任務說明、`submit_diagnosis` 與驗證 / 更正規則，差別只在取得資料的方式（SPEC §7「可見資料範圍」）。

## 決策

### 1. 共同的概覽區塊（三個 LLM 方法都可以看到，Agent 用 `service_minute_stats` 自己取）

每個服務每分鐘的 span 數、error span 數、server span p95、WARN 以上 log 數、CPU 核數、記憶體（decision 019 的同一套定義），依服務名稱、分鐘排序。
這是中性的數量，不是分數或排名（decision 011 §5）。

### 2. Dump-all（`baselines/dump_all.py`），預算 B proxy tokens

固定的打包順序，超過 B 時從最後一段開始截：
1. 概覽區塊（§1）。
2. **error 等級的 record**（status = error 的 span、severity ≥ WARN 的 log），依 decision 015 的樣板分組：每組列出筆數、首次與最後出現時間，
   並放第一筆與最後一筆的完整 render v1 行；組依首次出現時間排序。
3. **其他 record 的時間分層樣本**：把時間窗切成每分鐘一格，每格依 id 排序後輪流從 span、log 取，直到用完 B；同一格內的選取以 incident id 為種子決定。
- 一次呼叫（加上最多 2 次更正）；沒有工具。usage 的 retrievals = 0、tool_calls = 0、proxy_tokens = 送進去的打包內容。
- 建議 B = 120,000 proxy tokens（約可放進 200k context 的模型，含任務說明與回答）。

### 3. Retrieval（`baselines/retrieval.py`），預算 q 個查詢 × 每個 k 筆

兩次呼叫（各加最多 2 次更正）：
1. 模型看任務說明與概覽區塊，用 `propose_queries` 提出最多 q 個查詢（文字，可加服務與時間範圍）。
2. 每個查詢在 span 與 log 上做 **BM25 排序**（sqlite FTS5，以 render v1 的行建索引；同分依時間），取前 k 筆；去重後依時間排序，
   連同概覽區塊交給模型，模型呼叫 `submit_diagnosis`。
- 與 Agent 的差別：只有一輪、由相關度排序取資料、不能看 metric 的點、不能翻頁或追 trace。
- usage 的 retrievals = 查詢數、proxy_tokens = 檢索結果與概覽送進去的量。
- 建議 q = 8、k = 25（最多 200 筆，約 5 萬 proxy tokens）。

### 4. 公平性

- 三個 LLM 方法用同一個模型、同一份任務說明；報告列出各自的 proxy tokens、tool / retrieval 次數、實際 tokens、latency、cost（SPEC §7）。
- Agent 的工具輸出 proxy token 上限建議與 dump-all 的 B 相同（120,000），工具呼叫數上限建議 40、回合數上限 30：
  Agent 看到的資料總量不超過 dump-all，勝出不能是「看了更多」。

## 為什麼

- error 等級的 record 先放、依樣板去重：在有限的預算內，這是不依賴 incident 的最強固定規則；比均勻抽樣更難被 Agent 擊敗，比較才有意義。
- 時間分層樣本：讓模型看到 normal 與之後的「正常長什麼樣子」，不只看到錯誤。
- Retrieval 用 BM25：這是 retrieval baseline 的一般作法；Agent 的工具刻意不排序（decision 019），兩者因此是不同的資料取得方式。

## 放棄的替代方案

- **均勻抽樣整個 snapshot**：error 很稀少，抽樣幾乎看不到，baseline 會過弱。
- **dump-all 用摘要（例如每個服務的統計）取代 record**：那是另一種方法（接近統計 baseline + LLM），而且沒有可引用的 evidence。
- **Retrieval 用固定的查詢詞（例如 error、timeout）**：等於把查詢策略寫死成我們的猜測；讓模型提查詢才是 retrieval + LLM 的一般形式。

## 實測（soak #5 的無 fault 校準 snapshot，38 分鐘）

- dump-all（B = 120,000）：打包 3 秒、119,338 proxy tokens；概覽 703 行（約 1.8 萬 tokens）、error 樣板 5 組、時間分層樣本 509 筆。
- retrieval：FTS5 索引建立 7 秒、347 MiB（依 content digest 快取）；每個查詢 < 0.1 秒。

## 補註（2026-10-10，decision 029）

- 使用者暫時同意 LLM 方法先試本機模型（Ollama）。本文件的結構與建議的預算數值**不變**；三個 LLM 方法仍用同一個模型（§4）。
- B = 120,000 是為約 200k context 的模型設計。本機模型的 `num_ctx` 必須放得下「預算 + overhead」（`eval/runner.py` 的 `llm_fit`；
  建議的設定、num_predict 8192 時 dump-all 需要 130,567、Agent 需要 131,586 proxy tokens），放不下就拒絕執行、不自動縮預算；改預算是使用者的決定。

## Pilot 上的修訂（2026-10-11，使用者決定）

- 使用者原話（2026-10-11，看過三個 LLM 方法在 Pilot 上的結果之後）：
  > 選方案 (a)。
  > 請修正 Retrieval 引用不存在 evidence ID 的問題，確保所有引用都能對應到真實證據。
  > 不得為了提高分數放寬引用驗證，也不要更改既有評分門檻。
  > 修正必須記錄 decision log，保留原始 Pilot 結果，然後在相同模型、資料、預算及評測條件下，重新執行受影響的正式方法。
  > 方案 (b)、(c) 暫時不修改，保留在 failure analysis。
  > Evidence gold 標註請先準備互動式審查流程，一次帶我處理一個 incident，不要要求我自行編輯 JSON。
  > 完成後更新報告、測試、commit、push，再依原本 Gate 判斷是否需要 Advanced。

  後兩句（gold 標註的審查流程、收尾）不屬於本修訂。
- 提給使用者的三個方案：**(a)** 概覽的每分鐘列被當成證據引用 → 寫明它們不能引用、只能引用紀錄 id；(b) 三個 LLM 方法都只給一個 origin 候選
  （top3 = top1）；(c) Agent 到回合上限。**本修訂只做 (a)**；(b)、(c) 不改，留在失敗分析（decision 022 補註（2026-10-11））。
- 時間：三個 LLM 方法在 RTX 5070 Ti 上的 Pilot 執行（029 修訂 1，commit `f001e94`）評分之後；任何 held-out 資料與 freeze 之前。

### 證據（Pilot transcript，主 session 讀過）

- RTX 5070 Ti 的執行：dump-all 的 INC-009、INC-010 提交 `m-ad+012:00`、`m-checkout+017:00` 這類 evidence id——由概覽列
  `ad +012:00 spans=… cpu_cores=…` 拼成——被 `check_prediction` 拒收（id 必須符合 `^[slmpt]-[0-9a-f]{16,32}$`），更正兩次後仍不合格，以
  `invalid_submission` 結束（沒有答案，022 的 `no_answer`）。模型自己寫「the metric series are listed in the per-service and minute section with IDs like m-ad+012:00」。
- 被取代的 Mac 執行（封存在 `data/external/archive/pilot-llm-mac-2026-10-11/`）：retrieval 的 INC-005、INC-011 同樣（`m-cart-10:00`、`m-recommendation+015:00`）。

### 原因

- 三個 LLM 方法共用的任務說明（decision 020 §1，`agent/prompt.py`）說 evidence id 是「s-..., l-..., m-..., p-..., or t-<trace id>」，
  並說「for a metric series (m-...) you may add t0 and t1」。這對 Agent 是對的（它的工具列出 metric series 與 point），
  但 dump-all 與 retrieval **看不到任何 `m-` / `p-` id**：只看到 span 與 log 的紀錄行（`s-`、`l-`，span 行內有 `trace_id`）和概覽區塊（§1：每服務每分鐘的彙總，沒有 id）。
  概覽的 CPU、記憶體欄來自 metric，模型因此把 `m-` 前綴和概覽列拼在一起。
- 引用驗證本身是對的：這些 id 不符合 id 的格式（也不對應任何紀錄），拒收是正確的。缺的是「概覽列不是可引用的紀錄」這句話。

### 修訂

1. **`baselines/overview.py`**：概覽的標題行之後加一行固定的說明（每個 incident 都相同，不提示任何故障、不含任何 id）：
   ```text
   These rows are aggregates computed from the snapshot, not records: they have no id and cannot be cited as evidence. Evidence must be ids that appear in the span and log records shown to you: the id at the start of a record line (s-... for a span, l-... for a log), or t- followed by the trace_id of a span shown. This data shows no metric series (m-...) or metric point (p-...) ids.
   ```
   **標題與每一列的內容、順序都不變**（測試用修訂前的程式逐行比對測試用 snapshot 與合成範例）。
2. **dump-all**（§2）：標題與說明是一個單位，只和第一列一起放進去（「section 標題只和第一行一起」的規則不變）；說明不是概覽列，
   不算進 exposure 的 `stats:` 格子（decision 022）。打包順序、error 群組、時間分層樣本與截斷規則不變。
3. **retrieval**（§3）：第一次呼叫的概覽區塊同樣帶這一行；查詢、BM25、q、k 不變。
4. **method 版本**：dump-all 與 retrieval 的 prediction 記 `method.version` = `"2"`（原始 Pilot 執行是 `"1"`），Agent 維持 `"1"`
   （`eval/runner.py` 的 `LLM_METHOD_VERSIONS`）。只是 provenance：分辨重跑與封存的原始結果，評分不讀它。

為什麼這樣改：
- **列不改**：列的格式（`ad +012:00 …`）也是 decision 022 exposure（`stats:<service>:<分鐘>`）的解析依據；改列會同時改變模型讀到的內容，
  原始 Pilot 與重跑之間就不只一個差別。問題出在沒有說明，直接寫明是最小的修正。
- **`t-` 也寫進去**：020 的任務說明允許 `t-<trace id>`，dump-all / retrieval 的 span 行有 `trace_id`，`Snapshot.resolve` 找得到；
  只寫 `s-` / `l-` 會比 020 更窄，等於另外縮小了方法能引用的範圍。
- **寫明沒有 `m-` / `p-` id**：直接對應原因（020 的說明列出 `m-`）；不說哪一種 metric 或哪一個服務，不是提示。
- **不改 020 的任務說明**：它對 Agent 是正確的，改它會改到 Agent 的輸入、Agent 就要重跑；020 在 Pilot 上的那一次修訂不在這裡使用。

### 不變的

- **引用驗證不放寬**：`check_prediction`、prediction schema 的 id pattern、`Snapshot.resolve` 與 evidence existence / relevance 都不變；
  格式不合的 id 照樣在提交時拒收，格式合但不存在的 id 照樣在評分時計為未解析（existence）。
- harness 的更正訊息與更正次數上限（020 §3）、020 的任務說明（`agent/prompt.py`）。
- 指標、評分門檻、切分、Gate 條件。
- 預算：B = 120,000、q = 8、k = 25、Agent 40 次工具 / 120,000 proxy tokens / 30 回合（`eval/llm_methods.json` 不變，所以重跑的 `run_config.json` 與原始執行相同）。
- 模型與設定：qwen3.5 9B（digest `sha256:6488c96f…3ea7`）、Ollama 0.35.0、`num_ctx` 262,144、`num_predict` 8192、temperature 0、seed 42、think 關、`timeout_s` 3600；
  推論主機 gpu-server（029 修訂 1）。
- **Agent**：工具、任務說明、system 文字都不變（測試釘住 Agent 輸入的 sha256，並確認 `agent/` 不使用概覽），所以 Agent **不重跑**。

### 影響（在合成範例上量測，decision 027；不是結果）

- 說明是固定的一行，概覽多 **96 proxy tokens**（合成範例：169 行 3,732 → 170 行 3,828）。
- dump-all 的 B 固定，留給時間分層樣本的空間因此少 96 proxy tokens：合成範例在 B = 120,000 時全部放得下（38,376 → 38,472 proxy tokens，
  樣本 248 筆不變）；在 B 會截斷的情況（B = 30,000：樣本 184 → 183 筆；B = 10,000：33 → 32 筆），樣本行平均 131 proxy tokens，約少一筆。
  Pilot 的 snapshot 遠大於 B，預期每個 incident 的樣本少約一筆（數百筆之中）。
- retrieval 沒有 proxy-token 預算；報告的 `proxy_tokens` 每個 incident 多 96。
- **已知的 coverage 限制，不改**：dump-all 與 retrieval 依設計仍不能引用 metric series（§3「不能看 metric 的點」；dump-all 只放 span 與 log）。
  資源類 fault（CPU、記憶體、GC）在這兩個方法裡只能以 span / log 為證據；這是方法之間「可見資料範圍」的差別（SPEC §7），在報告中照實寫。
- 這個修訂改的是方法給模型的說明，不是驗證，所以**不保證**模型只引用存在的 id：格式不合的仍在提交時拒收（更正兩次後放棄作答），
  格式合但不存在的仍在 evidence existence 中計為未解析並報告。在提交時檢查 id 是否存在會改到 020 的 harness（也改到 Agent），不在本修訂。
- 修訂後若仍有模型引用概覽列或其他不存在的 id，照上面的規則處理並記錄為觀察；021 的一次修訂已用掉，不再修。

### 這是 021 在 Pilot 上的那一次修訂

- freeze 的 Pilot 修訂宣告寫 `"021": {"status": "used", "decision": "docs/decisions/021-dump-all-and-retrieval-baselines.md"}`
  （`collect/freeze.py` 的規則不變；測試確認這個宣告通過檢查）。之後 021 不能再在 Pilot 上修訂。

### 測試（先寫測試、看它失敗，再實作；1111 passed，`-m "not network and not docker_daemon"`）

- `tests/test_llm_baselines.py`：說明在概覽中、標題與每一列和修訂前的程式（逐字複製在測試裡）逐行相同（測試用 snapshot 與合成範例）、說明不提任何故障也不含 id；
  dump-all 與 retrieval 送給模型的第一則訊息都帶說明且在列之前；dump-all 在各種截斷預算下，標題從不在沒有說明時出現、說明不算概覽列；
  Agent 的 system、任務說明與工具的 sha256 與修訂前相同、`agent/` 不使用概覽、Agent 的 transcript 沒有說明；dump-all / retrieval 的 method 版本 "2"、Agent "1"。
  既有的「截斷的概覽只 claim 打包進去的列」測試：預算 60 在標題變長之後一列都放不下、測試會變成空的，改為 200（期望的 exposure 寫明）。
- `tests/test_local_llm.py`：Pilot 執行的 prediction 依方法期望版本（dump-all / retrieval "2"、Agent "1"）。
- `tests/test_heldout_freeze.py`：021 宣告 used 並指名本文件時通過 freeze 的 Pilot 修訂檢查；used 不指名文件、waived 卻指名文件仍被拒絕。
- 沒有執行任何模型、server、ssh 或 Docker，也沒有讀 `data/external`。

### 重跑計畫（主 session；指令見 NEXT）

1. **封存原始結果**（只複製，封存目錄必須還不存在、不覆寫任何既有封存）：dump-all 與 retrieval 目前的 Pilot 輸出
   （prediction、transcript、`run_config.json`、`power.jsonl`、`scores.json`、`table.md`）→
   `data/external/archive/pilot-llm-gpu-2026-10-11-before-021-revision/`。原始結果保留、照樣報告（標明是修訂前），不再評分。
2. 合併本修訂進 main 之後，在 `./tools/with-remote-ollama` 之下用相同的模型、資料、預算與評測，在 Pilot 上**整個重跑** retrieval 與 dump-all。
3. 評分；修訂前後並列（不只報修訂後）；`eval compare` 與 `eval gate`（agent 對 stat-anomaly：Agent 與統計 baseline 都沒有重跑，Pilot 的 Gate 診斷預期不變，重跑只是確認）。
4. Agent 不重跑（輸入不變）。
5. 之後再產生 evidence gold 工作表（`eval gold-todo`）：重跑後 dump-all 與 retrieval 的引用會變，修訂前的引用不需要標。
