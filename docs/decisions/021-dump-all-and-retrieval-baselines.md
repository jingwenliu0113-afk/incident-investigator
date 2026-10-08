# 021 — Dump-all 與 Retrieval baseline 的結構（打包順序、檢索方式）

- 狀態：Accepted（結構，2026-10-09）；在任何 LLM baseline 執行之前寫定。**預算數值與模型由使用者決定**（decision 011「延後」），
  下面的數字只是建議值；第一次呼叫付費 API 之前依 MACHINE_POLICY 報告成本並等批准。可在 Pilot 上修訂一次，held-out 之前凍結。
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
