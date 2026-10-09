# 026 — Held-out 協定的程式實作與解讀

- 狀態：Accepted（2026-10-09）；在任何 held-out 資料、任何 Pilot 方法結果之前寫定。只把 decision 023 落成程式，**不改任何規則、門檻、指標、切分或預算**；
  023 有歧義的地方一律取最保守的讀法（拒絕而不放行），每一項解讀都列在下面。
  **補充（2026-10-09，合併 main 的 decision 025 修訂 2、3 之後）**：解讀 29（電力條件）、30（撤回）把 025 的規則落實到 held-out；只拒絕更多，不放寬任何條件。
- 影響範圍：`collect/heldout.py`、`collect/freeze.py`（新增）；`collect/__main__.py`（`run|next|status --set heldout`、`heldout-plan`、
  `heldout-freeze`、`heldout-list`、incident 指令的 freeze 檢查）；`collect/rungroup.py`（`Plan.slot`、`Plan.freeze_sha256`）；
  `collect/pilot.py`、`collect/labeling.py`、`collect/layout.py`；`eval/runner.py`、`eval/__main__.py`；`agent/harness.py`（`CallError`）；
  `baselines/dump_all.py`、`baselines/retrieval.py`。

## 背景

- decision 023 已 Accepted（使用者 2026-10-09：K = 5，其餘照保守預設）。023「對實驗的影響 / 程式」列出現在就能寫、不需要 lock 的程式：
  `PLANS["heldout"]` 與 slot 清單的產生、freeze 紀錄與檢查、collect 的拒絕規則與以 slot 計算的無效上限、`heldout_incidents.json`、eval 的前置檢查與重試規則。
- 標「Pilot 後定稿」的內容（fault 清單、`PLANS["heldout"]` 的實際內容、slot 清單、freeze 紀錄）現在**不能**產生：Pilot 正在收集。
  這裡只寫出產生它們的指令，以及在它們不存在時一律拒絕的檢查。
- 使用者決定（2026-10-09）：付費 LLM API 方法延後（NEXT A1）；Pilot 驗證失敗的 fault 移除並列出；需要新 policy 或改 env lock 時排除受影響的 incident；
  不付費重跑；真實 snapshot 不進 git。

## 決策

### 1. 檔案與位置

| 檔案 | 位置 | 進 git | 寫入者 |
|---|---|---|---|
| held-out plan（`PLANS["heldout"]`） | `docs/heldout/plan.json` | 是 | `collect heldout-plan` |
| slot 清單 | `docs/heldout/slots.json` | 是（與 freeze 同一個 commit） | `collect heldout-freeze` |
| freeze 紀錄 | `docs/heldout/freeze.json` | 是（與 slots 同一個 commit） | `collect heldout-freeze` |
| run group 的 slot 與 freeze sha | `ground_truth/run_groups/<RG>/run.json` 的 `plan.slot`、`plan.freeze_sha256` | 否 | `collect run --set heldout` |
| held-out 清單 | `data/external/ground_truth/heldout_incidents.json` | 否 | `collect heldout-list` |
| 嘗試紀錄 | `data/external/results/heldout/<method>/attempts.jsonl` | 否 | `eval run --set heldout` |
| 執行鎖 | `data/external/results/heldout/<method>/run.lock` | 否 | `eval run --set heldout` |

- 四個 JSON 紀錄都以 `json.dumps(doc, indent=2) + "\n"`、exclusive create（`"x"`）寫一次，sha 一律是 `env.lock.sha256_path`。
- 進 git 的三個檔案只描述設計，**不得出現任何 `INC-` / `RG-` id**（`tests/test_repo_hygiene.py` 檢查）。
- Pilot 的 run.json 沒有 `slot` / `freeze_sha256` 這兩個鍵，形狀與今天完全相同；`injection.json` 不變（schema 是 `additionalProperties: false`）。

### 2. 解讀（每一項都取保守的一側）

1. **`PLANS["heldout"]`** 是進 git 的 `docs/heldout/plan.json`，由 `collect heldout-plan` 從 `PLANS["pilot"]` 加上人寫的修正與移除產生。
   `planned("heldout", …, project_dir=…)` 只從明確給定的專案目錄讀；沒有檔案或沒有 `project_dir` 時 LookupError。
