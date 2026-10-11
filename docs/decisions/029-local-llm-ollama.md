# 029 — LLM 方法暫時改試本機模型（Ollama adapter、截斷防護、模型釘選、合成範例探測）

- 狀態：Accepted（2026-10-10，使用者決定，**暫時**）。使用者原話：
  「先暫時兩個都同意，先關掉 grafana 下載再測本地模型，之後可以考慮再換回來原本的方案」。
  寫在任何 LLM 方法的執行（包括合成範例的探測）、任何 held-out 資料與 freeze 之前。使用者之後可以換回原本的方案（付費 API 模型），換回時另寫 decision log
  （見「對實驗的影響」）。「兩個」的另一項（關掉 grafana 的 plugin 下載，NEXT A0）不在本文件。
  **使用者決定的範圍**：先試本機模型，依序做提案的三步（見「背景」）。其餘的實作細節是助理依提案做的設計；比提案更嚴格、使用者還沒確認的部分
  （Ollama 版本釘選）列在「不在本文件決定」，等使用者確認（2026-10-10 已確認：釘選，見下一段）。
  **使用者決定（2026-10-10，探測之後、任何 Pilot 上的 LLM 執行之前）**：使用者原話「照建議」，一次同意助理在探測之後提出的八項建議：
  模型 qwen3.5 9B、`num_ctx` 262,144、think 關、Ollama 版本釘選、LLM 執行也要求高效能模式 + AC 並記錄電力狀態、`num_predict` 8192、
  freeze 的兩項檢查寫進程式、grafana 的背景安裝器維持現狀。`eval/llm_methods.json` 改為 `approved`；「不在本文件決定」的各項都已決定。
  見文末「使用者決定（2026-10-10）：照建議」。只拒絕更多或只增加紀錄，預算、指標、切分、門檻都不變。
  **使用者決定的實作審查（2026-10-10，任何 Pilot 上的 LLM 執行之前）**：`ollama.timeout_s` 改回提案的 3600（實作時改成的 7200 不在八項之內，
  探測速度的估計也沒有超過 3600；要不要加長是使用者的決定，見文末「`timeout_s`」一節）；`power.jsonl` 每一行另記該次執行 `run_config.json` 的 sha256，
  freeze 用它拒絕中途停止的 Pilot 執行留下的舊 prediction（026 解讀 32）；held-out 失敗嘗試的 latency 不是在正式電力條件下量測時，評分也列出；
  補上不可重試的錯誤與不合格的 prediction 之後電力紀錄的測試。只拒絕更多或只增加紀錄。
  **審查（2026-10-10，合併前、任何執行之前）**：每個 incident 的釘選檢查移到嘗試開始之前；整個執行只用開始時讀到的設定；
  解析不了的 tool call 參數由 harness 拒收；回覆檢查加上兩項不依賴 `truncate: false` 的檢查；探測的防護自我測試要求 server 自己拒絕並加上多則訊息的情況；
  server 與模型只在一次 heavy lock 內存在（`tools/with-local-ollama`、執行結束時卸載模型）；Ollama 版本釘選改列為待使用者確認；探測記錄電力狀態。
  只拒絕更多或只增加紀錄，沒有放寬任何條件。
  **修訂 1（2026-10-11，使用者決定「同意」；Pilot 上 retrieval / agent 已在 Mac 跑過、任何 held-out 資料與 freeze 之前）**：推論改在使用者的
  RTX 5070 Ti 桌機（`ollama.host` = `gpu-server`，`tools/with-remote-ollama`；eval、snapshot 與 ground truth 留在 Mac），這種執行不需要 Mac heavy lock、
  不檢查 Mac 的電力模式，改為記錄 GPU 的狀態；三個 LLM 方法要在 Pilot 上用 GPU 重跑。模型與其他設定、預算、指標都不變。見文末「修訂 1」。
- 影響範圍：新增 `agent/ollama.py`（adapter）、`eval/probe.py`（`python -m eval local-probe`）、`tools/with-local-ollama`；
  `eval/runner.py`（`load_llm_config`、`llm_fit`、`start_llm`、`pinned_model`、`finish_llm`、`run_llm`、`_llm`、`run_config.json` 的 `llm`、評分表多一行）；
  `agent/harness.py`（`_arguments`：adapter 標記為解析不了的參數照 020 §3 拒收；`CallError` 的說明）；`eval/__main__.py`；
  `eval/llm_methods.json`（只新增欄位，仍是 `proposed`）；decision 020 §6 與 021 的補註；README 的狀態句；`tools/README.md`。
  **使用者決定（2026-10-10）之後**：`eval/llm_methods.json`（`approved`；`timeout_s` 維持提案的 3600）；`eval/runner.py`（電力條件 `formal_power`、
  `power.jsonl`、評分的 `latency_power`、`pilot_llm_problems`）；`agent/ollama.py`（`pinned_record`）；`collect/freeze.py`（026 修訂 3）；
  decision 023、026、028 的補註；README；NEXT。
  **不改**任何預算數值、指標、切分、門檻、freeze 協定，也不改 decision 013、020–024、026 的任何規則（`RETRYABLE` 仍只有 `api_error`、`transport_error`）。
  **修訂 1（2026-10-11）**：新增 `tools/with-remote-ollama`、`eval/inference_host.py`；`eval/llm_methods.json`（`ollama.host`、`note`）；
  `agent/ollama.py`（`HOSTS`、`config_problems`、`run_record` 的 `host`）；`eval/runner.py`（`start_llm`、`host_watch`、`MacPower`、`GpuState`、
  `power.jsonl` 的 `host`、評分的 `latency_power` 與表）；`eval/probe.py` 與 `eval/__main__.py`（`--host`）；MACHINE_POLICY「遠端 GPU」；
  026 解讀 32 的補註；README；`tools/README.md`；NEXT。

## 背景

- NEXT A1：使用者 2026-10-09 決定付費 API 的 LLM 方法先延後；程式已就緒，但沒有 adapter（decision 020 §6：harness 只依賴
  `complete(system, messages, tools) → {content, usage}`，訊息採 Anthropic Messages API 的形狀，真正的 client 是另外的 adapter）。
- 2026-10-10 向使用者提出、使用者同意的提案，依序：
  1. 寫 decision log，加一個 Ollama adapter：固定 context 長度（Ollama 對超過 `num_ctx` 的 prompt 會**靜默截斷**，必須防住）、temperature 0、記錄模型檔的
     digest 與 Ollama 版本；
  2. 先在**合成範例**上測三個本機模型（絕不用 Pilot 資料）的 tool calling 與速度，回報建議的模型與時間估計；
  3. **使用者同意之後**，才在 Pilot 上執行三個 LLM 方法。
  本文件與這次的程式只做 1 與 2 的工具；不批准任何東西、不選模型、不執行任何模型。
- 本機狀態（2026-10-10，只讀檔案，沒有啟動 server）：Ollama 0.35.0（`/opt/homebrew/bin/ollama`）；Mac M4 Pro、48 GB。已安裝的模型（manifest 的 sha256 前 12 碼；探測會再從 API 讀一次）：

  | tag | manifest digest | GGUF context_length | tool 的呈現 |
  |---|---|---:|---|
  | `qwen3:8b-q4_K_M` | `500a1f067a9f…` | 40,960 | template 有 `.Tools` |
  | `qwen3.5:9b-q4_K_M` | `6488c96fa5fa…` | 262,144 | 內建 renderer / parser `qwen3.5`（需要 Ollama ≥ 0.17.1） |
  | `gemma4:12b-it-q4_K_M` | `4eb23ef187e2…` | 262,144 | 內建 renderer / parser `gemma4`（需要 Ollama ≥ 0.30.5） |

  模型自帶的預設取樣參數不同（qwen3：temperature 0.6、top_k 20；qwen3.5：temperature 1、presence_penalty 1.5；gemma4：temperature 1、top_k 64）。
- Ollama 0.35.0 的執行檔裡有 `/api/chat` 的 `truncate`、`shift` 欄位，以及 "truncating input messages which exceed context length"、
  "the input length exceeds the context length"、"input exceeds maximum context length and cannot be truncated further" 等訊息：
  預設會丟掉舊訊息、截斷 prompt，生成到 context 盡頭時 shift（丟掉前面的 token）繼續，全部不報錯。
  執行檔也帶著 llama-server 的 `prompt_n`、`cache_n`、`tokens_evaluated` 欄位：`prompt_eval_count` 在 prompt 有快取時是整個 prompt 還是只有沒快取的部分，
  只看執行檔無法確定（探測的 repeat_check 會量）。`prompt_eval_count`、`eval_count` 都帶 `omitempty`：數值 0 時欄位不出現。
- decision 021：dump-all 的 B = 120,000 proxy tokens，是為約 200k context 的模型設計；三個 LLM 方法用同一個模型（021 §4）。
- MACHINE_POLICY：本機硬體運算不是外部費用；但數小時的本機模型執行是 heavy workload。

## 決策

### 1. Adapter（`agent/ollama.py`，只用標準函式庫）

