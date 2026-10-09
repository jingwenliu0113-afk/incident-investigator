# 026 — Held-out 協定的程式實作與解讀

- 狀態：Accepted（2026-10-09）；在任何 held-out 資料、任何 Pilot 方法結果之前寫定。只把 decision 023 落成程式，**不改任何規則、門檻、指標、切分或預算**；
  023 有歧義的地方一律取最保守的讀法（拒絕而不放行），每一項解讀都列在下面。
  **補充（2026-10-09，合併 main 的 decision 025 修訂 2、3 之後）**：解讀 29（電力條件）把 025 的規則落實到 held-out；只拒絕更多，不放寬任何條件。
  **修訂 1（2026-10-09，程式審查後、在任何 held-out 資料與方法結果之前）**：補充時的解讀 30 讓 held-out run group 也能撤回，
  實際上會讓 slot 不受限地重收（放寬 023 §2、§4、§5.3），改為 held-out run group 一律不能撤回（解讀 30）。
  另修正解讀 18、19、24 的實作缺口（見各項）。023 沒有涵蓋、需要使用者決定的事項列在文末「待使用者決定」，**這些事項的程式行為不變**。
  **更正（2026-10-10，合併審查；只改文字，程式行為不變）**：解讀 11 原本說 slot 的無效上限「與 Pilot 的規則相同」，合併 main 之後已不成立
  （Pilot 有 `collect ack-failures`，held-out 沒有）；解讀 11 與「待使用者決定」1 已更正並註明 Pilot 的前例。
- 影響範圍：`collect/heldout.py`、`collect/freeze.py`（新增）；`collect/__main__.py`（`run|next|status --set heldout`、`heldout-plan`、
  `heldout-freeze`、`heldout-list`、incident 指令的 freeze 檢查）；`collect/rungroup.py`（`Plan.slot`、`Plan.freeze_sha256`；修訂 1：`up_at` 先寫）；
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
11. **以 slot 計算的無效上限**：累計該 slot 所有非 valid 的 run group（invalid 與所有 aborted_*）；在 run group 產生之前就被拒絕的 run 不算。
    **更正（2026-10-10）**：原文寫「與 Pilot 的規則相同」。「非 valid」的範圍（invalid 與所有 aborted_*）與 Pilot 相同，但計數方式已不同：
    Pilot 自 016「實作說明（2026-10-09）」起有 `collect ack-failures`（ground-truth 側 `failure_acks.jsonl`），人看過 run record 之後，
    被確認的失敗 run group 不再計入，該 fault 重新計數（已用過兩次：productCatalogFailure 的 RG-004–006、intlShippingSlowdown）。
    held-out 沒有這種確認：一個 slot 的非 valid run group 一律累計、永不重新計數（`collect/heldout.py` 的 `_slot_detail`；
    `ack-failures` 只接受 `--set pilot`）。程式行為不變；held-out 是否要類似的機制是文末「待使用者決定」1。
12. **slot 狀態的優先順序**：filled > needs_person > closed > open。以下是 ValueError（exit 2）：
    - 一個 slot 有超過 1 個可用的 incident；
    - 一個 slot 有超過 2 個未觸發的 incident；
    - 任何損壞或不符的 held-out 紀錄，包括 freeze sha 不是目前的 freeze（直接停止，不過濾）。
    需要人處理時是 RuntimeError（exit 3）：3 個以上 slot 待人處理時 `next` 停止；沒有 open 的 slot、但有 1–2 個待人處理時也停止，不回報「收齊」。
    目前沒有解除機制：待人處理的 slot 會讓 `heldout-list` 一直拒絕（見文末「待使用者決定」1）。
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
    **transcript 先寫、prediction 最後寫**（修訂 1）：prediction 檔案存在就代表一次完整的嘗試。兩個檔案之間被中止時沒有 prediction、
    嘗試紀錄有 start 沒有 end（中斷），該 incident 關閉、依解讀 19 計為放棄作答；不會留下沒有 transcript 的 prediction。