2. **023 第 6 行「Pilot 後定稿」**要等 Pilot 收集、review、leakage audit **與 LLM 方法試跑**都完成。所以 `heldout-plan` 與 `heldout-freeze`
   都要求：`eval/llm_methods.json` 已 approved（含 model、model_version、temperature），而且每個已登錄的方法都有 `results/pilot/<m>/scores.json`。
   付費 LLM 方法延後期間，**plan、freeze 與 held-out 收集都被 NEXT A1 擋住**。
3. **「只吸收 Pilot label review 發現的差異」**以程式檢查。修正欄位用 review 的差異欄位名：`affected_services`、`user_symptom`（整個 `{kinds, description}`）、`notes`。
   一個值只有在以下全部成立時才能吸收：
   - 來自 `fault_exercised = true` 而且 `saw_method_outputs = false` 的 review；
   - 該 fault 所有這樣的 review 對這個欄位的值都一致；
   - 與 a priori 不同；
   - 修正值等於它（list 排序後比較）。
   每一項都要有非空的理由；修正後的 entry 仍要通過 PILOT entry 規則（origin ∈ affected ⊆ 18 個 SUT 服務；symptom 只能是 `["none"]` 或不含 none；詞彙內）。
   origin、flag、variant 永不改（018 §2）。沒有吸收的差異自動寫進 plan.json 的 `not_absorbed`，**只有計數與原因，不寫值**。
4. 進 git 的理由與值都不得含 `INC-` / `RG-` id。
5. **移除只能依 Pilot 驗證失敗**（使用者決定 5），每種依據都對照 Pilot 資料：
   - `not_exercised`：沒有 exercised 的 review，而且至少 2 個未觸發的 review（016 §5 的重收已做過）；
   - `invalid_rate`：至少 `MAX_INVALID_ATTEMPTS`（3）個非 valid 的 Pilot run group，而且沒有 exercised 的 review；
   - `lexicon_hits`：有 Pilot incident 的詞彙命中 > 0，而且沒有任何 exercised review 的 incident 是乾淨的；
   - `pipeline` / `label`：自由文字的依據，必須指名 HEAD 上存在的 decision 檔，記為人的聲明。
   方法分數永遠不是依據；plan.json 記錄寫入當時有 Pilot 結果的方法。移除時記錄證據的計數。
6. **進入條件（§1）**：held-out 的 fault 至少要有一個 Pilot incident 有 `label.reviewed.json` 且 `fault_exercised = true`。
   「Pilot review 完成」= 每個 valid 的 Pilot incident（包括未觸發的）都有 `label.reviewed.json` 與 `label_review.json`。
7. **freeze 的身分（「commit 與 env lock 的 sha」、「checkout … 不符」），預設拒絕**：紀錄寫 `frozen_from_commit`（freeze commit 的父 commit）與它的 tree。
   `git diff --name-status frozen_from_commit <commit>` 只允許三種變動：
   - `M NEXT.md`；
   - `A docs/heldout/slots.json` 與 `A docs/heldout/freeze.json`；
   - `A docs/decisions/NNN-*.md`。
   其他一切（程式、測試、SPEC、README、docs、每一個既有的 decision）都必須逐位元相同。另外還要求：
   - checkout 乾淨（沒有 untracked、沒有 assume-unchanged / skip-worktree 標記、程式目錄下沒有被 ignore 的 `.py`）；
   - `frozen_from_commit` 是 HEAD 的祖先；
   - slots.json 與 freeze.json 各只被一個 commit 碰過，而且是同一個 commit、第一個父 commit 是 `frozen_from_commit`（寫一次）；
   - plan、slots、freeze 都已 commit，且與 HEAD 的 blob 相同；
   - 紀錄中的 tree、decision blob、env lock、policy、llm 設定與實際相符（多加的防竄改檢查，不是新規則）。
   **後果**：freeze 之後既有的 decision 檔不能再改，新的紀錄（held-out 收集紀錄、bug log）只能寫進 NEXT.md 或**新的** decision 檔
   （例如不再追加 009「收集結果」或 016 §5）；使用者的 held-out review 也需要乾淨的 checkout。
8. env lock、policy、llm 設定的 sha 依 023 §6 寫進紀錄，在寫入時檢查一次，之後由預設拒絕的 diff 釘住。資料與紀錄的比對仍保留：
   run.json 的 env lock、normalize_report 的 policy、run_config 的 freeze 與清單 sha。
