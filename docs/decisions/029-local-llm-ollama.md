# 029 — LLM 方法暫時改試本機模型（Ollama adapter、截斷防護、模型釘選、合成範例探測）

- 狀態：Accepted（2026-10-10，使用者決定，**暫時**）。使用者原話：
  「先暫時兩個都同意，先關掉 grafana 下載再測本地模型，之後可以考慮再換回來原本的方案」。
  寫在任何 LLM 方法的執行（包括合成範例的探測）、任何 held-out 資料與 freeze 之前。使用者之後可以換回原本的方案（付費 API 模型），換回時另寫 decision log
  （見「對實驗的影響」）。「兩個」的另一項（關掉 grafana 的 plugin 下載，NEXT A0）不在本文件。
- 影響範圍：新增 `agent/ollama.py`（adapter）、`eval/probe.py`（`python -m eval local-probe`）；`eval/runner.py`（`load_llm_config`、`llm_fit`、`start_llm`、
  `run_llm`、`_llm`、`run_config.json` 的 `llm`、評分表多一行）；`eval/__main__.py`；`eval/llm_methods.json`（只新增欄位，仍是 `proposed`）；
  decision 020 §6 與 021 的補註；README 的狀態句。
  **不改**任何預算數值、指標、切分、門檻、freeze 協定，也不改 decision 013、020–024、026 的任何規則（`RETRYABLE` 仍只有 `api_error`、`transport_error`）。

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
- decision 021：dump-all 的 B = 120,000 proxy tokens，是為約 200k context 的模型設計；三個 LLM 方法用同一個模型（021 §4）。
- MACHINE_POLICY：本機硬體運算不是外部費用；但數小時的本機模型執行是 heavy workload。

## 決策

### 1. Adapter（`agent/ollama.py`，只用標準函式庫）

1. 實作 decision 020 §6 的介面：`OllamaModel.complete(system, messages, tools)` → `{content, usage, stop_reason, ollama}`（harness 只讀 content 與 usage）。
   - 送出：`system` → system 訊息；text → user / assistant 的 content；`tool_use` → assistant 的 `tool_calls`；`tool_result` → `role: "tool"` 訊息
     （帶 `tool_name` 與 `tool_call_id`；`is_error` 的內容本來就以 `error:` 開頭）；thinking → assistant 的 `thinking`。tools → `{"type": "function", ...}`。
   - 收回：`tool_calls` → `tool_use`，id 由 adapter 產生、可重現（`toolu_<回合>_<序號>`，與 Ollama 自己的 id 無關）；字串形式的 arguments 解析成物件，
     解析不了時 `input` 為空、原文放在 `unparsed_arguments`（交給方法照 020 §3 拒收）；text → text；thinking → thinking block（transcript 保留）。
   - `stream: false`；options：`temperature`、`seed`、`num_ctx`（必填，絕不用 Ollama 的預設）、`num_predict`（輸出上限）；`think` 開或關（記錄）。
   - usage：`prompt_eval_count` → input tokens、`eval_count` → output tokens。
2. **只連本機**：URL 必須是 `http://` 加 `127.0.0.1`、`localhost`（解析結果必須全部是 loopback）或 `::1`；直接用 `http.client`（不經過任何 proxy 設定）；
   tag 以 `cloud` 結尾、或 `/api/tags`、`/api/show`、任何一次回覆帶 `remote_model` / `remote_host` 的模型（Ollama 的 cloud 模型）一律拒絕。
   這個 adapter 因此不可能連到遠端或付費服務。

### 2. 截斷防護：一次呼叫絕不靜默截斷

