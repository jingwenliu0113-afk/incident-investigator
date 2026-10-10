# 020 — Agent 執行框架 v1（任務說明、tool-use 迴圈、提交答案、用量紀錄）

- 狀態：Accepted（2026-10-09）；在任何 Agent 執行之前寫定。可在 Pilot 上修訂一次（寫 decision log）；held-out 之前凍結。
- 影響範圍：SPEC Core §7 第 4 組（Agent + tools）；LLM baseline（第 1、2 組）共用任務說明與答案格式。
- **不在本文件決定**：模型、每個 incident 的預算數值（工具呼叫數、proxy token、回合數）、dump-all / retrieval 的預算——由使用者決定（decision 011「延後」）；
  第一次呼叫付費 API 之前，依 MACHINE_POLICY 報告用途、請求數、token 量與預估成本並等批准。

## 決策

1. **任務說明**（所有 LLM 方法相同；`agent/prompt.py`）：
   - 角色：只讀的 incident 調查，資料是一個凍結的 telemetry snapshot（traces / logs / metrics），不能接觸正在運作的系統。
   - 時間：時間窗長度（以 render v1 的相對時間表示）與 decision 014 那一句：
     「The system was healthy during the first 10 minutes of the time window; at some point after that a fault may have started.」
   - 答案空間：snapshot 的服務清單、decision 006 的 fault_type 與 fault_family 用詞、user symptom 的 4 種 kind、evidence id 的寫法、origin 最多 5 個且排序。
   - 不描述收集協定（不提 flag、注入、fault 長度、run group），通過 policy 詞彙檢查（測試檢查）。
2. **迴圈**：模型每回合可以呼叫 decision 019 的工具或 `submit_diagnosis`；工具結果原樣回給模型。
   回合數、工具預算到上限時，送一次「請立即提交」的提示；仍未提交則記為放棄作答（decision 013：算錯，不排除）。
3. **提交**：`submit_diagnosis` 的參數就是 decision 013 的 prediction 欄位（fault、origin_candidates、affected_services、user_symptom、evidence）；
   evidence 的 `t0` / `t1` 由模型以「相對時間窗起點的秒數」給，harness 換成資料時鐘的 ns（decision 013 的格式）。
   模型看到的時間是毫秒（renderer 取到 ms），所以 `t0` 換成該毫秒的起點、`t1` 換成該毫秒的終點（+999,999 ns），照畫面上的時間引用一定涵蓋那個點（時鐘稽核）。
   harness 補上 incident_id、method、usage，並用 `check_prediction` 驗證；不合格時把問題回給模型修正，最多 2 次，之後記為放棄作答。
4. **用量**：input / output tokens（模型回報的數字）、工具呼叫數、工具輸出的 proxy tokens、retrieval 次數（Agent 為 0）、wall-clock latency、
   cost = tokens × 呼叫端提供的單價（沒有單價時 null）。
5. **紀錄**：每個 incident 一份 transcript（訊息、工具呼叫與結果、exposure log、usage、停止原因），放在方法的結果目錄（`results/<set>/<method>/<INC>.transcript.json`），
   不含任何 label 或 ground truth。
6. **模型介面**：harness 只依賴一個 `complete(system, messages, tools) → {content, usage}` 的介面（訊息與 content block 採 Anthropic Messages API 的形狀）；
   真正的 API client 是另外一個 adapter，在使用者批准成本之後才加入。測試用腳本化的假模型。
   - **補註（2026-10-10，decision 029）**：使用者暫時同意先試本機模型；第一個 adapter 是本機 Ollama（`agent/ollama.py`，只連 loopback），介面不變。
     截斷或無法確認未截斷的呼叫是不可重試的 `CallError`（029 §2）。付費 API 的 adapter 仍不存在。
     adapter 讀不成 JSON 物件的 tool call 參數放在 block 的 `unparsed_arguments`，harness 照 §3 當成不合格的答案或參數要求更正，不當成空的答案（029 §1）。

## 為什麼

- 所有 LLM 方法共用同一份任務說明與答案格式，差異只在「看得到什麼、怎麼取得」，比較才公平（SPEC §7）。
- 用工具提交結構化答案：避免從自由文字解析答案的誤差，也符合 decision 013「沒有自由文字答案欄位」。
- 放棄作答算錯、預算到了強制提交：方法不能靠拒答或無限探索得利。

## 放棄的替代方案

- **讓模型輸出自由文字、再用另一個 LLM 抽取答案**：多一個會出錯、要花錢的步驟，評分也不可重現。
- **把 fault 類型的說明或範例寫進 prompt**：等於提供 fault 設計的提示；只給用詞清單（答案空間），所有方法相同。

## 修正（2026-10-10，在任何 LLM 方法於任何 set 上的結果之前）

- **發現**：decision 029 的合成範例探測（只用 synthetic 樣本）中，qwen3.5 9B 在 dump-all 與 retrieval 都呼叫了 `submit_diagnosis`，但把 `evidence` 寫成
  id 字串的清單（`["s-…", "l-…"]`），格式規定是物件的清單。harness 把 Python 的例外訊息原樣回給模型（`string indices must be integers, not 'str'`），
  沒說哪一項錯、應該是什麼格式；模型在 temperature 0 下三次送出相同的答案，被記為 `invalid_submission`（放棄作答）。這是 harness 的缺陷，不是答案格式的問題。
- **修正**（§3 的更正迴圈；`agent/harness.py` 的 `_evidence_shape`）：`evidence` 不是清單、某一項不是物件、缺少字串的 `id`、或 `t0` / `t1` 不是數字時，
  回給模型的問題指出是哪一項（`evidence[i]`）並附上預期的形狀。**答案格式不變、沒有放寬**：id 字串的清單仍然不合格，仍然要更正，更正次數上限（2 次）不變。
  其他欄位的檢查（`check_prediction`）原本就會指出欄位，不變。
- 這不是本文件「在 Pilot 上修訂一次」的那一次：發現於合成範例，在任何 LLM 方法在 Pilot 或 held-out 上執行之前，沒有看過任何方法結果。
- 測試：`tests/test_agent_harness.py`（先寫、看到 6 個失敗才改）。
