# 019 — Agent 工具 v1 的介面（資料存取、預算計量、exposure log）

- 狀態：Accepted（2026-10-09）；在任何 Agent 或 retrieval baseline 執行之前寫定。工具清單本身已在 decision 011 §5 決定，本文件固定細節。
  可在 Pilot 上修訂一次（寫 decision log）；held-out 之前凍結。
- 影響範圍：SPEC Core §7 第 4 組（Agent + tools）；第 2 組（retrieval + LLM）共用同一個索引；所有方法的 exposure / 預算報告。

## 背景

- decision 011 §5：Agent 工具只提供資料存取（list_services、search_logs、search_spans、get_trace、list_series、get_points、service_minute_stats），
  **不提供異常排名**；預算單位 proxy_tokens = ceil(utf8 bytes / 4)；每個 run 記錄看過的 record id（exposure log）；index（sqlite）以 content_sha256 快取在 `data/external/cache/`。
- decision 014：所有方法只拿到時間窗與「前 10 分鐘正常」這一句。
- SPEC §7：每組報可見資料範圍、retrieval / tool-call / token 預算、latency、cost；避免 Agent 因為「看了更多資料」而不公平勝出。

## 決策

1. **索引**：只從 `open_snapshot()`（驗過 sha）的 record 建立 sqlite 索引，放在 `data/external/cache/<content_sha256>/index.sqlite`；
   開啟時比對 content_sha256，不符就重建。每筆存 renderer（decision 011 §5，v2 見該文件修訂）的那一行（Agent 看到的就是這一行）。
2. **時間參數**一律是「相對時間窗起點的秒數」（與 render v1 的 `+MMM:SS.mmm` 同一個基準），區間 `[t0, t1)`。
3. **文字比對** = 子字串比對（ASCII 不分大小寫；`%`、`_` 是一般字元），比對對象是該 record 的 render v1 那一行（看得到什麼就能搜什麼）；沒有排序上的「相關度」。
   實測（soak #5 的 38 分鐘 snapshot，約 19 萬個 span）：建索引約 9 秒、326 MiB；一次查詢 0.1–0.3 秒。
4. **結果排序**：時間由早到晚、同時間依 id；每次最多回傳 50 筆（`limit`，預設 20），用 `offset` 翻頁；第一行說明總筆數與這次顯示的範圍。
5. **工具**（參數都可省略，省略 = 不限制）：
   - `list_services()`：snapshot 的服務與各自的 span / log / metric series 數（中性的數量，不是排名）。
   - `search_spans(service, text, status, min_duration_ms, t0, t1, limit, offset)`：status ∈ {error, ok, unset}。
   - `search_logs(service, text, min_severity, t0, t1, limit, offset)`：min_severity 是 OTLP severity number。
   - `get_trace(trace_id, limit, offset)`：該 trace 的 span。
   - `list_series(service, text, limit, offset)`：text 比對 metric 名稱與 series 那一行。
   - `get_points(series_id, t0, t1, limit, offset)`。
   - `service_minute_stats(service, t0, t1)`：該服務每分鐘的 span 數、error span 數、server span p95、WARN 以上 log 數、CPU 核數、記憶體（`collect.derive` 的同一套定義）；
     一次只能看一個服務，不提供跨服務比較或分數。
6. **預算與紀錄**（每個 incident 一個 session）：工具呼叫數與工具輸出的 proxy_tokens 累計；超過上限時工具回傳「預算用完」而不給資料。
   exposure log = 每次輸出中出現的 record id（按順序、去重）與 trace id；與 usage 一起寫進方法的輸出旁邊（不在 prediction 裡）。
   預算數值（呼叫數、token 數）與模型屬於要由使用者決定的事項（decision 011「延後」），這裡只固定計量方式。
7. **工具說明文字**不描述收集協定、不提 flag 或 fault 注入，並通過 policy 的詞彙檢查（測試檢查）。

## 為什麼

- 子字串比對與時間排序：行為可預測、可重現，不會偷偷把「重要」的東西排在前面（那等於一種異常排名）。
- 每次最多 50 筆、翻頁：讓「看多少資料」反映在呼叫數與 token 上，預算才能公平比較。
- 一次一個服務的分鐘統計：Agent 自己決定要看哪些服務，跨服務比較留給它自己做；統計 baseline 的工作不會被工具代勞。

## 放棄的替代方案

- **FTS5 全文檢索與 BM25 排序**：排序本身會帶進「相關度」判斷；斷詞規則也讓 Agent 難以預期哪些字串查得到。
- **提供 top-N 錯誤或異常服務的工具**：decision 011 §5 已排除。
- **讓 Agent 直接讀 jsonl 檔**：無法計量、無法記錄 exposure，也無法保證只讀 snapshot。

## 對實驗的影響

- Agent 與 retrieval baseline 的 usage 會報 tool_calls、proxy_tokens（工具輸出），以及實際 token / latency / cost。
- exposure log 讓之後可以分析「答錯時是否看過正確的 evidence」（telemetry 不足 vs 推理錯誤，Gate 的判斷依據之一）。