1. 實作 decision 020 §6 的介面：`OllamaModel.complete(system, messages, tools)` → `{content, usage, stop_reason, ollama}`（harness 只讀 content 與 usage）。
   - 送出：`system` → system 訊息；text → user / assistant 的 content；`tool_use` → assistant 的 `tool_calls`；`tool_result` → `role: "tool"` 訊息
     （帶 `tool_name` 與 `tool_call_id`；`is_error` 的內容本來就以 `error:` 開頭）；thinking → assistant 的 `thinking`。tools → `{"type": "function", ...}`。
   - 收回：`tool_calls` → `tool_use`，id 由 adapter 產生、可重現（`toolu_<回合>_<序號>`，與 Ollama 自己的 id 無關）；text → text；thinking → thinking block（transcript 保留）。
   - **參數**：物件照用；字串先解析成 JSON；`null`（沒有參數：Ollama 把空的 map 寫成 null）視為空物件。其他（解析不了的字串、陣列、數字等不是物件的值）
     `input` 保持空物件（Anthropic 的形狀），原文放在 `unparsed_arguments`。harness（`agent/harness.py` 的 `_arguments`）把帶這個欄位的 block 照 020 §3
     當成不合格：`submit_diagnosis` 回「the answer is malformed」並要求更正（最多 2 次，之後放棄作答），Agent 的工具回「arguments must be an object」
     （照常計一次工具呼叫）。**絕不**當成空的答案（空的答案是合格的放棄作答）。retrieval 的 `propose_queries` 沒有更正回合（021 §3），
     這種提案等於沒有查詢；原文留在 transcript。Anthropic 的 adapter 永遠給物件，不受影響。
   - `stream: false`；options：`temperature`、`seed`、`num_ctx`（必填，絕不用 Ollama 的預設）、`num_predict`（輸出上限）；`think` 開或關（記錄）。
   - usage：`prompt_eval_count` → input tokens、`eval_count` → output tokens（欄位不在就是 0，見「背景」）。
2. **只連本機**：URL 必須是 `http://` 加 `127.0.0.1`、`localhost`（解析結果必須全部是 loopback）或 `::1`；直接用 `http.client`（不經過任何 proxy 設定）；
   tag 以 `cloud` 結尾、或 `/api/tags`、`/api/show`、任何一次回覆帶 `remote_model` / `remote_host` 的模型（Ollama 的 cloud 模型）一律拒絕。
   這個 adapter 因此不可能連到遠端或付費服務。

### 2. 截斷防護：一次呼叫絕不靜默截斷

1. 每個請求都送 `truncate: false`、`shift: false`。**預期**（不是已確認的事實）Ollama 因此回錯誤，而不是丟訊息或 shift；
   這台機器、這個 Ollama 版本實際是否如此，由探測的防護自我測試確認（§5：一則長訊息與多則訊息兩種情況，都必須是 **server 自己**拒絕）。
   adapter 不依賴這一點：下面每一項回覆檢查都在不信任 `truncate: false` 的前提下成立。
2. 每個回覆都檢查，任何一項不成立就丟 `CallError`（`guard` 屬性記下是哪一項，探測用）：
   - HTTP 錯誤的訊息提到 context（例如 "the input length exceeds the context length"）→ `context_overflow`（`server`）；
   - 沒有 `prompt_eval_count`、或它是 0 → `context_unverified`（`count_missing`）；沒有 `eval_count` 視為 0 個輸出 token（Ollama 省略 0）；
   - **送出的 proxy tokens 超過 `num_ctx`，卻收到回覆** → `context_unverified`（`sent_proxy`）。送出的量 = 訊息文字、tool call 參數、tool 結果與 tool schema
     （`sent_proxy_tokens`；先前回合的 thinking 不算，chat template 可能丟掉它，所以這是 prompt 的下限）。telemetry 的 proxy token 通常低估實際 token
     （decision 011 §5），所以這種回覆不是被截斷，就是無法證明沒有被截斷；
   - **`prompt_eval_count` 少於送出 proxy tokens 的一半**（`COUNT_FLOOR` = 0.5）→ `context_unverified`（`count_floor`）：有一部分 prompt 被丟掉或沒有計入。
     完整的 prompt 預期不會低於這個比例（估計，未實測：telemetry 的實際 / proxy 約 1–1.3（NEXT B），英文約 0.8–1，
     探測的產生文字（每個單字約 6.6 bytes）最壞約 0.6；探測的 `proxy_to_real` 會量到實際值）；
   - `prompt_eval_count + eval_count ≥ num_ctx` → `context_overflow`（`count_at_num_ctx`）；
   - `done_reason` 是 `length` 但輸出少於 `num_predict`（被 context 截斷，不是被輸出上限）→ `context_overflow`（`length_stop`）；
   - `/api/ps` 沒有列出這個模型，或載入的 `context_length` 不等於 `num_ctx`（例如被 Ollama 調整）→ `context_unverified`（`loaded_context`）；
     載入的 digest 不是釘選的 → `pin_mismatch`；
   - 回覆來自遠端模型 → `remote_model`。
   `sent_proxy` 會在實際 token 少於 proxy 的 prompt（大多是英文）上誤報；誤報是大聲失敗、不是靜默截斷。dump-all 的第一次呼叫
   （need 約 13 萬，fit check 保證不超過 `num_ctx`）碰不到它。
3. **失敗的方式**：上面這些 reason 都**不在** `RETRYABLE`（`api_error`、`transport_error`）裡。依現有的契約（023 §5、026 解讀 17、19）：
   - Pilot：`eval run` 停止，CLI 印 `error: …`、exit 2（與 API 錯誤相同，NEXT A1）；
   - held-out：該次嘗試記為 `error`、該 incident 關閉、不再有 prediction，評分時算放棄作答（`no_answer`，留在分母、列出嘗試結果）；執行停止，由人查看。
   - 其他 HTTP 錯誤仍是 `api_error`，呼叫中的連線失敗 / 逾時仍是 `transport_error`（可依 026 解讀 17 重試）。
   - **每個 incident 的釘選檢查在嘗試之外**（`eval/runner.py` 的 `pinned_model`）：held-out 在寫下嘗試的 `start` 之前、Pilot 在每個 incident 之前執行。
     server 連不上、digest 或版本不符時，整個執行停止（ValueError、exit 2），**不寫 start、不用掉任何嘗試**，server 或釘選的模型恢復後續跑即可。
     呼叫中途 server 停掉時：那次嘗試以 `transport_error` 結束（可重試）；下一次嘗試的檢查在它的 start 之前，server 還沒恢復就停止執行，
     第二次嘗試留到續跑時再用。基礎設施故障因此不會關閉 held-out 的 incident。
   - 剩下的情況：**嘗試進行中**模型被換掉（回覆後 `/api/ps` 的 `pin_mismatch`）——那次嘗試確實用了別的模型、輸出不能用，依 026 解讀 17 關閉該 incident。
     heavy lock 與 `tools/with-local-ollama`（§3）下沒有人會在執行中 pull 或換模型，所以只當作最後的防線。
4. **輸出達到 `num_predict`**（`done_reason` = `length` 且輸出 = `num_predict`）不是截斷輸入：照常回傳、`stop_reason` = `max_tokens`，
   與 Anthropic API 的 max_tokens 相同；harness 照 020 §3 處理（沒有提交就要求更正，最後放棄作答）。`num_predict` 記在設定與 `run_config.json`。
5. **執行前的 fit check**（`load_llm_config` → `eval/runner.py` 的 `llm_fit`）：每個方法的 `need` = system 文字 + 送出的 tool schema + 任務說明的保留量
   2,000（合成範例 18 個服務時是 425）+ 該方法的 proxy-token 預算 + 一次回覆（`num_predict`）。dump-all 用 B、Agent 用工具輸出預算；
   `need > num_ctx` → 拒絕執行並列出，**不改任何預算**。`worst_case`（連同每一次回覆與更正都留在對話中）只報告：超過 `num_ctx` 時執行開始前在 stderr 警告。
   retrieval 沒有 proxy-token 預算（q × k 筆加概覽），只靠執行時的防護。proxy token 會低估實際 token（decision 011 §5；NEXT B：可能高 0–30%），
   所以放得下是必要條件、不是充分條件：`num_ctx` 要依探測量到的實際 / proxy 比例留餘裕。

### 3. 釘選與紀錄

1. `model_version` = `/api/tags` 的 manifest digest（`sha256:<64 hex>`）。manifest 以 sha256 指名權重、template、參數與 license 的每一層，
   所以 freeze 的 model / model_version / temperature 檢查（026 解讀 9）釘住的就是完全相同的模型；freeze 另外釘住整個 `llm_methods.json` 的 sha。
2. **Ollama 版本**：使用者同意的提案是「記錄」。程式目前**照助理的提案釘選**（`ollama.version` 必填、不符就拒絕），比提案嚴格，**待使用者確認**
   （見「不在本文件決定」；**2026-10-10 使用者決定釘選**，見文末「使用者決定（2026-10-10）：照建議」第 4 項）：tool call 的 renderer / parser 與 context 的處理都隨 Ollama 版本改變，Pilot 與 held-out 之間 Homebrew 升級會在不知不覺中改變方法；
   代價是 held-out 結束前不能升級 Ollama。使用者若只要記錄：拿掉版本的拒絕，版本仍記在 `run_config.json`（held-out 續跑仍要求相同的 `run_config.json`，
   所以同一次 held-out 執行中途還是不能換版本）。
