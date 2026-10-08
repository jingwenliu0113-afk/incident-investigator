# 015 — Leakage audit v1 與 Easy / Medium / Hard

- 狀態：Accepted（2026-10-08）；在任何 Pilot incident 的 snapshot 產生之前寫定。v1 可以在 Pilot 稽核後修訂一次（寫 decision log），held-out 之前凍結。
- 影響範圍：SPEC Core §6（leakage audit）、incident 的難度分級（之後報告依難度分層）

## 背景

SPEC §6 至少要測：fault 名稱、服務名稱、明顯的錯誤訊息、fault flag metadata、文件中直接洩漏答案的描述；必要時分 Easy / Medium / Hard。
normalize（decision 011）已經在發布前擋下詞彙與 flag metadata；稽核量的是「剩下的、刻意保留或無法移除的」線索有多明顯。

## 決策

稽核在 **ground-truth 側**執行（`eval.leakage.audit`、`python -m eval leakage --set pilot`），因為它要用 label 的 fault 時間。
每個 incident 寫 `ground_truth/incidents/<INC>/leakage_audit.json`；結果表 `data/external/results/<set>/leakage.md` 只有難度與計數。

1. **可讀文字**：span 的 status message 與 event 名稱、log 的 body 與 event name。每段文字做成樣板（UUID、16 位以上的 hex、數字遮掉）。
2. **時段**：label 的 fault_start / fault_end（host 時鐘）加上該 run 量到的時鐘差，換到 snapshot 的資料時鐘；分 normal / fault / recovery。
3. **fault 專屬樣板**（「明顯的錯誤訊息」）：fault 期間出現、normal 期間從未出現的樣板，記錄次數、發出的服務、是否為 error 等級
   （span status = error、log severity ≥ WARN、`exception` event）。
4. **服務名稱**：fault 專屬樣板中，字面上提到 origin 服務的（`origin_named`）。
5. **fault 名稱與 flag metadata**：所有可讀文字的詞彙命中數（應為 0；不是 0 代表 normalize 有漏洞，該 incident 修好之前不得使用），
   以及 normalize report 的 `new_attribute_keys`（soak inventory 沒見過的 key，人工檢查是否只在 fault 時出現）。
6. **文件**：repo 的文件（decision log、NEXT、research notes）寫明了某些 incident 的 fault。控制方式：方法只能讀 snapshot（`open_snapshot`），
   不掛載 repo；任何 prompt / 工具說明都要通過詞彙檢查並且不描述收集協定（decision 011 §5、014）。這一項以檢查清單記錄，不自動計分。
7. **難度**（只依第 3 點，事先固定）：
   - **Easy**：有 error 等級的 fault 專屬樣板是 **origin 自己**發出的（origin 直接說出問題）。
   - **Medium**：有 error 等級的 fault 專屬樣板，但都來自其他服務（只看得到下游症狀）。
   - **Hard**：沒有 error 等級的 fault 專屬樣板（只能從 metric、延遲或流量變化推論）。

## 為什麼

- 「只在 fault 期間出現」是一個不需要人工判斷、又直接對應「明顯的錯誤訊息」的定義；誰發出它決定了要多少推理才能找到 origin。
- 用樣板而不是原文，避免 id 與數字讓同一種訊息看起來每次都不同。
- 在 ground-truth 側跑：稽核本身需要答案，結果不能回到 Agent 可讀的地方。

## 放棄的替代方案

- **人工逐筆判斷**：Pilot 之後的 incident 數量會讓它不可重現；人工檢查保留給 `new_attribute_keys` 與 Easy 的抽查。
- **依 fault 類型直接分級**（例如所有 error_response 都是 Easy）：同一類型在不同服務的 telemetry 差很多（例如 adFailure 只有 1/10 失敗）。

## 對實驗的影響

- 每個 Pilot incident 在 label 之後跑一次稽核；詞彙命中不是 0 的 incident 不進任何評分。
- 報告依難度分層列出各方法的分數（SPEC §6「必要時分 Easy / Medium / Hard」）。

## 修訂 1（2026-10-09，任何 Pilot incident 之前；只用無 fault 的資料）

- **發現**：在無 fault 的校準 snapshot（soak #3）上試跑，假設一個 10 分鐘的 fault 窗，得到 472 個「fault 專屬樣板」（應該接近 0）。
  原因是樣板只遮數字，商品 id（例如 `0PUK6V6EV0`）被切成 `<n>PUK<n>V<n>EV<n>`，recommendation 的 log 每種商品組合都變成一個新樣板。
  error 等級的 fault 專屬樣板在兩個 soak 上都是 0，所以難度判定沒有受影響；但稽核清單（最多列 50 個）會被這種雜訊佔滿。
- **修訂**：樣板中**含數字的整個字**（字元 `A-Z a-z 0-9 _ . -`）遮成 `<n>`（原本只遮數字本身）；UUID 與 16 位以上 hex 的規則不變。
  修訂後同一個無 fault snapshot 只剩 2 個 fault 專屬樣板（都不是 error 等級）。
- 只用無 fault 資料、在 Pilot 之前，不占「Pilot 稽核後修訂一次」的額度。
