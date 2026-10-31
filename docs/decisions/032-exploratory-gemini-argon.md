# 032 — 探索性實驗：用 Gemini 4 Argon（Vertex AI）在既有 held-out 上重跑三個 LLM 方法（不是 Gate 判定）

- 狀態：Accepted（2026-10-31，使用者確認草稿：「三點都同意，commit 並 push 後開始實作」——整份草稿、tag `heldout-final` 加上
  永不 merge 回 main 的 branch、thinking 先用 low 並在合成範例探測後確認）。付費 API 的第一次呼叫仍照第 6 節第 4 步先報告、等批准。
- 影響範圍：在 Core 收尾（031）之後，另外做一個**探索性**實驗。它回答「換成較強的模型，結論會不會不同」，不重新判定 Gate。
- **不改任何東西**：100、031、Gate 判定（NOT PASSED）、凍結的程式、資料、prompt、工具、預算、指標、門檻、切分、incident 清單、
  正式的 gold（`evidence_gold.json`）與正式結果（`data/external/results/heldout/`、`results/pilot/`）都不變。

## 背景

- Core 已用 held-out 的 Gate 判定 NOT PASSED 收尾（031）。結論只適用於本機模型 qwen3.5 9B（q4_K_M）（029、031「對實驗的影響」）。
- freeze 只釘一個模型；freeze 之後換模型是設計變更，不能拿來重新判定 Gate（029「freeze 只釘一個模型」、023 §6）。
- 自然的後續問題是「是不是 9B 模型太弱」。使用者 2026-10-31 的選擇（原話依序）：
  - 雲端 API 用 Google Cloud 的 Gemini（「2」）；
  - 模型 Gemini 4 Argon（「argon」）；
  - 做法 A：沿用這 50 個 held-out incident，做探索性補充（「a」）；
  - 三個 LLM 方法都跑（「三個都跑」）。

## 決策

### 1. 定位：探索性，事前登記，結果不論好壞都報告

1. 這是**探索性結果，不是 Gate 判定**。100 與 031 不改；Core 的結論仍是 NOT PASSED。
2. **只試一個模型（Argon）、每個（方法, incident）只跑一次**。看到結果之後不換模型、不調設定重跑。之後若想試別的模型，要另寫 decision，
   並在報告中寫明這是同一組 held-out 上的第二次探索（多次比較）。
3. 結果不論好壞都寫進 `docs/decisions/101-exploratory-argon-results.md`（固定檔名，只寫一次；之後的更正照 030 §3 另寫 decision）。
4. 即使 Argon 的 agent 明顯勝過 stat-anomaly，報告也只寫「探索性結果顯示…」。要成為 Gate 等級的結論，需要新的 held-out 集合
   （023 §7「另開新的集合」的做法，另寫 decision）。

### 2. 不變的部分（事前登記）

- incident：`heldout_incidents.json`（sha256:e606baae8b8944f1267e6296e7d9784620b952149b12f37e46dc99821a6140b5）列入的 50 個，
  freeze 記錄 sha256:7d68302545d958c4ba4d787e2d4f6fa558c954ccb27b7369f217b4b14d20cb39；snapshot、label、ground truth 都是凍結的那一份。
- 方法：dump-all v2、retrieval v2、agent v1（`LLM_METHOD_VERSIONS`）；prompt、7 個工具、可見資料範圍都不變。
- 預算：dump-all B = 120,000 proxy tokens；retrieval q = 8、k = 25；agent 40 次工具呼叫、120,000 proxy tokens、30 回合。
- 評分與統計：013 的分層評分、017 的 evidence 層、022 的失敗分類、compare 的 paired bootstrap（10,000 次、seed 0）。
  023 §7 的三個 Gate 條件照原本的操作定義計算，但只作描述，輸出寫明「EXPLORATORY, NOT a Gate decision」。
- 執行規則與正式 held-out 相同：每個（方法, incident）一個 attempt；只有 `api_error`、`transport_error` 可以重試，
  總共最多 2 次（`HELDOUT_MAX_ATTEMPTS`）；預測永不覆寫；每次 attempt 記在 `attempts.jsonl`。
- 順序：retrieval → agent → dump-all（與 Pilot 相同）。
- stat-anomaly 不是 LLM，不重跑；比較時直接讀正式結果（唯讀）。

### 3. 必須不同的部分（全部列出）