3. 什麼時候檢查：每次執行開始時（`start_llm`，在開任何 snapshot、寫任何檔案之前）；每個 incident 的每次嘗試開始之前（`pinned_model`，§2.3，
   不在嘗試裡面）；每個回覆之後看 `/api/ps`。另外檢查 `num_ctx` 不超過模型的 context_length、模型回報 tools 能力、think 開時回報 thinking 能力。
4. **整個執行只用開始時讀到的設定**：`start_llm` 讀一次 `llm_methods.json`、驗證並寫進 `run_config.json`；之後每個 incident 的模型與檢查都用同一份設定，
   執行中途設定檔被改（例如在 main checkout 合併別的分支）不影響這次執行。LLM 方法只能經 `run_method` 執行（直接呼叫 `METHODS` 會被拒絕），
   heavy lock 與釘選檢查因此不會被繞過。
5. `run_config.json` 多一個 `llm`：provider、model、model_version（digest）、ollama_version、num_ctx、num_predict、temperature、seed、think。
   held-out 續跑要求完全相同的 `run_config.json`（024、026 解讀 18），換任何一項就是另一次執行而被拒絕。評分表多一行 Model runtime。
6. 本機 provider 必須寫 `price_per_mtok = {input: 0, output: 0}`：`cost_usd` 是 0（明確是本機），不是 null（未知）。
7. seed 必須是正整數（預設 42）：Ollama 的選項結構把 seed 標成 `omitempty`，0 在傳給 runner 的途中可能被當成「沒設」。temperature 0 是 greedy，
   seed 只是記錄。其他取樣參數維持模型的預設（由 digest 釘住；探測記錄 `/api/show` 的 parameters）。
8. **server 與模型只在一次 heavy lock 內存在**（MACHINE_POLICY：在 workload 整個存活期間持有 lock；這個 lock 也是 Rust HNSW 正式 benchmark 用的）：
   - 一律用 `./tools/with-mac-lock ./tools/with-local-ollama <指令>` 執行探測與 `eval run`。`with-local-ollama` 檢查 lock 是這個目錄的 with-mac-lock 持有的；
     127.0.0.1:11434 已經有程式在聽就拒絕（exit 3；不是這次啟動的 server，不使用也不停止它）；以固定的環境
     `OLLAMA_HOST=127.0.0.1:11434 OLLAMA_NUM_PARALLEL=1 OLLAMA_NO_CLOUD=1 ollama serve` 啟動（其他設定用預設）、等 `/api/version` 回應、執行指令，
     不論成功、失敗或中斷都停止 server（模型隨 server 卸載），再交回 exit code；lock 只在這之後才釋放。
   - 另外，每次 `eval run` 與探測結束前都卸載模型（`keep_alive: 0`，`/api/ps` 確認不在了；`agent.ollama.unload`）；確認不了時在 stderr 警告，不改變結果。
   - adapter 看不到 server 的環境變數，所以固定的啟動方式是唯一的保證；手動啟動的 server 不用。
9. **heavy lock**：本機模型的 `eval run` 與探測都要求 Mac heavy lock（與 `collect run` 相同的 `require_heavy_lock`）；拿不到就拒絕，不搶。

### 4. `eval/llm_methods.json`

- （寫定時）仍是 `status: "proposed"`、`model: null`（**2026-10-10 批准**，內容見文末「使用者決定（2026-10-10）：照建議」）；新增欄位：`provider: null`、`model_version: null`、`temperature: 0`、`price_per_mtok: null`、
  `ollama: {url: "http://127.0.0.1:11434", version: null, num_ctx: null, num_predict: 8192（建議值）, seed: 42, think: null, timeout_s: 3600}`；
  `budgets` 不變。
- 批准時（使用者決定之後）填：`provider: "ollama"`、model、model_version、`price_per_mtok` 0、`ollama.version`、`ollama.num_ctx`、`ollama.think`。
  探測輸出一段 `config_if_approved`（只是參考，不會自動寫入）。
- `load_llm_config`：approved 且 provider 是 `ollama` → 檢查所有欄位與 fit，然後用 adapter；其他任何 provider 照舊拒絕（「no model API adapter is installed yet」）。

### 5. 合成範例探測：`python -m eval local-probe`

```text
./tools/with-mac-lock ./tools/with-local-ollama uv run python -m eval local-probe --model <tag> [--num-ctx N] [--think] \
    [--context-sizes 8000,32000,100000] [--out PATH]
```

- **只在合成範例上執行**：沿用 `eval/demo.py` 的 `check_sample`（`synthetic: true`、每個檔案的 sha256 相符、沒有未列出的檔案），incident 必須是範例的 id；
  其他一律拒絕。不讀 label、不評分。
- 拒絕：heavy lock 沒拿到、遠端（cloud）模型、沒有安裝、`num_ctx` 超過模型的 context_length。`--num-ctx` 預設為模型的 context_length，最多 65,536
  （合成範例的 dump-all 約 4 萬 proxy tokens）。
- 用 `llm_methods.json` 建議的設定（預算、temperature、seed、num_predict），price 0；索引快取放在暫存目錄。**不寫 `data/` 下的任何東西**：
  輸出到 stdout 或 `--out`（`--out` 在 `data/` 下就拒絕）。
- 依序：
  1. **防護自我測試**（`num_ctx` 2,048）：一則約 6,000 proxy tokens 的長訊息，以及 4 則各約 1,500 的訊息組成的對話（server 可能在這裡丟掉舊訊息）。
     兩者都必須是 **server 自己**以 context 錯誤拒絕（`guard` = `server`）；只被 adapter 的回覆檢查抓到、或收到回覆，都寫 `GUARD FAILED`：
     這個 Ollama 版本不遵守 `truncate: false`，不要用它跑 LLM 方法。這時報告照樣寫出，CLI **exit 3**（需要人看）。
  2. 三個方法（真正的方法程式），每個方法報告：tool call 是否被解析（`tool_calls_parsed`、解析不了的 `unparsed_tool_calls`、寫成文字的 `text_tool_calls`）、
     是否提交合格的 prediction、更正次數、是否放棄作答、錯誤（含 `guard`）、tokens in / out、latency、cost、每次呼叫的實際 / proxy token 比例與 prefill / decode 時間；
  3. **repeat_check**：同一個 prompt（約 2,000 proxy tokens 的產生文字加一個問題）送兩次：temperature 0 是否得到相同回覆，以及兩次的 `prompt_eval_count`
     是否相同（第二次的 prompt 有快取；只算沒快取的部分時，第二次會被 `count_floor` 擋下或數字不同 → warnings 寫明：防護與 tokens_in 不能依賴它）；
  4. `--context-sizes`：各大小的產生文字（中性的單字，沒有任何 incident 資料）量 prefill 與 decode 的 tok/s；超過 `num_ctx` 的大小略過。
  5. 卸載模型並確認（`unloaded`）。
- 輸出的開頭與結尾都聲明：**不是結果**。也記錄看到的模型 digest、Ollama 版本、能力與預設參數、fit check，以及電力狀態（`power`：唯讀的 `pmset`，decision 025；
  速度取決於它）。
- think：有 thinking 能力的模型要開、關各探測一次，使用者才有兩者的數字可選。

## 不在本文件決定（2026-10-10 使用者決定之後：全部已決定）

寫定時列在這裡、等使用者決定的事項；每一項後面註明 2026-10-10 的決定（文末「使用者決定（2026-10-10）：照建議」）。

- **用哪個模型、`num_ctx`、think**：使用者看過三個模型的探測報告之後決定。
  **→ 已決定**：qwen3.5 9B（`qwen3.5:9b-q4_K_M`）、`num_ctx` 262,144、think 關（第 1–3 項）。
- **預算數值**：不變（B = 120,000、q = 8、k = 25、Agent 40 次 / 120,000 / 30 回合）。選定的模型放不下時，要不要改預算是使用者的決定（另寫 decision log）。
  **→ 不變**：`num_ctx` 262,144 放得下（第 2 項）。
- `llm_methods.json` 維持 `proposed`；三個 LLM 方法在 Pilot 上執行要等使用者同意（提案第 3 步）。
  **→ 已批准**（`approved`）；Pilot 上的執行是下一步（NEXT）。
- `num_predict` 8192 只是建議值，隨模型一起由使用者批准。**→ 維持 8192**（第 6 項）。
- **Ollama 版本是釘選（不符就拒絕）還是只記錄**：§3.2；程式目前釘選，待使用者確認，確認後以補註定案。
  **→ 釘選**（第 4 項；held-out 結束前不升級 Ollama）。