19. **沒有 prediction 的 incident**：在 023 §5 的重試規則之後仍沒有 prediction 的列表內 incident，計為**放棄作答**：每一層都算錯、留在分母（013 §2）、
    失敗類別 `no_answer`（022），並列出它的嘗試結果。所有方法（包括 stat-anomaly）都一樣。這是從 013 §2 與 023 §6（「Gate 用第一次的結果」、
    「incident 清單永不因 held-out 結果修改」）推得的，在任何 held-out 資料之前固定；**使用者可以在 freeze 之前推翻**。
    以下情況拒絕評分：還有列表內 incident 的嘗試沒結束；或該方法的 `run.lock` 存在（修訂 1：執行中的嘗試與中斷的嘗試在嘗試紀錄上
    都是有 start 沒有 end，只有 lock 能區分；被中止的程序留下的 lock 由人檢查後移除，解讀 18）。
    放棄作答的列不讀未完成的嘗試留下的 transcript（stop reason、exposure 為 null）。
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

    「在 `frozen_at` 之後開始」看 run.json 的 `up_at`。修訂 1：`run_group` 在任何可能失敗的步驟（`stack.watch`、compose up）之前就記下 `up_at`，
    所以每個存下來的紀錄，包括在 compose up 之前就中止的 `aborted_error`，都有開始時間。沒有 `up_at` 的 held-out 紀錄一律拒絕，
    而且紀錄不能改、程式在 freeze 後也不能改，所以會讓清單永遠拒絕；這種紀錄只可能來自這個修正之前的程式，held-out 收集一定用 freeze 時（已含修正）的程式。
25. **使用者決定 6 是約束性規則**：需要新 policy 或改 env lock 時排除受影響的 incident。在 freeze 修訂指令存在之前，任何不符都讓收集、清單與 eval 停止（fail closed，023 §6）。
    將來寫這個指令時，必須排除受影響的 incident，永不混用兩種設定。**因為 freeze 釘住所有程式（解讀 7），這個指令只能在 freeze 之前 commit；
    freeze 之後就無法加入**（見文末「待使用者決定」2）。
26. **仍存在的暴露**：slots.json 進 git，id 又依收集順序配發，所以同時有 git 與資料目錄的人可以把 held-out id 對應到 fault。
    incident id 永遠不在任何方法的 prompt 裡（有測試）；方法看不到 git 或 slot 清單。023 §4 要求清單進 git，所以接受這個暴露。
27. 因為 freeze 釘住所有程式，held-out 結果需要的一切都必須在 freeze **之前** commit：模型 API adapter、Gate 條件 2 與 3 的程式、各 fault 等權平均與缺格表、
    013 正式版，以及文末「待使用者決定」1–3 中使用者決定要有的機制（待人處理的 slot 如何解除、023 §6 的修正路徑、held-out 撤回）。
    NEXT 把它們列為 freeze 前的項目。
28. **這一批不做 held-out loop**：023 的「程式」沒有列它；它在 A1 與 Pilot review 之前無法執行；而且要改 `pilot_loop.py`（正在跑 Pilot 的檔案）。
    手動的 `next` → `run` → `process` → `eval leakage` 就能完成 held-out 收集。
29. **電力條件（decision 025 修訂 2、3：高效能模式 + AC，時間窗內每分鐘取樣）對 held-out 一樣成立**。held-out 沒有自己的收集路徑：
    `collect run --set heldout` 用同一個 `LiveStack.preflight`（開始時讀 `pmset`，不符就拒絕）與同一個 `run_group` / `_judge`
    （時間窗內任何一筆樣本不符或沒有樣本 → `power_not_formal`，run 無效）。有測試守住這兩點。
    - `power_not_formal` 的 run group 和其他無效 run group 一樣，算該 slot 的一次無效嘗試（解讀 11），不會進清單。
    - `heldout-list` 另加一項防竄改檢查（不是新規則）：每個計入 slot 的 valid held-out run group，run.json 必須記錄符合正式條件的開始電力
      （`provenance.machine.power`）、`power_samples` ≥ 1，而且沒有 `power_not_formal`；不符就拒絕寫清單。
30. **held-out run group 一律不能撤回**（修訂 1；取代補充時「撤回對 held-out 一樣成立」的解讀）。
    - **理由**：023 沒有撤回；decision 025 修訂 3 是使用者對單一 Pilot run group（RG-002）的決定。若 held-out 也能撤回，撤回的 run group
      不填 slot、不算無效嘗試，slot 就會重收：已關閉（兩次未觸發）或詞彙命中的 slot 會重新打開，次數沒有上限，也永遠不會觸發 023 §4 的待人處理；
      撤回又可以發生在 label review 與 leakage audit（難度）之後，等於看過 ground truth 之後挑選測試集。這放寬了 023 §2（不追加收集）、§4、§5.3 與解讀 13。
      電力的情況已由 preflight 與時間窗的 `power_not_formal` 處理（解讀 29），不需要撤回。
    - `collect.pilot.withdraw` 拒絕 held-out run group（run.json 或 injection.json 任一說 held-out），什麼都不寫。
    - 仍有人手寫 `withdrawn.json` 到 held-out run group 時 **fail closed**：所有 held-out 讀 run group 的共同入口（`collect.heldout._run_groups`）拋 ValueError，
      `collect next|status|run --set heldout`、`heldout-list`、`eval leakage --set heldout` 都 exit 2；清單寫出之後 `load_heldout_incidents` 拋 PermissionError，
      所有 held-out 方法執行與評分停止。不過濾、不忽略，由人以新的 decision 決定（見文末「待使用者決定」3）。
    - 因此 `heldout_incidents.json` 沒有撤回的項目，也沒有 `withdrawn_run_groups`；`collect status --set heldout` 的計數沒有 withdrawn。
    - **Pilot 側不變**（decision 025 修訂 3）：撤回的 Pilot incident 不是 held-out plan 的證據。`pilot_evidence` 不計入它（不算 valid、review 或無效 run group）；
      `pilot_problems` 與 plan / freeze 的前置檢查不要求它的 review 與 leakage audit（例如真實 Pilot 撤回的 RG-002）。

