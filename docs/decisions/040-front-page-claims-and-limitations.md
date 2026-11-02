# 040 — 首頁的兩處說法與「Limitations / 限制」一節

- 狀態：Proposed（2026-11-02）；合併到 main 即為 Accepted。
- 影響範圍：main 修改 `.github/README.md`（兩處說法、新增「Limitations / 限制」一節、decision log 的份數 41 → 42）與 `NEXT.md`，新增本文件。
  程式、測試、SPEC、根目錄 README、既有 decision、資料與結果都不變；tag `heldout-final` 不動。

## 背景

- 首頁（037）有兩句話說得比 repo 自己的紀錄更滿：
  1. 「The method looked at the right data and still drew the wrong conclusion.」（中文版：「方法看過正確的資料，仍下錯結論」）。
     022 §2 的「看過」是：exposure 裡有 origin 服務在故障期間的任何紀錄、origin 的 metric series，或 origin 在故障期間的每分鐘統計；
     dump-all 與 retrieval 的每分鐘概覽（`stats:*`）涵蓋所有服務，一律算看過（`eval/failures.py:21-47`）。
     其中 metric series 不看時間（`eval/failures.py:40-42`）：series 只是 metadata（服務、metric 名稱、kind、unit、attributes；`agent/tools.py` 的 `list_series`），
     agent 只呼叫 `list_series` 也會把 origin 的 series id 記進 exposure（`agent/tools.py:166-176`）。所以算作「看過」的 exposure 不一定含有故障期間的資料。
     022「已知限制」自己寫明，這比「看過能證明故障的紀錄」寬鬆，`seen_misread` 可能包含只看到 origin 正常 span 的情況。
  2. 「There are 10 fault types」（中文版：「10 種故障」）。實際是 10 個故障（`docs/heldout/plan.json` 的 10 個 entry，`docs/heldout/slots.json` 每個 5 個 slot），
     分屬 7 種 fault type（`collect/labels.py` 的 `FLAG_FAULT_TYPES`；016 §4「9 種 fault_type 中的 7 種」）。
- 首頁沒有寫出 decision 裡已經記錄的幾項限制（label 的慣例、「看過」的定義、預算、檢定力、單一標註者、注入的殘字），
  也沒有寫出「沒有無故障的對照」與「模型可能事先知道公開的故障情境」。

## 決策

1. **兩句改寫**（英文與中文同步）：
   - 「The method looked at…」改成：那些事故裡，方法的 exposure 紀錄（方法看過哪些資料）至少有一項依偏寬的「看過」定義算作看過 origin 服務：
     origin 在故障期間的紀錄、origin 的任何一條 metric series，或涵蓋 origin 故障期間的每分鐘統計（022，見「限制」第 2 點）。
     不寫成「含有 origin 在故障期間的資料」：metric series 與 `stats:*` 不看是否在故障期間（見「背景」）。
   - 粗體的那一句不變。payment-unreachable 的例子後面加「這個故障的 origin 是 label 的慣例，見限制第 1 點」：這個例子就是第 1 點的 fault。
   - 「There are 10 fault types」改成「10 faults across 7 fault types」；中文改成「10 個故障，分屬 7 種故障類型」，
     流程第 1 步的「10 種故障之一」也改成「10 個故障之一」（英文的「one of 10 faults」本來就對）。
2. **新增「Limitations」／「限制」一節**，放在「How it works」／「做了什麼」之後、「Try it」／「試跑」之前。
   6 點。數字四捨五入到小數兩位、不列 incident id（與 037 第 3 點相同），不新增實驗。037 第 3 點的首頁只轉寫 100、101；
   這一節另外轉寫 023 §2 的設計數字與 032 §2 的預算，還有一個由 100 的表推得的數字（第 3 點）。每個數字旁邊都標出處：

   | # | 內容 | 出處 |
   |---|---|---|
   | 1 | paymentUnreachable 的 origin 是 label 的慣例（checkout 呼叫錯誤的 payment 位址，payment 本身健康）；兩次執行的 agent 都是 1/5、baseline 5/5；Argon 的比較拿掉這個 fault，下界從 0.00 變成 0.13，是唯一使下界大於 0 的 fault | 016 §1；100 §5、101 §5 的各 fault 表；101 §5 的 leave one fault out |
   | 2 | 「看過」的定義偏寬；retrieval 與 dump-all 沒有 not_seen | 022 §2 與「已知限制」；`eval/failures.py:21-47`；100 §7、101 §7 |
   | 3 | qwen agent 15/50 撞到上限（submitted_after_limit 12、turn_limit 3）；Argon agent 25/49 是 submitted_after_limit；兩次執行的預算相同 | 100 §9；101 §9；032 §2 |
   | 4 | 事前估計的 Gate power 約 0.74（origin top-1 的 Δ = 0.20、一方答對另一方答錯的比例 0.30）；正式執行時 origin top-1 一方答對、另一方答錯的事故是 28 或 30 / 50（見第 3 點）；Argon 的 +0.16 小於 0.20 | 023 §2；100 §5；101 §5 |
   | 5 | 沒有無故障的對照；label review 與 gold 都只有一位標註者，gold 對方法盲、對標準答案不盲 | `docs/heldout/slots.json`（50 個 slot 都有 flag）；031 的時程表；100 §8；017 §3 |
   | 6 | productCatalogFailure 的注入殘字；讀 snapshot 文字的方法（三個 LLM 方法）看得到它，在這個 fault 的結果可能因此比沒有殘字時好，統計 baseline 只用每分鐘統計，本評測沒有量這個影響；OpenTelemetry Demo 與故障旗標是公開的，模型可能事先知道，本評測沒有檢查 | 011「已知取捨」；016「對實驗的影響」；`baselines/statistical.py`（只用 `collect.derive` 的每分鐘統計） |