- **電力條件**：本機 LLM 的 Pilot / held-out 執行要不要套用 decision 025 的正式條件（高效能模式 + AC、執行中取樣），以及要不要把電力狀態記進執行紀錄，
  由使用者在 Pilot 執行前決定（latency 是 SPEC §7 要報告的數字，取決於電力模式）。目前只有探測記錄電力狀態；`eval run` 沒有記錄。
  不記進 `run_config.json`：held-out 續跑要求它完全相同，記進去等於多一條使用者還沒定的規則。
  **→ 套用並記錄**（第 5 項）：開始時與每次嘗試之前檢查、前後取樣記在 `power.jsonl`（不在 `run_config.json`），見文末。
- **freeze 是否強制「Pilot 的 LLM 結果用的是凍結的模型」**：目前只是書面規則（見「對實驗的影響」）。freeze 檢查只看 Pilot 的 `scores.json` 存在，
  不比對 Pilot 的 `run_config.json`（model / `llm`）與 `llm_methods.json`；加上這項比對是 freeze 協定（023 §6、026）的變更，不在本文件做，待使用者決定。
  **→ 強制**（第 7 項）：decision 026 修訂 3（解讀 31、32），同時加上「目前 env lock 有通過的 soak」。

## 為什麼

- 使用者決定先試本機模型：沒有外部費用，又能讓已寫好的 harness 實際跑起來；付費 API 仍可換回。
- Ollama 的預設行為會在不報錯的情況下丟掉資料，方法的結果就會取決於看不見的截斷；與 A1 的「預算與可見資料必須明確」（SPEC §7、024）矛盾。
  寧可大聲失敗、讓使用者調 `num_ctx` 或決定預算，也不讓 context 變成一個沒有報告的隱藏預算。
- 截斷用 `CallError` 而不是 harness 的「放棄作答」：回合與工具預算是方法設計的一部分（020、021），context 是所選模型與執行環境的性質；
  把它變成方法自己的放棄作答，等於多一個沒有登錄的預算。現有契約已規定不可重試的錯誤怎麼處理（Pilot 停止、held-out 關閉該 incident），不必新增規則。
  不可重試：temperature 0、同一個請求，再送一次一樣會超過。
- 回覆檢查不只依賴 `truncate: false`：它是 Ollama 的行為，沒有在這台機器上驗證過；`sent_proxy` 與 `count_floor` 只用 adapter 自己知道的量，
  server 不管怎麼截斷都抓得到大部分的情況；探測的自我測試再確認 server 本身。
- 釘選檢查放在嘗試之外：026 解讀 17 的重試只看呼叫的停止原因；嘗試開始之前就知道「server 不在」或「模型不對」時，用掉一次 held-out 嘗試、
  甚至關閉 incident，等於把基礎設施故障算成方法答錯。
- 釘 digest：manifest digest 同時釘住權重、template 與參數，freeze 的「模型、版本」才完整。Ollama 版本見 §3.2。
- 先在合成範例上探測：選模型只依 tool calling、防護與速度，不看任何 Pilot 結果，避免用 Pilot 的成績挑模型；也符合「Pilot 等使用者同意」的順序。

## 放棄的替代方案

- **用 Ollama 的預設 context（或 `OLLAMA_CONTEXT_LENGTH`）**：預設值小，長 prompt 會被靜默截斷。
- **送出前先算 token 數**：Ollama 的 API 沒有公開的 tokenize；proxy 估計不精確。伺服器端的 `truncate: false` 加上回覆後的檢查（包括以 proxy 為下限的兩項）。
- **只靠 `truncate: false`**：沒有在這台機器上驗證過；server 若仍丟掉舊訊息，剩下的 prompt 可能遠低於 `num_ctx`，只看 `num_ctx` 的檢查抓不到。
- **context 超過時當成 harness 的停止（放棄作答）**：見「為什麼」。
- **context 超過時重試**：結果一樣，只是浪費時間（held-out 還會用掉一次嘗試）。
- **在嘗試裡面做每個 incident 的釘選檢查**：server 暫時不在就會關閉 held-out 的 incident（審查發現的問題），見 §2.3。
- **解析不了的參數當成空物件**：空的 `submit_diagnosis` 是合格的放棄作答，等於把格式錯誤算成放棄作答、跳過 020 §3 的更正（審查發現的問題）。
- **OpenAI 相容的 `/v1/chat/completions`**：沒有 `truncate` / `shift` 的控制；`/api/chat` 有，`/api/ps` 也能確認實際載入的 context。
- **`ollama` Python 套件**：多一個依賴；標準函式庫就夠。
- **在 Pilot incident 上探測**：違反提案的順序（Pilot 等使用者同意），也會用 Pilot 挑模型。
- **自動縮小預算以放進 context**：預算是使用者的決定（020、021），而且三個方法必須公平（021 §4）。
- **在 lock 外啟動 `ollama serve`、各探測各包一次 lock**：server 與模型（含 `num_ctx` 的 KV cache）在 lock 釋放後仍占著記憶體，別的 heavy workload 會拿到 lock。

## 對實驗的影響

- **結論縮小到所選的本機模型**（q4_K_M 量化、該 Ollama 版本、`num_ctx`、think 設定）：SPEC 的「LLM Agent 能不能…」只能以這個模型回答，報告與 README 必須寫明。
  三個 LLM 方法用同一個模型（021 §4 不變）。
- **freeze 只釘一個模型，held-out 每個（方法, incident）只跑一次**（023 §5、§6；026 解讀 9、17、18）：日後換回付費模型，必須在 **freeze 之前**用那個模型
  重跑 Pilot 的三個 LLM 方法（以及補 evidence gold，decision 017），held-out 不能混用兩個模型；freeze 之後換模型是設計變更（023 §6），不允許。
  換回時需要另寫 decision、加付費 API 的 adapter，並在第一次呼叫前依 MACHINE_POLICY 報告成本。
  **這一條目前沒有程式強制**（見「不在本文件決定」）：freeze 之前要由人比對三個 LLM 方法 Pilot 的 `run_config.json`（`model`、`llm`）與 `llm_methods.json`。
  （2026-10-10 使用者決定之後由程式強制：freeze 比對每個 LLM 方法 Pilot 的 `run_config.json` 與要凍結的 `llm_methods.json`，026 解讀 32。）
- **context 放不下 dump-all 預算的模型不能原樣執行 dump-all**（Agent 的工具輸出預算也一樣；例如 qwen3:8b 的 40,960 遠小於約 13 萬 proxy tokens 的 need）：
  fit check 拒絕；改預算是使用者的決定。
- 本機運算沒有外部費用（`cost_usd` = 0），但有時間成本：探測的速度量測用來估計 Pilot 的執行時間；多小時的執行是 heavy workload，透過 `with-mac-lock` 與 `with-local-ollama`。
- latency 是這台 Mac 的本機數字，與付費 API 不可比，也取決於電力模式；照實報告並標明（SPEC §7）。
- `tokens_in` / `tokens_out` 是模型自己 tokenizer 的數字，與 proxy token 不同單位；兩者照 024 分開報告。
- 合成範例的探測**不是結果**，不進 README 的結果表，也不用來調整任何方法、prompt 或預算。

## 測試

- `tests/test_ollama.py`（訊息與工具的轉換、可重現的 id、參數的各種形狀與 harness / submit_round 的拒收、請求的選項、每一種截斷 / 無法確認的情況與它的 `guard`、
  送出量的計算、API 與傳輸錯誤、只接受 loopback、釘選、卸載、綁在 127.0.0.1 的 stub HTTP server、harness 在 adapter 上跑完且 cost 為 0）、
  `tests/test_local_llm.py`（committed 設定仍是 proposed 且預算不變、approved 的每個必填欄位、其他 provider 仍沒有 adapter、fit check、Pilot 與 held-out 的
  `run_config.json`、digest 不符或沒有 lock 時什麼都不寫、執行中途換模型就停止、只能經 `run_method` 執行、執行中途改設定檔不影響、
  held-out 嘗試前 server 不在或模型被換時不用掉嘗試、呼叫中途 server 停掉時第二次嘗試留到續跑、執行結束時卸載模型）、
  `tests/test_local_probe.py`（只在合成範例、報告內容、兩種防護自我測試與 GUARD FAILED 時 exit 3、解析不了的參數與快取 prompt 的計數、拒絕的情況、CLI、不寫 `data/`）、
  `tests/test_with_local_ollama.py`（假的 `ollama` 執行檔在測試內綁 loopback：固定的環境、交回 exit code、一定停止 server、沒有 lock 或 port 已被占用時什麼都不啟動）。
  全部用腳本化的 transport 或測試內綁在 loopback 的 stub server，**從不連到真正的 Ollama**。

## 探測結果（2026-10-10，只用合成範例；**不是結果**）

三個模型各一次 heavy lock（`with-local-ollama`，server 只在 lock 內存在），高效能模式 + AC，Ollama 0.35.0，think 關、temperature 0、seed 42、num_predict 8192。
報告存在 session 的暫存目錄（不進 git、不寫 `data/`）。合成範例很小、fault 很明顯，下面的數字只說明工具呼叫能不能用、防護是否成立、速度多少。

