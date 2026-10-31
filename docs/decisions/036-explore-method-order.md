# 036 — 032 的探索性實驗：三個方法實際的執行順序是 dump-all → retrieval → agent，與 032 §2 登記的不同；照實記錄，不重跑

- 狀態：Accepted（2026-10-31，主 session 記錄；在看到任何 held-out 結果之前發現）。
- 影響範圍：只記錄執行的事實。032–035 都不改；本文件只新增（033 第 6 點）。程式、設定、預算、prompt、評分都不變。

## 背景

- 032 §2 登記的順序是「retrieval → agent → dump-all（與 Pilot 相同）」，也就是正式 held-out 執行方法的順序。
- 主 session 寫的執行腳本（`data/external/logs/explore-032/run-set.sh`，不進 git）卻依 dump-all → retrieval → agent 的順序跑：
  - Pilot 第 1 題（2026-10-31T08:46Z）與 Pilot 其餘 9 題（08:52Z–09:26Z）；
  - held-out 50 題（09:26:59Z 開始）。
- 主 session 在 held-out 的 dump-all 剛開始時（第 1 個 attempt 還在等回覆）重讀 032 §2 才發現。當時還沒有任何 held-out 的預測，也沒有看過任何 held-out 結果。
- 探索程式（`eval/explore.py`）本身不規定方法的順序，每個方法是一次獨立的指令。
- 本文件在發現時寫好，等 held-out 跑完（15:30:31Z）才 commit，以免在執行中切換 branch；內容只補上這一行的結束時間。

## 決策

1. **不中斷、不重跑**：held-out 照 dump-all → retrieval → agent 跑完。
2. **照實記錄**：101 寫明實際的順序與本文件。

## 為什麼

- 每次 Vertex 呼叫彼此獨立：temperature 0、seed 42，方法之間沒有共用的狀態（每個方法自己的對話、自己的 snapshot 讀取）。
  方法先跑或後跑，不會改變送出的內容，所以不預期會改變預測。
- 可能受影響的只有：
  - latency 與實際費用（Vertex 自動的 context cache、當時的負載與 rate limit 重試）；
  - 如果 Google 在實驗途中更新同名模型（035 第 3 點的限制），哪個方法落在更新之前或之後。這個風險不論順序都存在。
- 當時中斷反而更糟：會留下一個沒有結束的 attempt，INC 的那一題 dump-all 就要用掉第 2 次 attempt，
  直接動到「每個（方法, incident）一個 attempt」的規則（032 §2）。
- 探索的 Pilot 與 held-out 用的是同一個順序，兩者彼此一致。

## 放棄的替代方案

- **中斷後依 retrieval → agent → dump-all 重新開始**：見上；而且第一個 dump-all 的回覆已經付費，只能丟掉不看。
- **全部重跑**：每個（方法, incident）只跑一次（032 §1 第 2 點），不重跑。

## 另記：032 §3 設定的確認（032 §6 第 4 步）

- 使用者沒有另外回覆一句「確認第 3 節的設定」。
- 主 session 在探測報告裡寫明「temperature 0、seed 42、thinking low 照原設定，不用改」，使用者接著批准 Pilot 的總額（「批准上限 $150」）。
  這裡把它記為使用者的確認；設定檔從探測之後沒有改過設定。

## 對實驗的影響

- 預測內容不預期受影響；latency 與成本照實報告。
- 這是事前登記與實際執行的差異，101 必須列出。
