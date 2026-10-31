# 035 — 032 的探索性實驗：Gemini adapter 把工具結果之後的文字放進下一則 user turn；Vertex 的版本釘選只到模型名稱

- 狀態：Accepted（2026-10-31，使用者：「批准診斷和重跑探測」）。
- 影響範圍：只改 branch `explore/032-argon` 上的 `agent/gemini.py` 與 `tests/test_gemini.py`（兩個都是 branch 新增的檔案；commit `328a5a1`）。
  - 032、033、034 都不改；本文件只新增（033 第 6 點）。
  - main 的程式、prompt、工具、預算、指標與 Gate 都不變。

## 背景

### Vertex 探測（034 §4，2026-10-31）

合成範例，每個方法一次，合計 $0.21（試用抵免額）。報告在 `data/external/logs/explore-032/probe-2-vertex.json`（不進 git）。

| 方法 | 結果 | 呼叫 | 費用 |
|---|---|---:|---:|
| dump-all | 成功，合格的 submit_diagnosis | 1 | $0.139 |
| agent | 成功，合格的 submit_diagnosis；一次回覆裡平行呼叫多個工具 | 3 | $0.051 |
| retrieval | **失敗**：第 2 次呼叫 HTTP 400 INVALID_ARGUMENT "Requests ending with a model turn are not supported." | 2 | $0.018 |

- 032 §3 的設定都被接受：thinking LOW、temperature 0、seed 42、max_output_tokens 32768。三個方法的 thinking tokens 都是 0。
- 回覆的 `model_version` 是 `gemini-4-argon`；`models.get` 的 version 是 `default`（見決策第 3 點）。

### retrieval 第二次呼叫的形狀

`baselines/retrieval.py` 第二次呼叫送出的對話（Anthropic 形狀，轉成 Gemini contents 之後）：

1. user：任務與資料（text）
2. model：`propose_queries` 的 function_call（含 thought_signature）
3. user：function_response（查詢結果），**後面接** text "Now call submit_diagnosis."

這次請求只宣告 `submit_diagnosis`。

免費的 `count_tokens` 不檢查對話結構，無法不花錢重現。

### 小診斷（使用者批准，2026-10-31）

- 合成的極小請求（每個約 100–170 tokens），走 `GeminiModel`，所以測的就是 adapter 自己的轉換。
- 第一次呼叫是真的，用來拿到真的 function_call 與 thought_signature；第二次呼叫試以下形狀。
- 腳本與輸出在 `data/external/logs/explore-032/diag-3/`（不進 git）。合計 $0.0027。

| 變體 | 第 3 則 user turn | 宣告的工具 | 結果 |
|---|---|---|---|
| V1（retrieval 的形狀） | [function_response, text] | submit_diagnosis | 400（同一個錯誤） |
| V2 | [function_response, text] | propose_queries + submit_diagnosis | 400（同一個錯誤） |
| V3 | [function_response] | submit_diagnosis | 成功（回覆只有文字，因為沒有指示） |
| V4 | [text, function_response] | submit_diagnosis | 成功，呼叫 submit_diagnosis |
| V5 | [function_response]，再接一則 user turn [text] | submit_diagnosis | 成功，呼叫 submit_diagnosis |

**結論**：

- 原因是同一則 user turn 裡**文字放在 function_response 之後**。
- 先前呼叫的工具這次沒有宣告不是原因（V2 宣告了兩個工具仍然失敗）。

## 決策

1. **adapter 修正**：`to_gemini_contents` 遇到 user turn 裡、接在 function_response 後面的文字，就把它放進下一則 user turn（V5 的形狀）。
   - 文字內容與順序都不變。
   - 這和正式方法的 Ollama adapter 一致：`to_ollama_messages` 也是先放 tool messages，再放一則 user message。
   - 只改訊息怎麼分成 Gemini 的 turn。
   - 以 TDD 修正：先改測試並新增測試（紅燈），再改程式。全部 1164 個測試通過。
2. **受影響的訊息**（修正前都會被 Vertex 拒絕）：
   - retrieval：第二次呼叫一定是這個形狀。
   - agent：用完回合上限或工具預算時，最後一則 user turn 是工具結果後面接 `SUBMIT_NOW`（`agent/harness.py`）。這次探測沒有走到這一步。
   - `submit_round` 的更正：在沒有內容的回覆之後，文字會接在先前的工具結果之後。
   - dump-all 的第一次呼叫只有文字，不受影響。
3. **版本釘選的限制**：
   - Vertex 回覆的 `model_version` 只是模型名稱 `gemini-4-argon`，`models.get` 的 version 是 `default`。
   - 所以 032 §3 的釘選只能抓到換成**別的模型名稱**，抓不到 Google 在同一個名稱下更新模型。程式不變（仍然記錄並比對每次回覆的 `model_version`）。
   - 結果報告（101）必須寫明這個限制。
4. **這是 adapter 的 bug 修正**：
   - 發生在任何 Pilot 或 held-out incident 執行之前，沒有任何計分結果受影響。
   - 失敗的探測是合成範例，不是結果。
5. **下一步**（使用者已批准）：
   - 用修正後的 adapter 重跑同一個合成範例探測（約 $0.25）。
   - 三個方法都成功，才照 032 §6 第 5 步跑 Pilot 第 1 題（三個方法，上限 $15），重估總費用後**停下來等使用者批准總額**。

## 為什麼

- 錯誤在 Gemini 的訊息格式，不在方法本身。
- 修 adapter 不改任何方法看到的文字；V5 保留了「先結果、後指示」的順序。這和正式 Ollama 執行時模型看到的順序相同。

## 放棄的替代方案

- **V4：把文字移到 function_response 前面**：Vertex 接受，但模型看到的順序和正式方法不同（指示在結果之前）。
- **改 `baselines/retrieval.py`，不在工具結果後加文字**：會改方法本身，而且那是凍結的程式（032 §2）。
- **第二次呼叫也宣告 `propose_queries`**：V2 顯示這不是原因，而且會改變模型能用的工具。

## 對實驗的影響

- prompt、工具、預算、設定與單價都不變。
- 032 實驗到目前的花費（試用抵免額）：
  - Gemini API 探測 $0（402）；
  - Vertex 探測 $0.21；
  - 小診斷 $0.0027。