| | qwen3 8B（num_ctx 40,960） | qwen3.5 9B（num_ctx 196,608） | gemma4 12B（num_ctx 196,608） |
|---|---|---|---|
| 防護自我測試 | 通過（兩項都是 server 自己拒絕） | 通過 | 通過 |
| 同一 prompt 兩次 | 相同、prompt_eval_count 相同 | 相同 | 相同 |
| Agent | 合格答案，9 次呼叫，94 s | 合格答案，15 次呼叫、用了 8 種工具，180 s | 30 回合上限，沒有提交（多數回覆是文字、沒有呼叫工具） |
| dump-all | server 拒絕：63,148 tokens > 40,960（context_overflow） | 三次提交都被判格式不合格（見下） | 輸出 8,192 tokens 文字、沒有提交 |
| retrieval | 沒有提交 | 三次提交都被判格式不合格（見下） | 沒有提交 |
| prefill（8k → 130k proxy） | 300 → 209 tok/s（只測到 24k） | 330 → 166 tok/s | 208 → 114 tok/s |
| decode | 40 → 28 tok/s | 39 → 23 tok/s | 29 → 17 tok/s |
| 探測總時間 | 9 分鐘 | 36 分鐘 | 70 分鐘 |

- **qwen3.5 的不合格提交是 harness 的缺陷**：它把 `evidence` 寫成 id 字串清單，harness 回的是 Python 例外訊息，模型三次送出相同答案。
  已修正更正訊息（decision 020「修正（2026-10-10）」，格式不變、沒有放寬）。修正後重跑同一個診斷：dump-all 與 retrieval 都在一次更正後提交合格答案。
  三個模型的探測報告都是修正之前跑的；Agent 本來就用物件格式，不受影響。
- **實際 tokens / proxy tokens**：telemetry 文字約 1.6–1.8（dump-all 1.62–1.76、retrieval 1.61–1.80、Agent 0.86–1.68），產生的填充文字約 1.0。
  §4 的 fit check 以 proxy tokens 比 num_ctx，所以 qwen3.5 在 196,608 時顯示「放得下」，但 dump-all 填滿 120,000 proxy 預算時實際約 19.5–21 萬 tokens，
  加上任務說明與輸出會超過 196,608，server 會拒絕（不會靜默截斷，但整個 Pilot 執行會停下來）。用 dump-all 的現行預算時，num_ctx 要接近模型上限 262,144。
- gemma4 與 qwen3 的「沒有提交」沒有進一步診斷（gemma4 也可能是 Ollama 對它的工具呼叫處理）。qwen3 8B 的 context 放不下 dump-all 與 Agent 的預算。
- think 開沒有測。

## 使用者決定（2026-10-10）：照建議

- 使用者原話：「照建議」。一次同意助理看完探測結果（上一節；harness 的修正見 decision 020「修正（2026-10-10）」）之後提出的八項建議，
  時間在任何 Pilot 上的 LLM 執行、任何 held-out 資料與 freeze 之前。只記錄這八項，不延伸到其他規則、指標、切分、門檻或預算。
- 依據只有合成範例的探測（tool calling、防護、速度），沒有看任何 Pilot 資料或結果（本文件「為什麼」最後一項）。

| # | 建議（使用者同意的原內容） | 落地 |
|---|---|---|
| 1 | 模型 qwen3.5 9B：Ollama tag `qwen3.5:9b-q4_K_M`，digest `sha256:6488c96fa5faab64bb65cbd30d4289e20e6130ef535a93ef9a49f42eda893ea7`（探測看到的），Ollama 0.35.0；GGUF context_length 262,144，capabilities completion / vision / tools / thinking | `eval/llm_methods.json`：`status: "approved"`、`provider: "ollama"`、`model`、`model_version`（完整 digest）、`temperature` 0、`price_per_mtok` `{input: 0, output: 0}`、`ollama.version` `"0.35.0"`；`note` 記下批准（誰、何時、原話、本節） |
| 2 | `num_ctx` = 262,144（模型上限），dump-all 的預算維持 120,000 proxy tokens（telemetry 的實際 token 約是 proxy 的 1.6–1.8 倍；196,608 會讓 server 在執行中途拒絕 dump-all）；預算不變 | `ollama.num_ctx: 262144`；`budgets` 逐項不變（fit check：dump-all 與 Agent 的 need 都在 262,144 以內） |
| 3 | think 關 | `ollama.think: false` |
| 4 | Ollama 版本**釘選**（不符就拒絕；held-out 結束前不升級 Ollama） | 程式本來就是這個行為（§3.2，`pin_problems`）；現在是使用者的決定，不再只是助理的提案。Homebrew 的自動升級也要避免，直到 held-out 評測結束 |
| 5 | 電力：LLM 方法的執行也要求高效能模式 + AC（025 修訂 3 的 `FORMAL_POWER`、`collect.provenance.power_problems`），並記錄電力狀態（latency 要報告） | 見下面「電力條件的實作」 |
| 6 | `num_predict` 8192 維持 | `ollama.num_predict: 8192` |
| 7 | freeze 的檢查寫進程式（只會更嚴格）：(a) `collect heldout-freeze` 要求目前 env lock 有通過的 soak（`collect.live.passing_soak`，與收集 preflight 同一條規則；028「必須在 held-out freeze 之前」）；(b) 每個 LLM 方法的 Pilot 結果用的正好是凍結的 LLM 設定（Pilot `run_config.json` 的 `llm` 等於 `llm_methods.json` 規定的 provider、model、digest、Ollama 版本、num_ctx、num_predict、temperature、seed、think，預算也相同） | `collect/freeze.py` 的 `write_freeze`、`eval/runner.py` 的 `pilot_llm_problems`、`agent/ollama.py` 的 `pinned_record`；decision 026 修訂 3（解讀 31、32）；023「使用者決定」的「追加（2026-10-10，第三次）」 |
| 8 | grafana 的背景 plugin 安裝器維持現狀 | 不實作；記在 028「結果」與 NEXT A0 |

### `timeout_s`：維持提案的 3600（設定檔的值，不是預算；不在八項之內）

- `ollama.timeout_s` 是 adapter 的 socket timeout（`http.client`）。`stream: false` 時 Ollama 在整個回覆完成之前不送任何資料，所以它實際上限制
  一次呼叫的總時間。它不影響方法看到什麼，只決定「server 沒有回應」要等多久才算 `transport_error`。
- 使用者同意的是八項建議；`timeout_s` 不在其中，維持提案設定檔的 3600。實作時曾依下面的估計改成 7,200，審查（2026-10-10）指出：
  這不在使用者同意的範圍內，估計也沒有超過 3,600（改值的前提），所以改回 3,600。**要不要加長是使用者的決定**。
- **估計**（探測的 qwen3.5 速度：`num_ctx` 196,608、think 關、高效能模式 + AC；四個 prefill 大小 8,147 / 32,647 / 101,950 / 132,721 個實際 tokens
  → 329.5 / 286.2 / 185.5 / 165.6 tok/s）：每個 token 的平均 prefill 時間隨長度大致線性增加（1/速度 ≈ a + b·n，相鄰兩點的 b 是 1.9–2.7 × 10⁻⁸ 秒），
  取最陡的 b 從 132,721 往上外插：
  - 230,000 tokens（dump-all 用滿 120,000 proxy 時約 19.5–21 萬實際 tokens，加上 system、任務說明與 tool schema）：prefill 約 2,000 秒（33 分鐘）；
  - 最長可能的 prompt（262,144 − 8,192 = 253,952）：prefill 約 2,380 秒（40 分鐘）；
  - 輸出用滿 `num_predict` 8,192：decode 從 39 tok/s（8k）降到約 23 tok/s（13 萬），外插到 25 萬約 13.5 tok/s → 約 600 秒（10 分鐘）。
  - 合計：約 23 萬 tokens 的 dump-all 呼叫約 2,000–2,600 秒（3,600 的 56–72%）；最壞（最長 prompt 加上用滿輸出）約 3,000 秒（83%）。
    都低於 3,600，但這是外插到量測範圍的約 2 倍，262,144 沒有實測過。
- **超時的代價不對稱**：Pilot 上整個執行停止（`transport_error`，exit 2）、要重跑；held-out 上是可重試的 `transport_error`，第二次嘗試多半同樣超時
  → 該 incident 關閉、算放棄作答（026 解讀 17、19）。加長等待只會讓真的卡住的 server 晚一點被發現。
- **之後怎麼確認**：Pilot 的 dump-all 會量到接近滿 context 的實際 latency（評分表的 `latency_s` max；dump-all 每個 incident 主要是一次呼叫）。
  若最長的呼叫接近 3,600，或 Pilot 上有呼叫逾時，回報使用者決定要不要加長。Pilot 的 `run_config.json` 不記 `timeout_s`（026 解讀 32 也不比對它），
  所以 freeze 之前改它不需要重跑 Pilot；但 freeze 以 `llm.config_sha256` 釘住整個 `llm_methods.json`，**freeze 之後就不能改**。

### 電力條件的實作（第 5 項）