| 項目 | 凍結設定（qwen） | 本實驗（Argon） | 為什麼 |
|---|---|---|---|
| 模型 | Ollama `qwen3.5:9b-q4_K_M`，manifest digest 釘住 | Vertex AI 的 Gemini 4 Argon（model ID 以 Model Garden 顯示的為準） | 本實驗的目的 |
| 版本釘選 | manifest digest，不符就拒絕 | 記錄每次回覆的 `modelVersion`；實驗途中改變就停止並回報 | 雲端模型沒有 digest 可釘 |
| 推論位置 | 桌機 RTX 5070 Ti（SSH tunnel） | Google Cloud Vertex AI（project、region 由使用者提供） | |
| thinking | off | **low**（合成範例探測後由使用者確認） | 找不到 Argon 能完全關掉 thinking 的說法；low 最接近 off，也最便宜 |
| temperature / seed | 0 / 42 | API 接受就用 0 / 42；不接受，或合成範例探測顯示 0 會造成重複迴圈，就用模型預設值 | 盡量貼近凍結設定；在任何 Pilot 或 held-out 呼叫之前決定並記錄 |
| 輸出上限 | num_predict 8192 | max_output_tokens 32,768 | Gemini 的上限同時包含 thinking 與回答，Google 建議至少 32,768 |
| context | num_ctx 262,144 | 模型的 1M | `llm_fit` 照樣檢查預算放得下 |
| 單次呼叫逾時 | 3,600 秒 | 3,600 秒（不變） | |
| 單價 | 0（本機） | 執行當時 Vertex 的實際單價（input、output、cached input），由使用者從 console 確認 | 報告每個 incident 的成本 |
| tokenizer、latency | qwen；本機 GPU | Gemini；網路加雲端 | 兩者的 tokens 與 latency 不可比；proxy tokens（預算的單位）可比 |
| 內容被拒 | 不適用 | 回覆因安全過濾被擋（例如 `finish_reason` 是 SAFETY）算模型的失敗（no_answer），不重試 | 不能靠重試換答案 |

- usage 對應：tokens_in = prompt tokens，另列 cached tokens；tokens_out = 回答 tokens 加 thinking tokens，thinking 另列。

### 4. 程式放哪裡、結果寫到哪裡（main 保持凍結）

- freeze 之後，main 上只允許改 `NEXT.md` 和新增 decision 檔案；所有 held-out 指令都會檢查這一點，有其他改動就拒絕（deny by default）。
  所以：
  1. **程式放在 branch `explore/032-argon`**（從 main 分出），推到私有 origin，**永不 merge 回 main**。
     main 只加文件（032、101）和 `NEXT.md`，三項唯讀確認在 main 上保持通過。
  2. 建 branch 之前，在 main 目前的 commit（e47f2c7，發布 100 的那一個）加 tag `heldout-final`，並推到 origin。
     這只是新增 tag，不改寫任何歷史，之後隨時能回到正式發布的狀態。
- 探索用的執行指令另外新增，不經過 `heldout_guard`（branch 上的凍結檢查本來就不會通過）。它改做以下唯讀檢查：
  - `docs/heldout/freeze.json` 與 `heldout_incidents.json` 的 sha256 等於上面登記的值，incident 清單只從這個檔案讀；
  - 輸出只寫到 `data/external/results/explore-032/<set>/<method>/`；目標已存在就拒絕；
  - 永遠不寫 `results/heldout/`、`results/pilot/` 和任何 `evidence_gold.json`。
- 用 TDD 寫：上述限制、Gemini adapter 的格式轉換（Anthropic Messages 形狀 ↔ Gemini 的 contents、functionCall），
  以及 usage 與成本的計算，全部用假的模型測試，測試不呼叫真的 API。
- 新增的 Python 套件（Google 的 Gemini SDK）只改 branch 上的 `uv.lock`。
- 探索用的設定寫在 branch 上的 `eval/llm_methods.explore-032.json`，每次執行都記錄它的 sha256；
  正式的 `eval/llm_methods.json` 不變。

### 5. Gold（新的 evidence 要人工標）

- 規則與 017 相同：每個方法、每個 incident 最多抽 5 個引用；工作表不顯示方法名稱；標註者是使用者（`human:<name>`），我不代填任何判定。
- 已經在正式的 604 項裡判定過的（同一個 id、t0、t1）直接沿用，不重判；只有新的項目進工作表。估計約 300–600 項。
- 新的判定**另存**在 ground truth 那一側的 `evidence_gold.explore-032.json`（與各 incident 的 `evidence_gold.json` 同一個目錄，
  方法讀不到）。正式的 `evidence_gold.json` 不動，所以正式的 gold precision 與 coverage 不可能因此改變。
- 探索的評分同時讀正式 gold 與 032 的 gold；正式評分只讀正式 gold（不變）。

### 6. 步驟與停止點

1. 使用者確認本草稿 → 狀態改為 Accepted，只把本文件 commit 到 main。
2. 使用者在 Google Cloud 自己做：
   - 有 billing 的 project；
   - 啟用 Vertex AI API，在 Model Garden 確認 Argon 可用以及顯示的單價；
   - `gcloud auth application-default login`；
   - 設預算警示（建議 $250）。
   做完後告訴我 project ID、region 和單價。憑證由使用者處理，我不讀取也不保存。