1. 每個請求都送 `truncate: false`、`shift: false`：Ollama 改為回錯誤，而不是丟訊息或 shift。
2. 每個回覆都檢查，任何一項不成立就丟 `CallError`：
   - HTTP 錯誤的訊息提到 context（例如 "the input length exceeds the context length"）→ `context_overflow`；
   - 沒有可用的 `prompt_eval_count` / `eval_count` → `context_unverified`；
   - `prompt_eval_count + eval_count ≥ num_ctx` → `context_overflow`；
   - `done_reason` 是 `length` 但輸出少於 `num_predict`（被 context 截斷，不是被輸出上限）→ `context_overflow`；
   - `/api/ps` 沒有列出這個模型，或載入的 `context_length` 不等於 `num_ctx`（例如被 Ollama 調整）→ `context_unverified`；載入的 digest 不是釘選的 → `pin_mismatch`；
   - 回覆來自遠端模型 → `remote_model`。
3. **失敗的方式**：上面這些 reason 都**不在** `RETRYABLE`（`api_error`、`transport_error`）裡。依現有的契約（023 §5、026 解讀 17、19）：
   - Pilot：`eval run` 停止，CLI 印 `error: …`、exit 2（與 API 錯誤相同，NEXT A1）；
   - held-out：該次嘗試記為 `error`、該 incident 關閉、不再有 prediction，評分時算放棄作答（`no_answer`，留在分母、列出嘗試結果）；執行停止，由人查看。
   - 其他 HTTP 錯誤仍是 `api_error`，連線失敗 / 逾時仍是 `transport_error`（可依 026 解讀 17 重試）。
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
2. **Ollama 版本也釘選**（比「只記錄」嚴格）：tool call 的 renderer / parser 與 context 的處理都隨 Ollama 版本改變，Pilot 與 held-out 之間 Homebrew 升級
   會在不知不覺中改變方法。不符就拒絕。
3. 什麼時候檢查：每次執行開始時（`start_llm`，在開任何 snapshot、寫任何檔案之前）、每個 incident 之前再一次、每個回覆之後看 `/api/ps`。
   另外檢查 `num_ctx` 不超過模型的 context_length、模型回報 tools 能力、think 開時回報 thinking 能力。
4. `run_config.json` 多一個 `llm`：provider、model、model_version（digest）、ollama_version、num_ctx、num_predict、temperature、seed、think。
   held-out 續跑要求完全相同的 `run_config.json`（024、026 解讀 18），換任何一項就是另一次執行而被拒絕。評分表多一行 Model runtime。
5. 本機 provider 必須寫 `price_per_mtok = {input: 0, output: 0}`：`cost_usd` 是 0（明確是本機），不是 null（未知）。
6. seed 必須是正整數（預設 42）：Ollama 的選項結構把 seed 標成 `omitempty`，0 在傳給 runner 的途中可能被當成「沒設」。temperature 0 是 greedy，
   seed 只是記錄。其他取樣參數維持模型的預設（由 digest 釘住；探測記錄 `/api/show` 的 parameters）。
7. adapter 看不到 server 的環境變數；server 一律以固定的指令啟動：
   `OLLAMA_HOST=127.0.0.1:11434 OLLAMA_NUM_PARALLEL=1 OLLAMA_NO_CLOUD=1 ollama serve`（其他設定用預設；有不同時記在 NEXT）。
8. **heavy lock**：本機模型的 `eval run` 與探測都要求 Mac heavy lock（與 `collect run` 相同的 `require_heavy_lock`），透過 `./tools/with-mac-lock` 執行；
   拿不到就拒絕，不搶。

### 4. `eval/llm_methods.json`

- 仍是 `status: "proposed"`、`model: null`；新增欄位：`provider: null`、`model_version: null`、`temperature: 0`、`price_per_mtok: null`、
  `ollama: {url: "http://127.0.0.1:11434", version: null, num_ctx: null, num_predict: 8192（建議值）, seed: 42, think: null, timeout_s: 3600}`；
  `budgets` 不變。
- 批准時（使用者決定之後）填：`provider: "ollama"`、model、model_version、`price_per_mtok` 0、`ollama.version`、`ollama.num_ctx`、`ollama.think`。
  探測輸出一段 `config_if_approved`（只是參考，不會自動寫入）。