- **範圍**：只對本機模型的執行（provider `ollama`；與 heavy lock、釘選檢查相同）。統計 baseline 不變。換回付費 API 時另寫 decision。
- **檢查**（`eval/runner.py` 的 `formal_power`，唯讀的 `pmset`，`collect.provenance.power_facts` / `power_problems`）：
  - 執行開始時（`start_llm`：heavy lock 之後、釘選檢查之前；開任何 snapshot、寫任何檔案之前）；
  - 每個 incident 的每次嘗試之前，與釘選檢查在同一個位置：Pilot 在每個 incident 之前，held-out 在寫下嘗試的 `start` **之前**。
  - 不符（不是 AC、`powermode` 不是 2、`lowpowermode` 不是 0、讀不到 `pmset`）→ 整個執行停止（ValueError，CLI 印 `error: …`、exit 2），
    **該 incident 什麼都不寫、不用掉 held-out 嘗試**；電力恢復之後續跑即可（與釘選檢查相同，§2.3）。
- **紀錄**：每次嘗試結束後（held-out 在嘗試的 `end` 事件之後；Pilot 在 prediction 寫出之後）再讀一次，連同之前的樣本附加一行到
  `results/<set>/<method>/power.jsonl`（只附加、fsync）：`{incident_id, attempt（Pilot 為 null）, run_config_sha256, before, after, formal, problems}`。
  `run_config_sha256` 是這次執行的 `run_config.json` 寫出（held-out：驗證）之後的 sha256（審查 2026-10-10）：Pilot 上用來判斷每個 prediction 是哪一次執行寫的，
  freeze 拒絕中途停止留下的舊 prediction（026 解讀 32）。
  **不寫進** `run_config.json`（held-out 續跑要求它完全相同），也**不寫進** prediction（decision 013 的格式不變）。
- **之後的樣本不符**：執行在這裡停止（ValueError、exit 2）。這次嘗試產生的東西照常保留（prediction、transcript、嘗試紀錄的 `ok`），
  `power.jsonl` 的那一行是 `formal: false`。temperature 0 的輸出不取決於電力，只有 latency 會受影響，所以**只報告、不丟棄**；
  held-out 的 incident 已有 prediction，永不重跑（023 §5）。
  - 嘗試以不可重試的錯誤或不合格的 prediction 結束時，照樣先寫那一行，原本的錯誤照常停止執行（不被電力的訊息蓋掉）；
  - 可重試的錯誤（`api_error` / `transport_error`）之後樣本不符：執行停止，第二次嘗試留到續跑（續跑時嘗試之前的檢查照常）。
- **報告**（024 的「Budgets, usage and visible data」）：`eval score` 在 scores.json 的 `usage.latency_power`
  （`{condition, incidents_timed, not_formal: [{incident_id, attempt, reason}]}`）與 table.md 列出 latency 不是在正式條件下量測的 incident：
  每個有 latency 的 incident 看它在 `power.jsonl` 的最後一行（held-out 就是產生 prediction 的那次嘗試；Pilot 是最近一次執行），
  `formal` 不是 true、或沒有任何一行，都列出。usage 的數字**不剔除**它們（只報告）。都符合時表上寫一句「全部在 AC、高效能模式下量測」。
  held-out 另列失敗的嘗試（審查 2026-10-10）：報告的「Failed attempts」加總了失敗嘗試的 latency，所以有 latency 的失敗嘗試，它自己那一行
  （同一個 incident 與 attempt）的 `formal` 不是 true 或沒有那一行時，列在 `usage.latency_power.failed_not_formal`（`[{incident_id, attempt, reason}]`），
  table.md 在「Failed attempts」那一行之後列出；同樣不剔除。Pilot 沒有嘗試紀錄，沒有這個欄位。
  統計 baseline 與沒有本機模型的執行：`latency_power` 為 null，表上不出現。
- **限制**：只在每次嘗試的前後（與執行開始時）取樣，不像收集時每分鐘取樣；呼叫中途切換又切回不會被發現。Pilot 的執行中途停止時，
  `power.jsonl` 會留下前一次執行的行；評分只看每個 incident 的最後一行，與它目前的 prediction 對應（Pilot 重跑會重寫所有 prediction）。
  這種中途停止的 Pilot 目錄（新的 `run_config.json` 加上前一次執行的部分 prediction）由 freeze 以 `run_config_sha256` 拒絕（026 解讀 32），
  所以中途停止的執行要重跑到 exit 0 再評分。

### 測試（使用者決定之後新增或修改）

- `tests/test_local_llm.py`：committed 設定就是使用者批准的值（預算不變，`load_llm_config` 通過、不需要 server）；committed 設定在沒有 heavy lock 時
  三個方法都拒絕、什麼都不寫、不讀電力也不連 server（`eval run --method retrieval --set pilot` 在 lock 外的行為）；開始時電力不符就不開始
  （連釘選檢查都沒做）；Pilot 與 held-out 在嘗試之前電力不符就停止、不用掉嘗試；之後的樣本不符就停止、結果保留、評分列出；
  可重試的錯誤之後不符、第二次嘗試留到續跑；沒有樣本的 incident 也列出；統計 baseline 沒有這條規則。電力一律以 monkeypatch 給定，**從不執行真的 `pmset`**。
- `tests/test_local_llm.py`（審查 2026-10-10）：committed 設定的 `timeout_s` 是 3600、note 不寫 7200；held-out 嘗試以不可重試的 `CallError`
  （`context_overflow`）或不合格的 prediction 結束、之後的樣本不符時：raise 的是原本的錯誤、`power.jsonl` 有該嘗試的一行且 `formal` 為 false、
  ledger 是 `error` / `invalid_prediction`、incident 已關閉；可重試的錯誤之後不符時，失敗嘗試列在 `failed_not_formal` 與表上（正式條件下不列）；
  用別的設定跑完、再用凍結的設定在中途停止並評分 → freeze 的檢查只列沒重跑到的 incident，重跑到結束後通過，每一行的 `run_config_sha256` 正確。
- `tests/test_ollama.py`：`pinned_record` 等於釘選檢查通過後一次執行寫的 `run_record`。
- `tests/test_heldout_freeze.py`、`tests/test_collect_cli.py`：見 026 修訂 3。
- `tests/test_eval_runner.py`、`tests/test_eval_heldout.py`：原本以「committed 設定是 proposed」測試的拒絕，改用測試內寫的 proposed 設定；
  另測 committed 設定在 held-out 上也在 heavy lock 拒絕。

## 修訂 1（2026-10-11，使用者決定）：推論改在 RTX 5070 Ti

- 使用者原話：「不然就先停吧 我沒有更高瓦數的usec 還是說你要去5070ti上跑？」；助理提出下面的計畫，使用者回答「同意」。
  時間：Pilot 上的 retrieval 與 agent 已在 Mac 跑完並評分（2026-10-10/11），dump-all 的重跑停在 5/10；任何 held-out 資料與 freeze 之前。
- 只改「模型在哪裡推論」與跟著它的執行條件（wrapper、heavy lock、電力 → GPU 狀態的紀錄）。模型、digest、Ollama 版本、`num_ctx`、`num_predict`、
  temperature、seed、think、`timeout_s`、price、預算、指標、切分、門檻、評分都不變。

### 背景

- Mac（M4 Pro）在高效能模式下跑本機模型，耗電超過 70 W 的充電器：2026-10-11 dump-all 的重跑（08:07 起）接著 AC 電池仍每小時約掉 17–18%，
  跑完前會沒電，使用者在 10:38 停止（做完 5/10；中途停止的 Pilot 執行不評分）。029「照建議」第 5 項的電力條件（高效能 + AC）因此無法在整個執行中維持。
- held-out（每個 fault 5 個，約 50 個 incident × 三個方法）依 Pilot 的速度估計需要約 35–50 小時的 Mac 重負載，在 70 W 下不可行；使用者沒有更高瓦數的充電器。
- 使用者有一台 RTX 5070 Ti 桌機（16 GB VRAM；Windows 11 + OpenSSH，預設 shell 是 cmd；WSL Ubuntu-22.04），已設定好 alias `ssh gpu-server`；
  使用者的其他 project 在 WSL 裡以 `flock -n /tmp/ai-portfolio-gpu.lock` 共用 GPU。

### 決策

1. **推論主機是設定的一部分**：`eval/llm_methods.json` 新增 `ollama.host`，值只能是 `"local"`（這台 Mac：`with-mac-lock` + `with-local-ollama`，
   本文件原本的規則）或 `"gpu-server"`（`tools/with-remote-ollama`）；其他值或沒有這個欄位，`load_llm_config` 拒絕。committed 設定改為 `"gpu-server"`，
   其他欄位逐項不變（`approved`、`qwen3.5:9b-q4_K_M`、digest `sha256:6488c96f…3ea7`、Ollama 0.35.0、`num_ctx` 262,144、`num_predict` 8192、seed 42、
   think 關、temperature 0、price 0、`timeout_s` 3600、預算），`note` 補一句本修訂。