3. 加 tag `heldout-final`、建 branch，用 TDD 寫 adapter 和探索用的執行指令。這一步不呼叫付費 API。
4. **第一次付費呼叫：合成範例探測。** 只用 `data/samples/synthetic/`，三個方法各跑一次，預估少於 $1，先報告、等批准。
   - 探測結果要回答：工具呼叫是否正常、temperature 和 seed 是否被接受、thinking low 是否有效、tokens 與 latency。
   - 使用者依結果確認第 3 節的設定，之後設定檔不再改。
5. **Pilot 第 1 個 incident（三個方法）。** 用實測的用量重新估算總費用 → **使用者核准總預算**。
   執行指令依這個核准額設上限：累計成本超過就停止並回報，不自動繼續。
6. Pilot 其餘 9 個 incident。Pilot 只用來驗證 adapter（診斷用，永遠不和 held-out 合併）。
   - 發現 adapter 的 bug：修正、寫進本文件的修訂紀錄、整個 Pilot 重跑。
   - prompt、工具、預算與第 3 節的設定，不因 Pilot 的結果修改。
7. held-out 50 個 incident × 三個方法。
8. 評分、與 stat-anomaly 的 compare、描述性的 Gate 條件；產生 gold 工作表 → 使用者盲標 → 重新評分。
9. 寫 101（只寫一次）：
   - 內容：四個方法的結果（stat-anomaly 取自正式結果）、qwen 與 Argon 並列、用量與實際成本、失敗分類；
   - 不含 incident ID；
   - commit 到 main 時只有 `A 101`、`M NEXT.md`，commit 前後各跑一次三項唯讀確認。

## 為什麼

- 用不大的費用回答「是不是模型太弱」。不論結果是哪一種都有意義：還是輸，代表問題不只是模型大小；贏了，就有理由再開一個新的 held-out。
- 三個方法都跑：如果 Argon 的 agent 贏了，可以分辨是 agent 的設計有用，還是只是模型變強（同一個模型直接看資料或用檢索，表現如何）。
- 事前登記模型、設定和報告方式，而且只試一個模型：held-out 的結果已經看過了，這是降低「換到過為止」風險的唯一辦法。
- branch 加 tag、結果和 gold 分開存放：正式結果、正式 gold 與 main 的凍結狀態都不受影響，隨時可以重現 100。

## 放棄的替代方案

- **Claude on Vertex AI**：adapter 較簡單，但使用者選了 Gemini。
- **B：正式第二輪（新的 held-out 集合）**：要好幾週，加上完整的 label review 和 gold 盲標。Argon 的結果如果看起來很強，之後可以另寫 decision 再做。
- **只跑 agent**：費用約一半、gold 較少，但無法區分 agent 的設計與模型強度。使用者選三個都跑。
- **直接在 main 上改程式**：凍結檢查會讓所有 held-out 指令拒絕執行，也會混淆正式結果和探索結果。
- **新的 gold 直接寫進 `evidence_gold.json`**：正式結果之後若重新評分，coverage 可能改變（例如 retrieval 的 coverage 是 0.374，新判定可能補到它沒抽到的引用）。
- **thinking medium 或 high**：比較貴，也離凍結的「think off」更遠。

## 對實驗的影響

- 100、031 與 Gate 判定都不變。101 的數字全部標明是探索性的。
- 限制要照實寫：
  - 這 50 個 incident 的結果、gold 與失敗分析都已經看過；本實驗只換了模型，但「決定做這個實驗」本身發生在看到結果之後。
  - 第 3 節的差異（thinking、temperature、輸出上限、tokenizer）讓 Argon 和 qwen 不是只差在模型。
- 費用：上一則估計的範圍是，11/30 前的優惠價約 $60–120，標準價約 $120–240，誤差約 ±50%。實際上限在第 6 節第 5 步由使用者核准。
- 磁碟：60 個 incident 的索引 cache 會自動重建，約 32 GB（使用者 2026-10-31 刪掉的那一份）；目前可用約 105 GB。
- 資料外送：凍結的 snapshot（OTel Demo 的合成 telemetry，沒有個人資料）會送到 Google Cloud Vertex AI。label 與 ground truth 不會送出，方法本來就讀不到。
- 機器：推論在雲端，Mac 只跑 eval 迴圈和工具，與 029 修訂 1 的遠端推論相同，不需要 Mac heavy lock，也不用桌機的 GPU lock。
  開始前仍會檢查 Mac 的 CPU、GPU、RAM 負載。