- `load_llm_config`：approved 且 provider 是 `ollama` → 檢查所有欄位與 fit，然後用 adapter；其他任何 provider 照舊拒絕（「no model API adapter is installed yet」）。

### 5. 合成範例探測：`python -m eval local-probe`

```text
./tools/with-mac-lock uv run python -m eval local-probe --model <tag> [--num-ctx N] [--think] \
    [--context-sizes 8000,32000,100000] [--out PATH]
```

- **只在合成範例上執行**：沿用 `eval/demo.py` 的 `check_sample`（`synthetic: true`、每個檔案的 sha256 相符、沒有未列出的檔案），incident 必須是範例的 id；
  其他一律拒絕。不讀 label、不評分。
- 拒絕：heavy lock 沒拿到、遠端（cloud）模型、沒有安裝、`num_ctx` 超過模型的 context_length。`--num-ctx` 預設為模型的 context_length，最多 65,536
  （合成範例的 dump-all 約 4 萬 proxy tokens）。
- 用 `llm_methods.json` 建議的設定（預算、temperature、seed、num_predict），price 0；索引快取放在暫存目錄。**不寫 `data/` 下的任何東西**：
  輸出到 stdout 或 `--out`（`--out` 在 `data/` 下就拒絕）。
- 依序：
  1. 防護自我測試：`num_ctx` 2,048、約 6,000 proxy tokens 的產生文字，必須得到 `context_overflow`；否則在 warnings 寫 GUARD FAILED（不要用這個 Ollama 版本跑）；
  2. 三個方法（真正的方法程式），每個方法報告：tool call 是否被解析（`tool_calls_parsed`，以及寫成文字的 `text_tool_calls`）、是否提交合格的 prediction、
     更正次數、是否放棄作答、錯誤、tokens in / out、latency、cost、每次呼叫的實際 / proxy token 比例與 prefill / decode 時間；
  3. 同一個短 prompt 送兩次，看 temperature 0 是否得到相同回覆；
  4. `--context-sizes`：各大小的產生文字（中性的單字，沒有任何 incident 資料）量 prefill 與 decode 的 tok/s；超過 `num_ctx` 的大小略過。
- 輸出的開頭與結尾都聲明：**不是結果**。也記錄看到的模型 digest、Ollama 版本、能力與預設參數，以及 fit check。

## 不在本文件決定

- **用哪個模型、`num_ctx`、think**：使用者看過三個模型的探測報告之後決定。
- **預算數值**：不變（B = 120,000、q = 8、k = 25、Agent 40 次 / 120,000 / 30 回合）。選定的模型放不下時，要不要改預算是使用者的決定（另寫 decision log）。
- `llm_methods.json` 維持 `proposed`；三個 LLM 方法在 Pilot 上執行要等使用者同意（提案第 3 步）。
- `num_predict` 8192 只是建議值，隨模型一起由使用者批准。

## 為什麼

- 使用者決定先試本機模型：沒有外部費用，又能讓已寫好的 harness 實際跑起來；付費 API 仍可換回。
- Ollama 的預設行為會在不報錯的情況下丟掉資料，方法的結果就會取決於看不見的截斷；與 A1 的「預算與可見資料必須明確」（SPEC §7、024）矛盾。
  寧可大聲失敗、讓使用者調 `num_ctx` 或決定預算，也不讓 context 變成一個沒有報告的隱藏預算。
- 截斷用 `CallError` 而不是 harness 的「放棄作答」：回合與工具預算是方法設計的一部分（020、021），context 是所選模型與執行環境的性質；
  把它變成方法自己的放棄作答，等於多一個沒有登錄的預算。現有契約已規定不可重試的錯誤怎麼處理（Pilot 停止、held-out 關閉該 incident），不必新增規則。
  不可重試：temperature 0、同一個請求，再送一次一樣會超過。
- 釘 digest 與版本：manifest digest 同時釘住權重、template 與參數；Ollama 版本釘住 renderer / parser 與 context 處理。少了任何一個，freeze 的「模型、版本」就不完整。
- 先在合成範例上探測：選模型只依 tool calling、防護與速度，不看任何 Pilot 結果，避免用 Pilot 的成績挑模型；也符合「Pilot 等使用者同意」的順序。