9. freeze 要求 `llm_methods.json` 已 approved，且 model、model_version、temperature 非 null（這些欄位在批准時加入）。
10. **「Pilot 上修訂一次」**涵蓋 011、013、014、015、017、019、020、021、022：每一項都要宣告 used（指名 frozen commit 中的 decision 檔，人的聲明）或 waived。
    013 必須是 used（023 §7 用掉）；policy v1 時 011 必須 waived，v2 時必須 used（023 §6）。
11. **以 slot 計算的無效上限**：累計該 slot 所有非 valid 的 run group（invalid 與所有 aborted_*），與 Pilot 的規則相同；在 run group 產生之前就被拒絕的 run 不算。
12. **slot 狀態的優先順序**：filled > needs_person > closed > open。以下是 ValueError（exit 2）：
    - 一個 slot 有超過 1 個可用的 incident；
    - 一個 slot 有超過 2 個未觸發的 incident；
    - 任何損壞或不符的 held-out 紀錄，包括 freeze sha 不是目前的 freeze（直接停止，不過濾）。
    需要人處理時是 RuntimeError（exit 3）：3 個以上 slot 待人處理時 `next` 停止；沒有 open 的 slot、但有 1–2 個待人處理時也停止，不回報「收齊」。目前沒有解除機制。
13. **未觸發的 slot**：用新的 run group、新的 seed 再收一次；再次未觸發就預設關閉並列出（023 §5.3）。詞彙命中的 incident 排除並列出，該 slot **不重收**（023 沒有給重收規則）。
14. `collect run --set heldout` 自己算出下一個 open 的 slot，`--flag` / `--variant` 必須等於它；slot 與 freeze sha 寫進 run.json 的 `plan`，永不寫進 injection.json。
15. **seed**：`--set heldout` 拒絕 `--seed`。`fresh_seed` 用 SystemRandom 抽，直到沒有任何 set 的 run.json 用過。Pilot 的 seed 路徑不變。
16. **slot 順序**：Fisher–Yates，只用 `Random(20261009).random()`（CPython 對整數 seed 保證這個序列；`random.shuffle` 的演算法沒有這個保證）。
    slots.json 必須等於重新產生的清單，所以順序不能手改。slot 數 = held-out fault 數 × K，編號 H01 起兩位數。
17. **重試**：每個（方法, incident）最多 `HELDOUT_MAX_ATTEMPTS = 2` 次。只有 `CallError` 且 reason 是 `api_error` / `transport_error` 時重試；
    reason 由 adapter 依它看到的停止原因設定，永不看輸出內容。`CallError` 定義在 `agent/harness.py` 的模型介面旁，帶著失敗前的用量。可在同一次執行內重試。
    以下情況會關閉該 incident、不再有 prediction：其他任何錯誤、不合格的 prediction、中斷的嘗試（有 start 沒有 end）。每次嘗試都記錄用量。
18. **只跑一次**：有 prediction 或嘗試紀錄已關閉的 incident，該方法在 held-out 上永不再跑。續跑需要完全相同的 `run_config.json`。
    每個方法一個 O_EXCL 的 `run.lock` 防止同時執行；程序只刪自己的 lock，被中止的程序留下的 lock 由人處理。prediction 與 transcript 原子寫入、永不覆寫。
19. **沒有 prediction 的 incident**：在 023 §5 的重試規則之後仍沒有 prediction 的列表內 incident，計為**放棄作答**：每一層都算錯、留在分母（013 §2）、
    失敗類別 `no_answer`（022），並列出它的嘗試結果。所有方法（包括 stat-anomaly）都一樣。這是從 013 §2 與 023 §6（「Gate 用第一次的結果」、
    「incident 清單永不因 held-out 結果修改」）推得的，在任何 held-out 資料之前固定；**使用者可以在 freeze 之前推翻**。
    只有在還有列表內 incident 的嘗試沒結束時才拒絕評分。
20. **每個 held-out 的 eval 路徑**（leakage、run、score、gold-todo、對 held-out incident 的 gold-add、compare）第一個陳述都是 `heldout_guard`，在任何 mkdir 或寫入之前。
    它要求 freeze 檢查通過，除了 leakage 以外還要求驗證過的 `heldout_incidents.json`。held-out 時 `project_dir=None` 是 PermissionError。
    清單寫出之後 `eval leakage --set heldout` 拒絕（清單釘住了 audit）。
21. collect 的 `normalize`、`replay`、`label`、`process`、`review-sheet`、`review` 作用在 held-out incident 時，要求 freeze 檢查通過：
    held-out 資料只由凍結的程式產生，使用者的 held-out review 也需要乾淨的 checkout。