## 為什麼

- **預設拒絕**：023 要求 checkout、方法程式、prompt、設定、模型與 freeze 紀錄相符，但紀錄不能包含自己的 commit。
  只允許少數明列的路徑變動，是唯一能同時釘住「全部程式」與「之後還能記 NEXT / 新 decision」的做法；列舉「要檢查哪些檔案」容易漏。
- **兩個 writer 都等 LLM 試跑**：023 第 6 行把 LLM 方法試跑列為「Pilot 後定稿」的前提；提早寫 plan 會讓 plan 與 freeze 之間出現可以調整的空檔。
- **以 Pilot 資料檢查修正與移除**：023 §1 的「只吸收 review 發現的差異」、使用者決定 5 的「只依驗證失敗移除」都是可以機械檢查的條件；交給人的自由文字就無法事後稽核。
- **run group 的 commit、時間、編號三重檢查**：一個把 held-out 欄位全部偽造的 Pilot run group，仍然會因為 commit 不含 freeze 紀錄、開始時間早於 freeze、編號小於 Pilot 而被拒絕（SPEC §5、§10）。
- **放棄作答留在分母**：如果把沒有答案的 incident 從分母拿掉，清單就會因結果而改變，這是 023 §6 禁止的；013 §2 已規定放棄作答算錯。
- **held-out 不撤回**：清單之後的撤回等於依方法結果修改測試集；清單之前的撤回也可能在看過 label review 與 audit 難度之後發生，
  而且讓 slot 不受限地重收。唯一的已知理由（電力）已由收集時的判定處理。
- **電力證據在清單時再查一次**：preflight 與時間窗判定已經保證這件事；清單時再查，是讓不是由這套程式產生的紀錄無法混進 held-out。

## 放棄的替代方案

- **把 `PLANS["heldout"]` 寫成 Python 常數**：要改程式才能寫入，而 freeze 釘住程式；用 JSON 檔也讓 plan 與 freeze 的 sha 各自獨立。
- **freeze 紀錄只列要檢查的檔案與 sha**：漏列的檔案改了不會被發現。
- **freeze 後允許追加既有 decision**：會讓 decision 檔與 frozen commit 不同，無法區分「追加紀錄」與「改規則」。
- **無效上限沿用以 fault 計算**：那是為 K = 1 設計的，K = 5 時幾乎一定有 fault 停下來（023 §4）。
- **沒有 prediction 的 incident 從評分中排除**：清單會依結果改變。
- **在這一批寫 held-out loop**：理由見解讀 28。
- **held-out run group 可撤回、不填 slot、不算無效嘗試**（補充時的解讀 30）：放寬 023 §2、§4、§5.3，見解讀 30。
- **prediction 先寫、transcript 後寫**（修訂 1 之前）：兩者之間被中止會留下沒有 transcript 的 prediction，而且不能重跑。
- **沒有 `up_at` 的非 valid run group 只看 commit 與編號**：可行，但放寬一項防竄改檢查；在 `run_group` 先記 `up_at` 不放寬任何檢查。

## 對實驗的影響

- 不改任何協定、門檻、指標、切分、預算或 Gate 定義；Pilot 的收集、run.json 形狀與評分路徑不變（回歸測試守住）。
- **held-out 的 plan、freeze 與收集都被 NEXT A1（付費 LLM 方法延後）擋住**；在 freeze 紀錄存在之前，所有 held-out 收集與方法執行一律拒絕。
- freeze 之前必須 commit 的項目：模型 API adapter、Gate 條件 2 / 3 的程式、各 fault 等權平均與缺格表、013 正式版、需要乾淨 checkout 的 review 說明，
  以及下面「待使用者決定」中使用者決定要有的機制。