## 放棄的替代方案

- **用 Ollama 的預設 context（或 `OLLAMA_CONTEXT_LENGTH`）**：預設值小，長 prompt 會被靜默截斷。
- **送出前先算 token 數**：Ollama 的 API 沒有公開的 tokenize；proxy 估計不精確。伺服器端的 `truncate: false` 檢查是精確的，再加上回覆後的檢查。
- **context 超過時當成 harness 的停止（放棄作答）**：見「為什麼」。
- **context 超過時重試**：結果一樣，只是浪費時間（held-out 還會用掉一次嘗試）。
- **OpenAI 相容的 `/v1/chat/completions`**：沒有 `truncate` / `shift` 的控制；`/api/chat` 有，`/api/ps` 也能確認實際載入的 context。
- **`ollama` Python 套件**：多一個依賴；標準函式庫就夠。
- **只釘 digest、不釘 Ollama 版本**：見「為什麼」。
- **在 Pilot incident 上探測**：違反提案的順序（Pilot 等使用者同意），也會用 Pilot 挑模型。
- **自動縮小預算以放進 context**：預算是使用者的決定（020、021），而且三個方法必須公平（021 §4）。

## 對實驗的影響

- **結論縮小到所選的本機模型**（q4_K_M 量化、該 Ollama 版本、`num_ctx`、think 設定）：SPEC 的「LLM Agent 能不能…」只能以這個模型回答，報告與 README 必須寫明。
  三個 LLM 方法用同一個模型（021 §4 不變）。
- **freeze 只釘一個模型，held-out 每個（方法, incident）只跑一次**（023 §5、§6；026 解讀 9、17、18）：日後換回付費模型，必須在 **freeze 之前**用那個模型
  重跑 Pilot 的三個 LLM 方法（以及補 evidence gold，decision 017），held-out 不能混用兩個模型；freeze 之後換模型是設計變更（023 §6），不允許。
  換回時需要另寫 decision、加付費 API 的 adapter，並在第一次呼叫前依 MACHINE_POLICY 報告成本。
- **context 放不下 dump-all 預算的模型不能原樣執行 dump-all**（Agent 的工具輸出預算也一樣；例如 qwen3:8b 的 40,960 遠小於約 13 萬 proxy tokens 的 need）：
  fit check 拒絕；改預算是使用者的決定。
- 本機運算沒有外部費用（`cost_usd` = 0），但有時間成本：探測的速度量測用來估計 Pilot 的執行時間；多小時的執行是 heavy workload，透過 `with-mac-lock`。
- latency 是這台 Mac 的本機數字，與付費 API 不可比；照實報告並標明（SPEC §7）。
- `tokens_in` / `tokens_out` 是模型自己 tokenizer 的數字，與 proxy token 不同單位；兩者照 024 分開報告。
- 合成範例的探測**不是結果**，不進 README 的結果表，也不用來調整任何方法、prompt 或預算。

## 測試

- `tests/test_ollama.py`（訊息與工具的轉換、可重現的 id、請求的選項、每一種截斷 / 無法確認的情況、API 與傳輸錯誤、只接受 loopback、釘選、
  綁在 127.0.0.1 的 stub HTTP server、harness 在 adapter 上跑完且 cost 為 0）、`tests/test_local_llm.py`（committed 設定仍是 proposed 且預算不變、
  approved 的每個必填欄位、其他 provider 仍沒有 adapter、fit check、Pilot 與 held-out 的 `run_config.json`、digest 不符或沒有 lock 時什麼都不寫、
  執行中途換模型就停止）、`tests/test_local_probe.py`（只在合成範例、報告內容、拒絕的情況、CLI、不寫 `data/`）。
  全部用腳本化的 transport 或測試內綁在 loopback 的 stub server，**從不連到真正的 Ollama**。
