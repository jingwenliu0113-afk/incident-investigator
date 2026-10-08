# 024 — 各方法的預算、用量與可見資料範圍的報告

- 狀態：Accepted（2026-10-08）；在任何方法對正式 incident 執行之前寫定。只增加報告內容，不改任何指標、預算數值、方法或 Gate 判定。
- 影響範圍：SPEC Core §7「每組都報：可見資料範圍、retrieval budget、tool-call budget、token budget、latency、cost；避免 Agent 因為『看了更多資料』而不公平勝出」；
  `python -m eval run` 寫出的檔案與 `python -m eval score` 的表。

## 背景

- decision 013：每個 prediction 帶 `usage`（tokens in / out / proxy、工具呼叫、retrieval 次數、latency、成本）。
- decision 019–021：LLM 方法的 transcript 帶 exposure log（看過的 record id、trace id、概覽的 `stats:` 格子）。
- 但評分表沒有彙整這些數字；預算只存在 `eval/llm_methods.json`，而這個檔案可能在兩次執行之間改變，事後無法確定某份結果用的是哪組預算。

## 決策

1. **執行設定與結果一起保存**：每次 `eval run` 在寫任何 prediction 之前，在方法的結果目錄寫 `run_config.json`：
   method、set、model（LLM 方法；統計 baseline 為 null）、該次實際使用的預算、可見資料範圍的固定描述。
   - 統計 baseline 沒有預算（`{}`）；dump-all：`proxy_tokens`（B）；retrieval：`queries`（q）、`k`；agent：`tool_calls`、`proxy_tokens`、`turns`。
2. **評分表新增一節「Budgets, usage and visible data」**：
   - 可見資料範圍的描述、model、預算（取自 `run_config.json`；沒有這個檔案的舊結果寫 `not recorded`，不從目前的設定檔補）。
   - usage 每一欄在被評分的 incident 上的 n / mean / median / max；cost 另報總和（有任何一個 incident 的 cost 為 null 時總和寫 `-`）。
   - 有 transcript 的方法：停止原因的次數（submitted、submitted_after_limit、turn_limit、tool_budget、invalid_submission、no_submission）。
3. **量測的可見資料**（有 exposure log 的方法，每個 incident）：
   - `records_seen`：exposure 中不同的 span / log / metric point id 數；`records_share`：占 snapshot 的 span + log + metric point 總數的比例。
   - `overview_share`：看過的「服務 × 分鐘」格子占全部格子（snapshot 服務數 × 時間窗分鐘數）的比例；`stats:*`（完整概覽）= 1。
   - 統計 baseline 沒有 exposure log：它讀所有 record，但只用每服務每分鐘的彙總值；表上以描述呈現，不給數字。
   - 這些數字描述「方法實際看了多少」，**不是指標**，不進任何方法比較或 Gate 判定。

## 為什麼

- 預算與實際 exposure 並列，讀者才能判斷 Agent 的勝出是否只是看了更多資料（SPEC §7 的目的）。
- 預算跟結果一起保存：設定檔之後改了，舊結果的報告仍然正確；也能在 held-out 協定中檢查所有方法用的是凍結的設定。

## 放棄的替代方案

- **把 exposure 當成指標，或用它調整分數**：等於新增一個要事先登錄的比較，SPEC 沒有要求；只報告。
- **評分時從 `eval/llm_methods.json` 讀預算**：設定改了之後，舊結果的表會顯示錯的預算。

## 對實驗的影響

- 只影響報告；從第一張 Pilot 表起就有這一節。各方法本身、預算數值（仍待使用者決定，NEXT A1）與評分都不變。