- 測試全部用 synthetic / tiny generated fixture，沒有真實 snapshot 進 git。
- 修訂 1 只拒絕更多（held-out 不撤回、run.lock 存在時不評分），或讓紀錄更完整（每個紀錄都有 `up_at`、prediction 最後寫）；
  不改任何協定、門檻、指標、切分或預算。Pilot 的撤回與評分不變；Pilot 的 run.json 形狀不變（`up_at` 一直都有，只是更早寫入）。

## 待使用者決定

以下三項 023 與使用者決定都沒有涵蓋，**程式目前的行為不變**（都是拒絕的一側）。因為 freeze 釘住所有程式（解讀 7），
使用者若要其中任何一種機制，必須在 freeze **之前**決定、寫 decision 並 commit 程式；freeze 之後就無法加入。在決定之前不影響 Pilot 收集。

1. **待人處理的 slot 如何解除**（023 §4 只說「標為待人處理」，沒有說人可以做什麼）。
   - 現況：一個 slot 累計 3 個非 valid 的 run group、又沒有可用 incident，就永遠是待人處理；`withdraw` 只接受 valid run group，無效紀錄不能刪（009 §4），
     而 `heldout_incidents` 在有任何待人處理的 slot 時拒絕。所以只要有一個這樣的 slot，held-out 清單就永遠寫不出來，任何方法都不能在 held-out 上執行。
   - 估計：依 023 假設的無效率 25%，一個 slot 在第一個 valid 之前連續 3 個無效的機率約 0.25³ ≈ 1.6%；約 50 個 slot 加上 §5.3 的重收，
     至少一個 slot 卡住的機率約 55%。
   - 選項（審查建議 a，與 023 §2「不追加收集」一致）：
     a. 人在 ground-truth 側寫一份決定，把該 slot **關閉為缺格**（記錄方式同 `closed_slots`，`by_fault.missing_slots` 列出），清單接受這樣關閉的 slot；
     b. 人診斷 stack 之後，允許該 slot 再收（例如再給 3 次），次數與條件要寫進 decision；
        **Pilot 的前例**（2026-10-10 補註）：Pilot 已用同一種機制，`collect ack-failures --set pilot`（016「實作說明（2026-10-09）」，
        `failure_acks.jsonl`，只附加、不刪任何 run record），被確認的失敗不再計入、該 fault 重新計數，已用過兩次。
        Pilot 的確認沒有次數上限，b 則要把次數與條件寫進 decision（如上）；
     c. 維持現況（一個卡住的 slot 就讓 held-out 評測無法進行）。**注意**：c 與 Pilot 的規則**不同**（Pilot 有 `ack-failures`，見解讀 11 的更正）。
   - 附帶：狀態優先順序 needs_person > closed（解讀 12），所以 2 個未觸發加 3 個非 valid 的 slot 也是待人處理（實際上幾乎不會發生）；選項 a / b 也要涵蓋它。
2. **freeze 之後的修正路徑**（023 §6 的 bug 修正程序與使用者決定 6）。
   - 現況：freeze 預設拒絕（解讀 7），任何程式、env lock 或 policy 的變動都讓所有 held-out 收集、清單與 eval 停止；slots / freeze 只能寫一次，
     held-out run group 出現之後也不能重新 freeze。所以 023 §6 允許的「修好收集或 normalize 的 bug 後全部重新 normalize」、
     「方法執行後修好評分或稽核的 bug、所有方法重新評分（Gate 用修正後的數字，前後都報告）」，以及使用者決定 6 的「排除受影響的 incident」，
     在 freeze 之後都**做不到**：一個評分 bug 就會讓 held-out 評測停在沒有 Gate 的狀態。
   - 選項：
     a. freeze 之前實作一條窄的修訂路徑：新的 decision 檔加上一份接續的 freeze 紀錄，只允許變動指名的檔案，只用於 023 §6 允許的修正
        （評分 / 稽核修正與原始數字一起報告；使用者決定 6 的排除受影響 incident、永不混用）；
     b. 接受現況：freeze 之後發現任何 bug，held-out 評測就停止，由使用者另寫 decision 決定（可能要重新設計一個新的 held-out set）。
3. **held-out 撤回**（修訂 1 改為一律拒絕，見解讀 30）。
   - 若使用者認為 held-out 需要撤回（例如 `power_not_formal` 以外、收集時沒有偵測到的收集條件問題），審查建議的保守設計：
     撤回的 run group 算該 slot 的一次無效嘗試（或算 §5.3 那唯一的一次重收），永不免費重收；incident 已有 `label_review.json`、
     `label.reviewed.json` 或 `leakage_audit.json` 之後拒絕撤回；原因限定在固定的收集條件清單。
   - 預設：沒有 held-out 撤回。