22. freeze 紀錄存在之後，`collect run --set pilot` 拒絕：Pilot 在 freeze 時關閉。
23. held-out 的 `status` / `next` 只顯示 slot、fault、狀態、計數、非 valid 的 run group id 與電力設定；**不顯示 incident id 與 valid 的 run group id**。
    `heldout-list` 只印數量。NEXT 的紀錄只寫 slot 與非 valid 的 run group id。
24. **`heldout_incidents.json`** 寫一次，釘住每個列表內 incident 的 8 個檔案的 sha：label、label.reviewed、label_review、leakage_audit、manifest、
    normalize_report、injection、run；也記錄每個 held-out run group，之後多出來的會被發現。以下任一成立時拒絕：
    - 有 slot 是 open 或待人處理；
    - 有 incident 還沒 process、audit 或 review；
    - 有 review 的 `saw_method_outputs` 不是 false；
    - `results/heldout` 中有 `leakage.md` 以外的任何東西。
    任一個 held-out run group 不符合以下時也拒絕：
    - freeze sha、env lock、normalize 的 policy 與 freeze 紀錄相同；
    - run 與 normalize 的 commit 乾淨，且與 frozen commit 只差在允許的路徑、包含這份 freeze 紀錄；
    - 在 `frozen_at` 之後開始；
    - RG 編號大於每一個 Pilot run group；
    - fault 長度與 normal / recovery 參數符合 023 §3；
    - label 等於 plan 的 entry；`manifest.project` 等於 run 的 provenance；
    - 所有 run group 之間 seed 與 incident id 不重複。
25. **使用者決定 6 是約束性規則**：需要新 policy 或改 env lock 時排除受影響的 incident。在 freeze 修訂指令存在之前，任何不符都讓收集、清單與 eval 停止（fail closed，023 §6）。
    將來寫這個指令時，必須排除受影響的 incident，永不混用兩種設定。
26. **仍存在的暴露**：slots.json 進 git，id 又依收集順序配發，所以同時有 git 與資料目錄的人可以把 held-out id 對應到 fault。
    incident id 永遠不在任何方法的 prompt 裡（有測試）；方法看不到 git 或 slot 清單。023 §4 要求清單進 git，所以接受這個暴露。
27. 因為 freeze 釘住所有程式，held-out 結果需要的一切都必須在 freeze **之前** commit：模型 API adapter、Gate 條件 2 與 3 的程式、各 fault 等權平均與缺格表、
    013 正式版。NEXT 把它們列為 freeze 前的項目。
28. **這一批不做 held-out loop**：023 的「程式」沒有列它；它在 A1 與 Pilot review 之前無法執行；而且要改 `pilot_loop.py`（正在跑 Pilot 的檔案）。
    手動的 `next` → `run` → `process` → `eval leakage` 就能完成 held-out 收集。
29. **電力條件（decision 025 修訂 2、3：高效能模式 + AC，時間窗內每分鐘取樣）對 held-out 一樣成立**。held-out 沒有自己的收集路徑：
    `collect run --set heldout` 用同一個 `LiveStack.preflight`（開始時讀 `pmset`，不符就拒絕）與同一個 `run_group` / `_judge`
    （時間窗內任何一筆樣本不符或沒有樣本 → `power_not_formal`，run 無效）。有測試守住這兩點。
    - `power_not_formal` 的 run group 和其他無效 run group 一樣，算該 slot 的一次無效嘗試（解讀 11），不會進清單。
    - `heldout-list` 另加一項防竄改檢查（不是新規則）：每個計入 slot 的 valid held-out run group，run.json 必須記錄符合正式條件的開始電力
      （`provenance.machine.power`）、`power_samples` ≥ 1，而且沒有 `power_not_formal`；不符就拒絕寫清單。撤回的 run group 不檢查這一項（撤回的原因可能正是電力）。