2. **只有模型呼叫在桌機上**：eval 迴圈仍在 Mac 執行；snapshot、ground truth、評分與結果都不離開 Mac（ground truth 的隔離不變）。模型呼叫經 SSH 的本機轉送：
   Mac `127.0.0.1:11434` → gpu-server `127.0.0.1:11434`（WSL2 的 localhost 轉送把 WSL 的 `127.0.0.1:11434` 開在 Windows 的 localhost）。
   adapter 的「只連 loopback」規則與它的檢查都不變（仍連 `127.0.0.1`）。**照實說明**：在這個 wrapper 之下，那個 loopback 端點是一條通到使用者自己
   GPU 桌機的 tunnel，不是這台 Mac 上的 server；它不是付費或第三方服務（MACHINE_POLICY「外部費用」：既有的本地硬體），拒絕 cloud 模型的檢查也照舊。
3. **桌機上的安裝**（主 session 做，WSL 使用者的 home、不需要 sudo）：Ollama 0.35.0 在 `~/opt/ollama-0.35.0`（執行檔 `~/opt/ollama-0.35.0/bin/ollama`），
   只給本 project 的 models 目錄 `~/ii-ollama-models`（從 Mac 複製 `qwen3.5:9b-q4_K_M` 的 manifest 與 blob，digest 同上）。兩個路徑只定義在
   `tools/with-remote-ollama` 的開頭（只供測試覆寫，且只接受安全的字元）。版本與 digest 照舊由每次執行的釘選檢查經 API 確認。
4. **`tools/with-remote-ollama`**（對照 `with-local-ollama`）：
   - 本機 `127.0.0.1:11434` 已有程式在聽 → exit 3，不聯絡 gpu-server。
   - 一個背景的 ssh session（`-L 127.0.0.1:11434:127.0.0.1:11434`、`ExitOnForwardFailure=yes`、`BatchMode=yes`、`ServerAliveInterval=30`、
     `ControlPath=none`）同時在遠端執行
     `wsl.exe -d Ubuntu-22.04 -- bash -lc "exec flock -n -E 75 /tmp/ai-portfolio-gpu.lock bash -c '…'"`，lock 內：遠端 `127.0.0.1:11434` 已有程式在聽
     → exit 3（不是這次啟動的，不使用也不停止它）；否則印出啟動標記，再
     `exec env OLLAMA_HOST=127.0.0.1:11434 OLLAMA_NUM_PARALLEL=1 OLLAMA_NO_CLOUD=1 OLLAMA_MODELS=$HOME/ii-ollama-models $HOME/opt/ollama-0.35.0/bin/ollama serve`。
   - GPU lock 被占用 → **exit 75**（與 with-mac-lock 同義），什麼都不執行、不等、不搶、不刪 lock。`-E 75` 是為了區分：flock 預設的 1 會和 server 自己的失敗混在一起。
     ssh 本身失敗（255：離線、無法連線、本機轉送失敗）→ exit 3，LLM 的步驟標記 blocked。server 在 120 秒內沒有經 tunnel 回應 `/api/version` → exit 3。
   - 回應之後以 `II_INFERENCE_HOST=gpu-server` 與 `II_INFERENCE_TUNNEL_PID`（本機 ssh 的 pid）執行指令。
   - **結束（任何 exit 或 signal）**：只停止這次啟動的 server——只在這次 session 印出啟動標記（已取得 lock、遠端 port 空著、即將啟動）之後，
     遠端 `pkill -TERM -x -f $HOME/opt/ollama-0.35.0/bin/ollama.serve`（`-x -f`：整個命令列完全等於「`<binary> serve`」；樣式裡的空白寫成 `.`），
     等它結束（最多 30 秒，之後 KILL），GPU lock 隨它釋放；然後結束本機的 ssh，印出 serve 的 log 在哪裡（ssh session 的輸出，存在 Mac 的暫存檔）。
     無法確認已停止（例如桌機在執行中離線）→ 印出在 gpu-server 上檢查的指令、exit 3（指令本身失敗時保留它的 exit code）；絕不刪 lock。
     signal 送到整個 process group（本機 ssh 也被停止）時也照樣停止遠端 server。
   - 「完整命令列 `<binary> serve` 就是這次的 server」的根據：這個路徑的執行檔只為本 project 安裝、只由這個 wrapper 啟動、只在 GPU lock 內（一次一個）；
     沒有印出啟動標記（例如 lock 被占用）時什麼都不停止，所以別人留下的 server（包括同一路徑、被殺掉的 wrapper 留下的）不會被碰。剩下的情況：
     這次的 server 在執行中自己結束、而另一個 wrapper 恰好在這之間於同一台 Mac 啟動並取得 lock——tunnel 還在時第二個 wrapper 會在本機 11434 被拒絕，
     主 session 也一次只跑一個方法。
   - 遠端命令只用 `$HOME` 一個變數，不含 cmd.exe 會解讀的字元（`"`、`%`、`^`、`!`）：不論 wsl.exe 是否先經過預設的 Linux shell，結果都相同。
     停止之前先確認遠端有 `pkill` / `pgrep`（沒有就算無法確認，不會誤報已停止）。
   - **不需要 Mac heavy lock**：這種執行中 Mac 只跑輕量的 eval 迴圈（讀 snapshot、組 prompt、Agent 工具的 sqlite 查詢、寫結果），重的推論在桌機上、
     由 GPU lock 保護。量到的 latency 由桌機的推論主導，Mac 上其他 heavy workload 不會明顯影響它，這個迴圈也不會干擾它們。
5. **Runner 與探測**（`eval/runner.py`、`eval/probe.py`，新增 `eval/inference_host.py`）：
   - host `gpu-server`：要求在 wrapper 之下（`II_INFERENCE_HOST=gpu-server`，且 `II_INFERENCE_TUNNEL_PID` 是活著的程序：殘留在 shell 的變數會指向已結束的 pid），
     **取代** Mac heavy lock；不符就在開任何 snapshot、寫任何檔案、讀 GPU 或連 server 之前拒絕（CLI exit 2），訊息給出 wrapper 的指令。
     host `local`：完全不變（heavy lock、`with-local-ollama`、電力條件；wrapper 的變數不能代替 heavy lock）。
   - `run_config.json` 的 `llm` 多 `host`（`agent.ollama.run_record` / `pinned_record`）。所以 freeze 的「Pilot 用的正好是凍結的設定」（026 修訂 3、解讀 32）
     **自動要求 Pilot 在同一台主機上執行**；Mac 與桌機的執行 `run_config.json` 的 sha 也不同，中途停止留下的混合目錄照樣被拒絕。
   - `python -m eval local-probe` 新增 `--host {local,gpu-server}`，預設是設定的 `ollama.host`；`gpu-server` 的要求與 runner 相同。報告多 `host`；
     `gpu-server` 記錄 `gpu`（下面的 GPU 狀態）取代 `power`；GPU 讀不到或不是 RTX 5070 Ti 時寫進 warnings（探測只記錄、不停止）。
6. **電力條件改成適用推論主機**（使用者同意的內容：「電力條件改成適用推論主機：桌機接市電，改為記錄 GPU 的狀態（型號、驅動、功耗上限），
   不再檢查 Mac 的電力模式」；對 host `gpu-server` 取代「照建議」第 5 項，host `local` 的規則逐字不變）：
   - host `gpu-server` **不檢查、也不讀** Mac 的電力模式。
   - **GPU 狀態**：一次唯讀的
     `ssh gpu-server 'wsl.exe -d Ubuntu-22.04 -- nvidia-smi --query-gpu=name,driver_version,power.limit,power.draw,clocks.sm,temperature.gpu,memory.used --format=csv,noheader'`
     （`BatchMode`、連線逾時 20 秒、整體逾時 60 秒；只用使用者的 alias）。數值記成數字（`[N/A]` 記 null），也保留原始那一行；
     讀不到（ssh 或 nvidia-smi 失敗、逾時、輸出不是查詢的 7 個欄位）整個樣本記為 `null`，不猜。
   - 取樣的時間點與 Mac 的電力檢查相同：執行開始時、每個 incident 的每次嘗試之前（釘選檢查之後）與之後。
   - **停止的規則（完整）**：只有兩種情況停止——(a) 讀到的 GPU 名稱不含 `RTX 5070 Ti`；(b) **連續兩個樣本讀不到**（依取樣的順序：執行開始、每次嘗試之前、之後；
     讀到一次就重新計數）。停在哪裡：執行開始時 → 不開始（什麼都不寫、不做釘選檢查）；嘗試之前 → 停在嘗試之前（該 incident 什麼都不寫、不用掉 held-out 嘗試）；
     嘗試之後 → 那一行照寫、嘗試產生的東西保留，執行在下一個 incident 之前停止（held-out：有 prediction 的 incident 永不重跑，023 §5）。
     只有一個樣本讀不到：記為 null，執行繼續（表上列出）。功耗上限、驅動、clock、溫度都只記錄、不檢查。
   - **紀錄**：同一個 sidecar `results/<set>/<method>/power.jsonl`（只附加、fsync、`run_config_sha256` 照舊），一種格式、多一個 `host` 欄位（Mac 的行也寫
     `host: "local"`）：`{incident_id, attempt, run_config_sha256, host, before, after, formal, problems}`；`gpu-server` 的 `before` / `after` 是
     `{at, gpu}`（Mac 是 `{at, power}`）；`formal` = 之前與之後的樣本都讀到、而且是 RTX 5070 Ti；`problems` 前面標 `before:` / `after:`。
     仍然不寫進 `run_config.json` 或 prediction。
   - **評分**（024 的「Budgets, usage and visible data」）：`usage.latency_power` 多 `host`，`condition` 依主機；`gpu-server` 另有 `gpus`
     （計時的 incident 的樣本中看到的 GPU 名稱、驅動、功耗上限）。latency 不在條件下量測的 incident 照舊列出、不剔除（`gpu-server`：
     「NOT measured with a readable RTX 5070 Ti state before and after the incident」；最後一行是別的主機取樣的也列出）；都符合時寫
     「Inference host: gpu-server … the Mac's power mode is not a condition of this run」，再列 GPU（名稱、驅動、功耗上限；中途改變時全部列出）。
     「Model runtime」一行寫推論主機：本機照舊是「a local model on this Mac」，桌機是「the user's own RTX 5070 Ti desktop, reached through an SSH tunnel」。
     「AC power in the high power mode」的字句只出現在 host `local` 的表，held-out 失敗嘗試的那一行也依主機。

