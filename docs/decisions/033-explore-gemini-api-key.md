# 033 — 032 的探索性實驗改用 Gemini API 與使用者的 API key；之後的修訂一律另寫新的 decision

- 狀態：Accepted（2026-10-31）。使用者說「我不會用 我目前只申請了api而已」，key 是在 console.cloud.google.com 建立的（「網址是 console.cloud.google.com」）。
  主 session 提議改用這把 API key（不需要安裝 gcloud、不需要 Application Default Credentials、不需要 project ID 與 region），
  並說明會另寫本文件記錄；使用者接著照提議的步驟進行。
- 影響範圍：只改 032 §3 表格的「模型」「推論位置」「單價」三列，以及 032 §6 第 2 步（使用者的準備）與第 6 步（修訂的寫法）。
  032 的其他內容全部不變：模型仍是 Gemini 4 Argon，thinking low 等設定、預算、執行規則、停止點、結果與 gold 的存放位置都相同。
- 本文件只新增；032 本身不修改（理由見決策第 6 點）。

## 決策

1. **連線方式**：用 Google Gen AI SDK 呼叫 Gemini API，模型 ID `gemini-4-argon`。程式仍保留 Vertex AI 的連線方式，但本實驗不使用。
2. **憑證**：使用者在 console.cloud.google.com 建立的 API key。
   - 由使用者自己存進 macOS 鑰匙圈，`~/.zshrc` 在開新的 shell 時把它匯出成環境變數 `GEMINI_API_KEY`，由 SDK 讀取。
   - 程式只檢查這個變數「有沒有設定」，從不讀出、顯示、記錄或保存它的值。它不會出現在對話、git、結果或 log 裡。
   - 建議使用者把 key 限制成只能呼叫 Generative Language API。
   - 使用者要在 key 所屬的 project 啟用 Generative Language API，並連結帳單帳戶（Argon 沒有免費額度）。
3. **單價**：取自 Gemini API 的官方價格頁（ai.google.dev/gemini-api/docs/pricing，2026-10-31 讀取），每 1M tokens：

   | 期間 | input | cached input | output（含 thinking） |
   |---|---:|---:|---:|
   | 到 2026-11-30 | $2.00 | $0.10 | $10.00 |
   | 2026-12-01 起 | $4.00 | $0.20 | $20.00 |

   - 沒有免費額度；付費方案的資料不會被用來改進 Google 的產品（同一頁）。
   - 每次回覆依它自己的時間計價。價格頁沒寫時區，漲價時點取 2026-12-01T00:00:00Z（UTC，比美西午夜早），
     所以帳上的費用只可能偏高，對費用上限是保守的一側。
   - 帳上的費用是用價格表算出的估計；實際金額以 Google 的帳單為準。
4. **免費檢查**：新增 `python -m eval.explore check`。它只呼叫 models.get，不產生任何內容、不收費；設定檔在 draft 狀態也能執行。
   用來在合成範例探測之前確認 key 與模型 ID 可用。
5. **版本釘選**不變（032 §3）：每次回覆都要寫出它的 model version，實驗途中改變就停止。
6. **之後的修訂一律另寫新的 decision**：main 在 freeze 之後只允許「新增」decision 檔案，修改既有的 decision 會讓 main 的凍結檢查不通過
   （deny by default，`collect/freeze.py` `_change_problems`）。所以 032 §6 第 6 步「寫進本文件的修訂紀錄」改為「另寫新的 decision（034 起）」。
   本文件是 032 的第一個修訂。

## 為什麼

- 使用者手上只有 API key，也不熟悉 gcloud。用 API key 呼叫 Gemini API 是最簡單的做法，模型與單價都和 Vertex AI 相同，實驗內容沒有任何改變。
- 不讓 key 進入對話或 repo：專案規則禁止主 session 要求、讀取或保存任何 credential。

## 放棄的替代方案

- **Vertex AI 加 Application Default Credentials**（032 原本的寫法）：要安裝 gcloud 並登入，使用者表示不會用。
- **Vertex AI 的 API key（express mode）**：不確定使用者的 key 是不是這種；有 Generative Language API 的 key 呼叫 Gemini API 是有文件說明的標準做法。
- **把 key 貼進對話，或寫進 repo、`.env` 檔**：違反專案的 credential 規則，也有外洩風險。

## 對實驗的影響

- 模型、設定、預算與所有規則都不變，只換了連線方式與單價的來源。
- 資料（凍結 snapshot 中的合成 telemetry，沒有個人資料）改送到 Google 的 Gemini API；label 與 ground truth 仍然不會送出。
- 實作在 branch `explore/032-argon`（commit 0a474e8）：完整測試 1150 passed，沒有任何付費呼叫；設定檔仍是 draft。
