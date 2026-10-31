# 034 — 032 的探索性實驗改回 Vertex AI，用使用者登入的 Application Default Credentials 與 Google Cloud 試用抵免額

- 狀態：Accepted（2026-10-31，使用者：「選 B，可以裝 gcloud，探測費用也同意」）。
- 影響範圍：取代 033 第 1、2 點的連線方式與憑證（033 的其他內容不變：單價依時間計價、免費檢查、版本釘選、修訂一律另寫新的 decision）。
  032 的其他內容全部不變。本文件只新增；032、033 都不修改（033 第 6 點）。

## 背景

- 使用者批准合成範例探測（「批准探測」，2026-10-31）。用 033 的 Gemini API 與 API key 執行時，三個方法的第一次呼叫都被拒絕：
  HTTP 402 RESOURCE_EXHAUSTED，訊息是 "Your prepayment credits are depleted"。沒有任何回覆，費用 $0；報告在 session 暫存目錄（不進 git、不寫 `data/`）。
- 原因（Gemini API 的官方帳單說明 ai.google.dev/gemini-api/docs/billing，2026-10-31 讀取）：
  - 新用戶預設是預付制：要先在 AI Studio 買點數（最少 $5、最多 $5,000；12 個月到期、一般不退費），用完時呼叫被拒（HTTP 402）。
  - 2026-03-02 之後開的帳戶，Google Cloud 的歡迎或試用抵免額一般不能用在 Gemini API。
- 使用者的帳單帳戶是 Google Cloud 免費試用帳戶，試用抵免額還有 $8,053.97（2026-10-31，使用者同意下由主 session 用 Chrome 唯讀查看）。
- 免費檢查（models.get，不產生內容、不收費）：同一把 API key 用在 Vertex AI 時被拒絕，HTTP 401 "API keys are not supported by this API"。

## 決策

1. **連線方式**：Vertex AI（`endpoint` = `vertex`），project `lyrical-link-483206-r8`（使用者的 My First Project；不是憑證），location `global`。
   模型 ID 仍是 `gemini-4-argon`。帳單走 Google Cloud 的帳單帳戶，也就是使用者的試用抵免額。
2. **憑證**：使用者自己登入的 Application Default Credentials。
   - 主 session 經使用者同意，用 Homebrew 安裝 Google 官方的 `gcloud-cli`。
   - 登入（`gcloud auth application-default login`）與設定 quota project 由使用者自己在終端機執行，瀏覽器裡的授權也由使用者自己按。
   - 程式只透過 SDK 使用這份憑證，從不讀出、顯示、記錄或保存它。
   - 033 的 API key 與 `tools/with-gemini-key` 不再使用。鑰匙圈裡的 key 要不要刪由使用者決定。
3. **單價**：Vertex AI 的官方價格頁（cloud.google.com/vertex-ai/generative-ai/pricing，2026-10-31 用 Chrome 讀取），global 端點，每 1M tokens：

   | 期間 | input | cached input | output（含 thinking） |
   |---|---:|---:|---:|
   | 到 2026-11-30 | $2.00 | $0.10 | $10.00 |
   | 2026-12-01 起 | $4.00 | $0.20 | $20.00 |

   - 與 033 的數字相同，所以設定檔的單價與 price_changes 不變（非 global 端點貴 10%，本實驗用 global）。
   - 價格頁的註腳寫：促銷期間部分模型「淨支出可享 50% 的抵免額」。帳上照價格表計算，不扣這個促銷，所以只可能偏高。
   - 價格頁也寫：完成內容超過 32,000 tokens 時，即使因逾時失敗也要付費。本實驗的輸出上限是 32,768，回覆不會比這長。
4. **探測**：使用者同意用 Vertex AI 跑同一個已批准的合成範例探測（「探測費用也同意」）。
   之前估計 $2–6 是假設 Vertex 單價較高；查到的價格與 Gemini API 相同，所以估計仍是 $1–3。

## 為什麼

- 試用抵免額可以付 Vertex AI 的費用，不用另外花真的錢；Gemini API 的預付點數則要另外購買，而且試用抵免額通常不能用。
- 程式原本就支援 Vertex AI（032 的原始設計），只要改設定檔。

## 放棄的替代方案

- **A：在 AI Studio 購買 Gemini API 預付點數**：要花真的錢（最少 $5，整個實驗估計 $60–240），點數一般不退費。使用者選了 B。
- **Vertex AI 綁定 service account 的 API key**：要建立 service account 並設定權限，比使用者自己登入更複雜。

## 對實驗的影響

- 模型、設定、預算、規則與單價都不變；只換了連線方式、憑證與付款來源（試用抵免額）。
- 資料（凍結 snapshot 中的合成 telemetry，沒有個人資料）送到使用者自己 project 裡的 Vertex AI；label 與 ground truth 仍然不會送出。
- 033 那次被拒的探測沒有產生任何回覆，不算任何結果，也不影響之後的版本釘選（還沒有釘住任何版本）。