### 為什麼

- 使用者沒有更高瓦數的充電器；Mac 推論在 70 W 下維持不了 029 的電力條件，held-out 的約 35–50 小時也不可行。桌機接市電、有獨立的 GPU。
- 只移模型呼叫：snapshot 與 ground truth 留在 Mac，「Agent 只讀 frozen snapshot」與 ground truth 的物理隔離完全不變；桌機上只有模型與 Ollama，
  不落地任何 incident 資料（請求的內容只在推論時經過）。
- tunnel 讓 adapter 的 loopback 規則、截斷防護、釘選檢查都不必改：它看到的仍是同一版本、同一 digest 的 Ollama API。
- GPU lock 沿用使用者其他 project 的慣例，與它們公平共用 GPU；`flock -n` 不等待，一個長時間的執行不會卡住別人，也不會被卡住。
- 電力 → GPU 狀態：桌機接市電，沒有電池或低耗電模式的問題；速度取決於 GPU 的型號、驅動與功耗上限，所以記錄它們，讓 latency 可以解讀。
  停止規則只擋兩件事：跑在錯的 GPU 上（結果與 latency 不可比），以及一直看不到狀態（ssh 或 GPU 有問題）；單一次讀取失敗多半是暫時的網路問題，
  不值得讓數小時的執行停下，但會在表上列出。
- host 進 `llm` 紀錄：Metal（Mac）與 CUDA（桌機）的 kernel 在 temperature 0 下也可能給出不同的輸出，所以 Pilot 與 held-out 必須在同一台主機上跑；
  放進 freeze 已經比對的紀錄，就由程式強制，不必另訂規則。

### 放棄的替代方案

- **留在 Mac、每次充飽再跑**：Pilot 的 dump-all 一次就約 4.5 小時，充電與執行交替會讓 Pilot 拖上好幾天，held-out 的 35–50 小時更不可行；電力條件仍可能在中途失敗。
- **整個 eval 在桌機上執行**（複製 repo、snapshot 與 ground truth 過去）：snapshot 與 ground truth 會離開 Mac，隔離要重新設計，也違反 MACHINE_POLICY
  「主要開發一律在 Mac、桌機只是按需的算力 worker」。
- **adapter 直接連遠端的 URL**（例如桌機的位址）：破壞 adapter「只連 loopback」的保證（§1.2），而那正是「不可能連到付費或第三方服務」的根據。
- **桌機上用 Windows 版 Ollama**：GPU lock 的慣例在 WSL 裡（`flock`），Windows 的程序不在 lock 之內。
- **桌機上的 server 一直開著**：GPU 與其他 project 共用；server 與模型只在一次 lock 內存在（與 §3.8 相同的理由）。
- **以 pid 或命令列裡的 token 精確辨識 server**：要在 cmd → wsl → bash 之間可靠地傳遞 `$$`，或改變 server 的 argv（改變它的啟動方式），都不可靠；
  改用「這個路徑的執行檔只由這個 wrapper、只在 lock 內啟動」加上啟動標記。
- **GPU 讀不到一次就停止**：見「為什麼」。**完全不檢查 GPU**：可能在錯的 GPU 上跑完而不自知。

### 對實驗的影響

- **三個 LLM 方法都要在 Pilot 上用 GPU 重跑**（retrieval、agent、dump-all，各自從頭跑到 exit 0 再評分）：Metal 與 CUDA 的 kernel 在 temperature 0 下
  也可能給出不同的輸出。retrieval 與 agent 在 Mac 上的執行（2026-10-10/11）與分數**被取代**，只留作紀錄（NEXT），不進任何比較；freeze 也會拒絕它們
  （它們的 `llm` 沒有 `host`）。中途停止的 dump-all 本來就不評分。
- latency 是桌機 GPU 的數字（經 SSH tunnel，含少量網路延遲），與 Mac 的數字不可比；報告標明推論主機與 GPU。`tokens_in` / `tokens_out` 仍是同一個模型的 tokenizer。
- freeze 釘住 `host: "gpu-server"`（整個 `llm_methods.json` 的 sha 與每個 LLM 方法 Pilot 的 `llm`）；held-out 必須在同一台桌機上跑。換回 Mac 是另一個修訂，
  要在 freeze 之前、並在 Mac 上重跑 Pilot。
- evidence gold：GPU 重跑之後再用 `gold-todo` 列出（它只看目前的 prediction、只列還沒判斷的）。
- 桌機離線時 LLM 的步驟 blocked（MACHINE_POLICY）；GPU lock 被其他 project 占用時等之後再跑（exit 75）。
- 不改任何預算、指標、切分、門檻、評分、模型、digest、Ollama 版本、`num_ctx`、`num_predict`、temperature、seed、think、`timeout_s`。

### 測試

- `tests/test_with_remote_ollama.py`：PATH 上假的 `ssh` 扮演遠端——照 WSL 的方式以預設 shell 執行 `bash -lc "…"`，遠端的 11434 對應到一個空的 loopback port，
  `-L` 是一個小 relay；遠端 PATH 上有假的 `flock`（lock 檔在測試的暫存目錄，從不碰 Mac 的 `/tmp`）、`pkill` / `pgrep`（登記命令列的程序表，`-x -f` 的完全比對）
  與 stub 的 `ollama`。測：固定的環境與 models 目錄、tunnel、`II_INFERENCE_HOST`、交回 exit code、一定停止自己的 server 而且只停它（同一執行檔的 runner、
  別的 ollama、bash 都還在）、GPU lock 隨之釋放；lock 被占用 → 75、什麼都不停止（包括同一路徑留下的 server）；本機或遠端的 port 被占用 → 3、不碰它；
  ssh 失敗 → 3 並說 blocked；server 起不來 → 3；整個 process group 收到 SIGTERM 仍停止遠端 server；停止無法確認 → 3、提示、不刪 lock
  （之後的執行因 lock 被占用得到 75）；遠端路徑只接受安全的字元、停止的樣式跟著啟動的執行檔。拿掉停止或拿掉 `-x` 時測試會失敗（已確認）。
- `tests/test_remote_inference.py`：`gpu_facts` 的命令與解析（CRLF、`[N/A]`）、讀不到是 null 不是猜測；wrapper 檢查（沒有變數、殘留變數的 pid 已結束）；
  committed 的 host 是 `gpu-server` 且在 `pinned_record` 裡；gpu-server 的執行在 wrapper 外 → 什麼都不寫、不讀 GPU、不連 server；在 wrapper 內不要求
  heavy lock、不讀 Mac 的電力，`power.jsonl` 有 `host` 與前後的 GPU，評分與表的文字（沒有 AC / 高效能 / this Mac）；一次讀不到 → 繼續並列出；連續兩次 →
  三種位置的停止；不是 RTX 5070 Ti → 開始、之前、之後三種停止；held-out 嘗試之前停止不用掉嘗試、失敗嘗試的 GPU 讀不到列在 `failed_not_formal`；
  別的主機取樣的行列出；host `local` 仍要求 heavy lock（wrapper 的變數不能代替）；探測的 `--host`、預設值與 CLI。
- `tests/test_heldout_freeze.py`：Pilot 的 `run_config` 是 host `local`、要凍結的設定是 `gpu-server` → freeze 拒絕（`llm` 不同）；在 gpu-server 重跑後通過。
- 修改：`tests/ollama_fixtures.py` 的 `approved_config` 預設 host `local`（原本的本機測試照舊成立）；`tests/test_local_llm.py`（committed 設定多 `host`、
  `llm` 與 `latency_power` 多 `host`、host 必填、committed 設定在 wrapper 外拒絕）；`tests/test_local_probe.py`（明確 `--host local`）；
  `tests/test_eval_heldout.py`（committed 設定在 wrapper 外拒絕，同樣的設定改成 host `local` 在 heavy lock 拒絕）。
  全部不執行 ssh、nvidia-smi、pmset、Ollama 或任何 server，也不連網路。