30. **撤回（decision 025 修訂 3）對 held-out 一樣成立**。`collect.pilot.withdraw` 對任何 set 都可用：在 ground-truth 側寫 `run_groups/<RG>/withdrawn.json`，所有檔案保留。
    - 撤回的 held-out run group **不填 slot、不算該 slot 的無效嘗試**；slot 照常重收（新的 run group、新的 seed）。
    - 它的 incident 不需要 process、audit、review；`eval leakage --set heldout` 跳過它。
    - `heldout_incidents.json` 把它列在 `excluded`（`reason` = `withdrawn: <原因>`，含 slot 與 run group id），另記 `withdrawn_run_groups`。
      因此它不進任何方法的執行與評分；評分報告的「Not listed」列出它。
    - **撤回不豁免任何檢查**：撤回的 run group 仍是磁碟上的 held-out run group，解讀 24 的 run group 檢查（freeze sha、env lock、乾淨且凍結的 commit、
      freeze 之後開始、編號、023 §3 的長度、seed 不重複）照樣適用。撤回紀錄與 run.json 不符（run group id、incident id、非 valid）時 fail closed。
    - `collect status --set heldout` 只顯示撤回的**數量**，不顯示它的 id（解讀 23）。
    - **清單寫出之後不能再撤回 held-out run group**（023 §5.5、§6：清單永不因之後的事件或結果修改）：`withdraw` 拒絕；若仍有 `withdrawn.json` 被加入或移除，
      `load_heldout_incidents` 拒絕，所有 held-out 方法執行與評分停止，由人以新的 decision 決定。Pilot 的撤回不受影響。
    - **Pilot 側**：撤回的 Pilot incident 不是 held-out plan 的證據。`pilot_evidence` 不計入它（不算 valid、review 或無效 run group）；
      `pilot_problems` 與 plan / freeze 的前置檢查不要求它的 review 與 leakage audit（例如真實 Pilot 撤回的 RG-002）。

## 為什麼

- **預設拒絕**：023 要求 checkout、方法程式、prompt、設定、模型與 freeze 紀錄相符，但紀錄不能包含自己的 commit。
  只允許少數明列的路徑變動，是唯一能同時釘住「全部程式」與「之後還能記 NEXT / 新 decision」的做法；列舉「要檢查哪些檔案」容易漏。
- **兩個 writer 都等 LLM 試跑**：023 第 6 行把 LLM 方法試跑列為「Pilot 後定稿」的前提；提早寫 plan 會讓 plan 與 freeze 之間出現可以調整的空檔。
- **以 Pilot 資料檢查修正與移除**：023 §1 的「只吸收 review 發現的差異」、使用者決定 5 的「只依驗證失敗移除」都是可以機械檢查的條件；交給人的自由文字就無法事後稽核。
- **run group 的 commit、時間、編號三重檢查**：一個把 held-out 欄位全部偽造的 Pilot run group，仍然會因為 commit 不含 freeze 紀錄、開始時間早於 freeze、編號小於 Pilot 而被拒絕（SPEC §5、§10）。
- **放棄作答留在分母**：如果把沒有答案的 incident 從分母拿掉，清單就會因結果而改變，這是 023 §6 禁止的；013 §2 已規定放棄作答算錯。
- **清單寫出後不再撤回**：撤回若能在清單之後（也就是可能在看過方法結果之後）發生，就等於依結果修改測試集；寫出之前的撤回只依收集條件，沒有任何方法結果。
- **電力證據在清單時再查一次**：preflight 與時間窗判定已經保證這件事；清單時再查，是讓不是由這套程式產生的紀錄無法混進 held-out。

## 放棄的替代方案

- **把 `PLANS["heldout"]` 寫成 Python 常數**：要改程式才能寫入，而 freeze 釘住程式；用 JSON 檔也讓 plan 與 freeze 的 sha 各自獨立。
- **freeze 紀錄只列要檢查的檔案與 sha**：漏列的檔案改了不會被發現。
- **freeze 後允許追加既有 decision**：會讓 decision 檔與 frozen commit 不同，無法區分「追加紀錄」與「改規則」。
- **無效上限沿用以 fault 計算**：那是為 K = 1 設計的，K = 5 時幾乎一定有 fault 停下來（023 §4）。
- **沒有 prediction 的 incident 從評分中排除**：清單會依結果改變。
- **在這一批寫 held-out loop**：理由見解讀 28。

## 對實驗的影響

- 不改任何協定、門檻、指標、切分、預算或 Gate 定義；Pilot 的收集、run.json 形狀與評分路徑不變（回歸測試守住）。
- **held-out 的 plan、freeze 與收集都被 NEXT A1（付費 LLM 方法延後）擋住**；在 freeze 紀錄存在之前，所有 held-out 收集與方法執行一律拒絕。
- freeze 之前必須 commit 的項目：模型 API adapter、Gate 條件 2 / 3 的程式、各 fault 等權平均與缺格表、013 正式版、需要乾淨 checkout 的 review 說明。
- 測試全部用 synthetic / tiny generated fixture，沒有真實 snapshot 進 git。