3. **表中第 4 項的數字怎麼來**（唯一推得的數字，不是重算）：
   - 023 §2 的表是 Agent − stat-anomaly 的 origin_top1 paired 差異，所以那裡「兩個方法答案不一致」的事故，是 origin_top1 一方答對、另一方答錯的事故
     （paired 比較的 discordant pair）。這裡算的是同一個量：兩者都答錯的事故不算，不論答案是否相同。
   - 100 §5 的各 fault 表列出每個 fault 的 agent 與 baseline 各答對幾次（K = 5）。同一個 fault 裡，答對次數分別是 a、b 時，
     一方答對、另一方答錯的事故數是 a + b − 2x；x 是兩者都答對的事故數，介於 max(0, a + b − 5) 與 min(a, b) 之間。
   - intlShippingSlowdown（agent 1/5、baseline 4/5）的 x 可以是 0 或 1，這個數是 5 或 3；其他 9 個 fault 的 x 只有一種可能，合計 25。
   - 所以 50 個事故中有 28 或 30 個（56% 或 60%），都高於 023 §2 假設的 25–40%（模擬用 0.30）。
4. **decision log 的份數**：首頁的 41 改成 42（加上本文件）。
5. **freeze 檢查**：本文件只改 `.github/README.md`（037 起就是例外，相對凍結的 commit 仍是 `A`）與 `NEXT.md`，並新增一份 decision。
   `freeze_problems` 仍是 039 第 4、6 點的五項；三項唯讀確認與 039 相同。

## 為什麼

- 首頁是第一次看 repo 的人讀的地方，它的說法不應該比 decision 的紀錄更強。
- 限制寫在首頁，讀者不用先讀完 decision 才知道結論適用的範圍。
- 第 6 點寫出殘字可能影響哪一邊：只寫「有殘字」，讀者看不出它對哪些方法有利。
- 只轉寫、不重算：唯一推得的數字直接由 100 的表算出，算法寫在上面。

## 放棄的替代方案

- **改根目錄的 README**：freeze 時封存（030、037）。
- **只改兩句、不加限制**：讀者仍看不到 label 慣例、預算與檢定力對結論的影響。
- **第 4 點不寫推得的數字，只寫「比假設的多」**：可以，但沒有數字，讀者無從檢查「比假設的多」；數字由 100 的表直接算出（第 3 點）。
  之後若要拿掉，首頁兩種語言與本文件第 2 點的表一起改；第 3 點的算法留著，當作「比假設的多」的依據。
- **第 6 點附上 productCatalogFailure 的分數，當成殘字的影響**（例如 agent 5/5、baseline 0/5）：011、016 只對 productCatalogFailure 記錄了殘字，
  但 cartFailure 的 agent 與 baseline 在兩次執行也都是 5/5 對 0/5（100 §5、101 §5），這組對比說明不了殘字的影響；
  qwen 的 retrieval 在這個 fault 的 origin_top1 是 0.80（100 §6），也不是每個 LLM 方法都 5/5。
- **重算檢定力**（例如用觀察到的不一致比例重做 023 的模擬）：那是新的分析，要另寫事後、探索性的 decision；本文件不做。
- **收緊「看過」的定義後重新分類**：要改程式與分類結果，也是新的事後分析；本文件不做。

## 對實驗的影響

- 沒有。程式、測試、資料、label、gold、結果與 Gate 判定都不變。
