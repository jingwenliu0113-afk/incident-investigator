# NEXT

## 目前位置（2026-10-16：Pilot 的 evidence gold 標完並重新評分；Freeze 前稽核進行中）

**Core 還沒完成，Gate 還沒判定，不進 Advanced。** Pilot 上四個方法都已執行並評分（診斷用，不是 Gate 判定）。使用者的 evidence gold 盲標（91 筆）
2026-10-16 完成（87 筆寫入、4 筆略），重新評分、compare、gate 與 README 的結果都已更新（「下一步」1–4 完成）。剩下的 Core 依序見「下一步（Core，依序）」5–9：
013 正式版（起草中）、Pilot 修訂宣告、version-check、heldout-plan、freeze。沒有技術上的 blocker；需要使用者的事項見「Blocked / 需要使用者」A。

- **使用者決定（2026-10-16）**，原話：
  > 我的決定：
  >
  > 1. Gold 背景資訊選 a，依 decision 017 顯示，但必須保持方法盲標。
  > 2. 重複證據維持原規則，不修改 91 筆工作表的標註單位；可以提醒我哪些是重複內容。
  > 3. 同意修正所有過期文件、錯誤敘述及失效指令，確保 README、NEXT、Decision Logs 與實際程式一致。
  > 4. README 發布方式選 a，Freeze 前預留正式結果連結，之後以固定的新結果文件及 decision 紀錄呈現，不修改封存的 README。
  >
  > Gold 標註仍由我確認，不得自行冒充人工標註。
  > 完成 91 筆標註後，重新計算 Pilot 的相關分數、比較與診斷性 Gate，並完成 Freeze 前稽核。
  > 不修改既有評測門檻、不放寬 Gate、不自行進入 Advanced。
  > 其他技術問題自行解決，持續測試、Review、Commit、Push。需要我人工標註時，再依 Incident 分組詢問我。

  - 1、2 記在 decision 017「補註（2026-10-16）」（照 017 現行規則，**不是 017 在 Pilot 上的那一次修訂**）；怎麼做見「下一步」1；
    這一輪標註的紀錄（呈現方式、筆數、4 筆略與使用者的理由、重複項目、INC-002 第 10 項）在 017「補註（2026-10-16，第二則）」。
  - 3 是本次的文件同步（下面「文件同步（2026-10-16）」）。
  - 4 是 decision 030：held-out 最終結果的固定檔名 `docs/decisions/100-heldout-final-results.md`（100 保留，一般 decision 用 031–099）；README 已加預留連結
    （held-out 評測完成前打不開）。README 在 freeze 時封存，之後不改；held-out 的結果只寫在 100 與同時新增的 decision 紀錄。
  - 「重新計算 Pilot 的分數、比較與診斷性 Gate」是「下一步」2、3（**已完成**）；「Freeze 前稽核」是「下一步」4–8（README 定稿——**已完成**、013 正式版、
    Pilot 修訂宣告、version-check、plan），freeze 本身再由程式檢查（「下一步」9）。門檻、Gate、指標、切分、預算、評分、引用驗證都不改。
- **使用者（2026-10-16，回答 INC-011 時）**，原話（標註的部分記在 017「補註（2026-10-16，第二則）」）：
  > 請依 decision 017 寫入人工標註，保持方法盲標，不修改既有判定標準。
  > 10 個 Incident 全部完成後，請重新計算 Gold Evidence Precision、Coverage 與 Pilot 比較結果，進行 Freeze 前稽核。
  > 若沒有其他需要我決定的問題，請依既定 SPEC 繼續推進 Held-out 正式評測。

  依序是「下一步」1（完成）、2–4（完成）、5–9（進行中）；需要使用者決定的事項列在「Blocked / 需要使用者」A，不自行決定。
- **Pilot 結果**（n = 10，診斷用；2026-10-16 gold 標完後重新評分，評分程式沒有改：主要指標與 2026-10-15 的評分相同，只有 evidence 的 gold 欄位改變，見「下一步」2）：

  | 方法 | fault_type | origin_top1 | origin_top3 | affected_f1 | symptom_exact | 失敗（022） | 平均 latency |
  |---|---:|---:|---:|---:|---:|---|---:|
  | stat-anomaly v2 | 0.30 | 0.60 | 0.90 | 0.77 | 0.50 | mechanism 4、rule_limit 4 | — |
  | dump-all（021 修訂後） | 0.60 | 0.70 | 0.80 | 0.74 | 0.50 | seen_misread 3、mechanism 2 | 139 s |
  | retrieval（021 修訂後） | 0.60 | 0.80 | 0.80 | 0.73 | 0.50 | mechanism 3、seen_misread 2 | 40 s |
  | agent（未重跑） | 0.50 | 0.60 | 0.60 | 0.69 | 0.60 | seen_misread 3、mechanism 2、no_answer 1 | 188 s |
  | *dump-all（修訂前）* | *0.50* | *0.70* | *0.70* | *0.66* | *0.40* | *mechanism 3、no_answer 2、seen_misread 1* | *133 s* |
  | *retrieval（修訂前）* | *0.50* | *0.80* | *0.80* | *0.83* | *0.50* | *mechanism 5、seen_misread 2* | *56 s* |

  - **decision 021 的 Pilot 修訂**（使用者 2026-10-11 選 (a)，原話見 021）：dump-all 與 retrieval 共用的概覽寫明它的列是彙總、沒有 id、不能引用（`baselines/overview.py`）。
    引用驗證、評分門檻、模型、資料、預算、推論主機、020 的任務說明與 Agent 都不變；這是 021 在 Pilot 上唯一的一次修訂（freeze 宣告 `"021": used`）。
    (b)、(c) 不改，保留為失敗分析的發現（decision 022 補註）。
  - **重跑（2026-10-15，commit `292e125`，RTX 5070 Ti）**：修訂前的輸出封存在 `data/external/archive/pilot-llm-gpu-2026-10-11-before-021-revision/`；
    retrieval 431 s、dump-all 1,437 s 都 exit 0；版本確認通過（每一筆都是 `method.version` "2"；2026-10-16 用 `method_version_problems` 再確認一次）；已評分、compare、gate、gold-todo。
  - **引用（修訂後）**：dump-all 的 `invalid_submission` 2 → 0；兩個方法的引用全部存在（existence 1.0）、只有 `s-` / `l-`。**錯誤降低但沒有消除：最後一次允許的提交才改正**——
    dump-all 的 INC-007、008、009、010 在第一次提交（evidence 寫成字串，以格式被拒收）與第一次更正（id 是概覽列，以 id 格式被拒收）都引用概覽列，
    第三次（最後一次允許的）提交才改用紀錄 id。retrieval 修訂後沒有引用概覽列；它的 INC-007、009、011 查詢沒有找到任何紀錄、沒有附證據。
    Agent 的 existence 0.96（020 的範圍，這次不改）。詳見 021「重跑結果」（2026-10-16 更正：原本寫成 3 個 incident、只有第一次提交）。
  - **origin 候選數（(b)）**：提出方案時（2026-10-11 的執行）每個 incident 最多一個候選；修訂後重跑，dump-all 的 INC-007 給了 2 個（origin_top1 0.70、top3 0.80），
    retrieval 每個 1 個（0.80 / 0.80）；Agent 沒有重跑，每個 1 個、INC-008 沒有答案（0.60 / 0.60）。(b) 仍是失敗分析的發現（022 補註，2026-10-16 更正）。
  - **evidence**（2026-10-16 gold 之後；n = 有引用的 incident 數，等權平均，run-group cluster bootstrap 95%；各方法的 n 不同，不是 paired 的比較）：

    | 方法 | n | existence | 弱標籤 temporal 且 service | gold precision | gold coverage |
    |---|---:|---:|---:|---:|---:|
    | stat-anomaly | 8 | 1.000 | 1.000 | 0.906 [0.719, 1.000] | 1.000 |
    | dump-all（021 修訂後） | 10 | 1.000 | 0.640 [0.340, 0.900] | 0.540 [0.240, 0.840] | 0.840 [0.710, 0.960] |
    | retrieval（021 修訂後） | 7 | 1.000 | 0.571 [0.143, 0.857] | 0.571 [0.143, 0.857] | 0.667 [0.345, 0.892] |
    | agent | 9 | 0.956 [0.867, 1.000] | 0.833 [0.611, 1.000] | 0.756 [0.444, 1.000] | 1.000 |

    coverage < 1：017 每個方法、每個 incident 只抽最多 5 筆（retrieval 在 INC-002、005、006 各引用 45、22、25 筆），以及 4 筆略（都在 dump-all 的樣本裡，
    所以 dump-all 的樣本沒有全部判定，見 A12）。gold precision 是 0 的 incident：dump-all INC-006、008、009、010，retrieval INC-006、008、010，agent INC-009、010。
    數字來自 `data/external/results/pilot/*/table.md` 與 `scores.json`；README 的「Evidence」已同步。
- **Gate（Pilot 診斷，不是判定）**：條件 1 不成立（agent − stat-anomaly 的 origin_top1 差 0.00，95% [-0.50, 0.50]）；條件 2 不評估（每個 fault 只有 1 個 incident）；
  條件 3 不成立（3/6 = 0.50）。**依 SPEC Gate，進 Advanced 要「Agent 在 held-out 明顯勝過最強統計 baseline」**：held-out 還沒收集，Gate 無法判定，**不進 Advanced**；
  Pilot 的診斷也沒有顯示 Agent 勝過統計 baseline。gold 不進任何 Gate 條件；2026-10-16 gold 之後重算的 compare 與 gate 三個條件的結果都不變。
- **`timeout_s`（原 A1 的待決事項）：沒有觸發，維持 3600**。Pilot（RTX 5070 Ti）每個 incident 的 `latency_s`（從開始到提交的經過時間，含所有模型呼叫）最長：
  Agent 1,214 s、dump-all 201 s、retrieval 76 s；任何一次呼叫都不超過它所在 incident 的經過時間，所以都遠低於 3,600；30 個 incident 都已提交，沒有
  `transport_error`、沒有逾時。029「`timeout_s`」的觸發條件不成立，不需要使用者決定（029「結果（2026-10-16）」）。
- **文件同步（2026-10-16，使用者決定 3）**：
  - 新增唯讀指令 `uv run python -m eval version-check --set pilot [--method <m> ...]`（預設三個 LLM 方法；`--method` 可重複）：印出 `method_version_problems`，
    有任何一筆 exit 1、沒有 exit 0；不寫任何檔案；只接受 `--set pilot` 與 LLM 方法。**流程上的檢查**：`eval score` 與 `collect heldout-freeze` 都不呼叫它
    （評分與 freeze 的程式不變）。取代原本指向已刪除的「目前位置第 3 步」的說法（NEXT、021、`eval/runner.py` 的 docstring）。
  - decision 030（新增）；017、019、020、021、022、023、024、026、029 的日期補註或更正（規則都不變）；`docs/decisions/README.md` 註明 100 保留。
  - README：狀態、預留連結、gold precision 的算法、origin 候選數與概覽列引用的敘述、held-out 段的 `version-check` 與 `gold-todo --set heldout`、decision 範圍（001–030）。
  - NEXT：本節、「下一步」與「Blocked」改寫成同一個順序；舊的內容移到文末「歷史紀錄」並標明。
  - 測試：1115 passed（`-m "not network and not docker_daemon"`；新增 3 個：`version-check` 兩個、freeze 之後新增 100 與改 README 一個）。
- **已完成的 Core 範圍**：

  | 項目 | decision |
  |---|---|
  | 環境鎖定與 soak（soak #6 PASSED，目前的 lock） | 001、004、007、008、028 |
  | run group 收集協定 | 009，含修訂 1–5 |
  | label 與 review（Pilot 10 個，human:jingwen） | 006、010、016、018 |
  | canonical snapshot 與凍結的 policy v1 | 011；renderer v2 |
  | docker_stats 覆蓋 | 012 |
  | 分層評分（正式版待「下一步」5） | 013 |
  | 統計 baseline v2（Pilot 修訂放棄） | 014 |
  | leakage audit | 015 |
  | evidence relevance（Pilot 的 gold：統計 baseline 2026-10-10、LLM 方法 2026-10-16，human:jingwen） | 017 |
  | Agent 工具與執行框架 | 019、020 |
  | dump-all 與 retrieval（Pilot 修訂已使用） | 021 |
  | 失敗分類 | 022 |
  | held-out 協定（Accepted，K = 5）與程式實作 | 023、026 |
  | 預算、用量與可見資料的報告 | 024 |
  | 收集時的電力模式紀錄 | 025 |
  | paired 比較與 Gate 計算 | 023 §7、「實作說明：Gate 計算」 |
  | 合成範例與 2 分鐘 demo | 027 |
  | 本機 LLM（qwen3.5 9B，RTX 5070 Ti）與三個 LLM 方法的 Pilot 執行 | 029、029 修訂 1 |
  | held-out 結果的發布方式 | 030 |
  | 端到端測試、README | — |

## 下一步（Core，依序）

1. **使用者的 evidence gold 盲標（91 筆）——已完成（2026-10-16）**：2026-10-15 `eval gold-todo --set pilot` 產生的工作表（INC-002 10、003 12、004 9、005 9、
   006 11、007 7、008 10、009 7、010 9、011 7；ground-truth 側各 incident 的 `evidence_gold_todo.json`）。
   - **做法**：一次一個 incident。主 session 唯讀顯示每一項的 record 內容（render v2）與 017 §3 的背景（label 的 fault_type、origin_service、affected_services 與
     fault 的相對時間；使用者決定 1 選 a），**不顯示是哪個方法引用的，也不顯示弱標籤**（方法盲標）。使用者逐項回答「是 / 否 / 略」；重複的項目（使用者決定 2）
     照 017 以 `(id, t0, t1)` 為單位分開回答，顯示時標明與哪一項重複。每個 incident 答完，主 session 列出問答紀錄給使用者確認，確認之後才
     `uv run python -m eval gold-add --incident <INC> --file <filled> --annotator human:jingwen`（寫入後不能改，017 §3）；主 session 沒有替使用者判定任何一項。
   - **結果**（以各 incident 的 `evidence_gold.json` 為準）：寫入 87 筆（human:jingwen，`annotated_at` 2026-10-15T16:25Z – 2026-10-16T00:56Z，本地時間 2026-10-16
     00:25–08:56）：INC-002 10、003 11、004 7、005 9、006 11、007 7、008 10、009 6、010 9、011 7，其中 50 筆 relevant。gold 現有 115 筆判定
     （2026-10-10 的 28 筆 + 87 筆），75 筆 relevant，全部 human:jingwen。
   - **略 4 筆**（`relevant: null`，不寫入、不進分母，只降低 coverage；之後的 `gold-todo` 會再列出）：INC-003 第 9 項、INC-004 第 1、8 項、INC-009 第 2 項；
     使用者的理由只記在 017「補註（2026-10-16，第二則）」（略的項目沒有寫進 `evidence_gold.json`）。4 筆都在 dump-all 的樣本裡（A12）。
   - **重複**：INC-003 第 2/3、10/11 項與 INC-004 第 2/3 項（同一筆紀錄的不同時間範圍）分開回答；INC-004 第 5 項是 2026-10-10 以另一個鍵判定過的紀錄，
     作答時沒有顯示先前的判斷（記在該項的 `note`）。
   - **INC-002 第 10 項**：使用者回答之前看到了助理的一段說明；寫入時在該項的 `note` 記錄（判定仍是使用者的）。
   - 寫入的項目在 `note` 記錄使用者的理由或作答情境（INC-005 到 011 每一項都有）；各 incident 的理由摘要在 017「補註（2026-10-16，第二則）」。
2. **重新評分三個 LLM 方法（Pilot）——已完成（2026-10-16）**：`uv run python -m eval version-check --set pilot` 通過（exit 0）之後
   `uv run python -m eval score --method {dump-all,retrieval,agent} --set pilot`；評分程式沒有改，主要指標不變，只有 gold 欄位改變（數字見「目前位置」）。
   stat-anomaly 的引用 2026-10-10 已全部判定（coverage 1.0），新的判定只加在別的鍵上，不改它的分數，沒有重新評分。
   **gold precision 的讀法**（017 §3、§4，`eval/relevance.py` 的 `gold_score`）：每個方法、每個 incident = relevant 的引用數 / 已有 gold 判定的引用數
   （任何人判定、以 `(id, t0, t1)` 為鍵，不分是哪個方法的樣本抽到的）；跨 incident = 該方法至少有一筆已判定引用的 incident 的**等權平均**（n、run-group
   cluster bootstrap 區間），不是合在一起算（stat-anomaly：0.906 是 8 個 incident 的平均，合在一起的 25 / 28 = 0.893 不是報告的數字）；「略」不寫入、
   不進分母，只降低 coverage；各方法的 n 不同，所以不是 paired 的比較。
3. **Pilot 的 compare 與 gate 再算一次——已完成（2026-10-16）**（診斷，不是 Gate 判定）：`eval compare --method agent --against stat-anomaly --set pilot`、
   `eval gate --method agent --against stat-anomaly --set pilot`。三個條件的結果不變（條件 1 0.000 [-0.500, 0.500] 不成立；條件 2 不評估，K < 2；條件 3 3/6 = 0.50 不成立）。
4. **README 結果更新（gold 數字）——已完成（2026-10-16）**：README「Evidence」表列出四個方法的 existence、弱標籤（temporal 且 service）、gold precision 與 coverage
   （n、等權平均、區間），寫明各方法的 n 不同、不是 paired 的比較，以及 017 每個方法、每個 incident 最多抽 5 筆、略不計入；狀態列與「還在盲標中」的說法已改。
   修訂前（封存）的 dump-all / retrieval **不補標、不重新評分**（封存目錄不被 `gold-todo` 讀；封存的 `scores.json` 只含評分當時與既有判定重疊的 gold：
   dump-all n = 1、coverage 0.025，retrieval n = 0），README 不報它們的 gold precision。decision 030 的預留連結還在。README 在 freeze 時封存；
   dump-all 的 gold precision 照使用者 2026-10-16 的要求報出，並標明它的樣本沒有全部判定；使用者若要改（A12），只能在 freeze 之前。
5. **013 正式版**（decision 013、023 §7：§7 的 paired 比較與 Gate 判準寫進 013 正式版，用掉 013 唯一的一次修訂；其他由 Pilot 引起的 013 修改必須和它併在一起）。
   **程式不檢查它的內容**：`collect/freeze.py` 只檢查 Pilot 修訂宣告的 013 是 `used`、而且指名 frozen commit 裡存在的 decision 檔。內容是流程上的檢查。
   主 session 依 023 §7 起草中（2026-10-16）；要併入其他 013 修改時先問使用者（A11）。
6. **Pilot 修訂宣告**（`collect heldout-freeze --pilot-revisions <file>` 的輸入，023 §6「用掉或明確放棄」）：

   | decision | 宣告 | 根據 |
   |---|---|---|
   | 011 | `waived` | policy v1（程式強制：v1 ⇔ waived） |
   | 013 | `used`，指名 013 正式版所在的 decision 檔 | 程式強制 `used`（023 §7） |
   | 014 | `waived` | 使用者 2026-10-10 放棄；程式強制 |
   | 021 | `used`，`docs/decisions/021-dump-all-and-retrieval-baselines.md` | 使用者 2026-10-11 選 (a) |
   | 015、017、019、020、022 | **使用者決定** `used` / `waived`（A9） | 推導的建議：五個都 `waived`（015：Pilot 稽核後沒有修訂——修訂 1 在 Pilot 之前、只用無 fault 資料，不占額度；Pilot 的詞彙命中都是 0。017：2026-10-16 的兩則補註都不改規則。019、020：021 的修訂刻意不改它們；020 的 2026-10-10 修正自己寫明不是 Pilot 修訂。022：2026-10-11 補註寫明沒有使用） |

   程式只檢查格式與 011 / 013 / 014 三個強制項目；五個由使用者決定的項目，程式兩者都接受。
7. **version-check（freeze 之前再一次）**：`uv run python -m eval version-check --set pilot` → exit 0 才繼續。`collect heldout-freeze` 不呼叫它
   （freeze 的 `pilot_llm_problems` 分不出 021 修訂前後的執行，decision 021「審查（2026-10-11）」），所以這是流程上的檢查。
8. **heldout-plan**：`uv run python -m collect heldout-plan --amendments <amendments.json>` 寫一次 `docs/heldout/plan.json` → 人檢查後 commit。
   label review 的 affected 與 user symptom 全部維持 a priori；7 個 incident 有 notes——要不要把 notes 當成 amendments 吸收（`field: notes`，每項要理由，
   023 解讀 3）由使用者決定（A10）。移除 fault 只依 023 §1 的證據（觸發、無效率、詞彙命中），永不依任何方法的分數。
9. **heldout-freeze → held-out 收集 → held-out 方法執行 → Gate**：
   - freeze 之前：README 已定稿（第 4 步）、A4 若要改也在這之前、checkout 乾淨。
     `uv run python -m collect heldout-freeze --pilot-revisions <revisions.json>` → 只把 `docs/heldout/slots.json` 與 `freeze.json` commit 成一個 commit。
     程式另檢查：目前 env lock 有通過的 soak（soak #6）、三個 LLM 方法的 Pilot `run_config.json` 正好是 `llm_methods.json`（含 host `gpu-server`）且分數是從那次執行算的（026 解讀 31、32）。
   - held-out 收集（Mac、Docker、高效能 + AC、Mac heavy lock；K = 5，約 50 個 slot）：README「Held-out」段的指令依序；沒有 loop，每個 run 一次 `./tools/with-mac-lock`。
   - held-out 方法執行：每個方法、每個 incident 只跑一次；只對 `api_error` / `transport_error` 重試、最多 2 次（023 §5）。LLM 方法每個方法一次
     `./tools/with-remote-ollama uv run python -m eval run --method <m> --set heldout`（開始前照歷史紀錄「原下一步 8.2」的遠端唯讀確認）。
   - score → compare → gate（held-out 上才是 Gate 判定）→ 結果只寫進 `docs/decisions/100-heldout-final-results.md` 與一份新的 decision（decision 030），README 不改。
   - 依 SPEC「Gate」：判定 `pass` 才可能進 Advanced，而且要使用者確認（使用者 2026-10-16：不自行進入 Advanced）；不通過時依 SPEC「收尾或改題」，由使用者決定。

## Blocked / 需要使用者（回來時一次處理）

### A. 需要使用者

（編號接在之前用過的 A0–A7 之後，避免和 decision 裡的「NEXT A1」等舊編號混淆；舊的項目見下面「已處理」。）

- **A9 Pilot 修訂宣告的五項**（015、017、019、020、022 寫 `used` 或 `waived`；「下一步」6）：推導的建議是五個都 `waived`，由使用者決定。
- **A10 heldout-plan 是否吸收 label review 的 notes**（「下一步」8）。
- **A11（需要時）013 正式版**：主 session 依 023 §7 起草；若要併入其他由 Pilot 引起的 013 修改，那是設計決定，先問使用者（「下一步」5）。
- **A12 Pilot README 的 dump-all gold precision（確認即可；要改只能在 freeze 之前）**：017「對實驗的影響」寫「各自的樣本要先標完，gold precision 才會出現在報告中」，
  decision 030 §8 照這句寫 held-out 的 100「一個方法的樣本全部判定之前不報它的 gold precision」。Pilot 上 91 筆都已呈現並作答，但 4 筆略都在 dump-all 的樣本裡，
  所以 dump-all 的樣本沒有全部判定（stat-anomaly、retrieval、agent 的樣本全部判定）。README 照使用者 2026-10-16 的要求（重新計算 Gold Evidence Precision、Coverage）
  報出 dump-all 的 0.540（n = 10，coverage 0.840），並標明 4 筆略與「樣本沒有全部判定」；**預設維持這樣**。若使用者要依字面不報，或要再判定那 4 筆
  （之後的 `gold-todo` 會再列出），都必須在 freeze 之前（README 在 freeze 時封存）。held-out 照 030 §8 的字面，不變；規則都不改（017「補註（2026-10-16，第二則）」）。
- **A4 freeze 之後的修正路徑（026「待使用者決定」2）**：使用者 2026-10-10 選**「沒有偏好」** → 不實作，維持現況：freeze 預設拒絕任何程式、env lock 或 policy 的變動，
  freeze 之後發現 bug 時 held-out 評測停止，由使用者當時決定。**freeze 之前仍可決定**（例如一條窄的修訂路徑：新 decision + 接續的 freeze 紀錄，
  只用於 023 §6 允許的修正）；freeze 釘住所有程式，之後就無法加入。不影響其他工作。

已處理（2026-10-16）：
- 原 A8 evidence gold 盲標（91 筆）：使用者 2026-10-16 一次一個 incident 盲標完成（87 筆寫入、4 筆略），已重新評分（「下一步」1–4）。
- 原 A1 的「`timeout_s` 要不要加長」：Pilot 上沒有觸發（見「目前位置」），維持 3600，不需要決定。
- 原 A1（LLM 方法）整項已處理：模型批准（2026-10-10）、推論改到 RTX 5070 Ti（2026-10-11）、三個方法在 Pilot 上執行（2026-10-11）、021 修訂後重跑（2026-10-15）。
  原文保留在下面「原 A1（已處理）」。

原 A1（已處理；保留當時的寫法）：
- **原 A1 LLM 方法（dump-all / retrieval / agent）**：付費 API 由使用者決定先延後（2026-10-09）；2026-10-10 使用者暫時同意先試本機模型
  （decision 029；原話「先暫時兩個都同意，先關掉 grafana 下載再測本地模型，之後可以考慮再換回來原本的方案」，之後可能換回付費 API）。
  - **已決定（2026-10-10，使用者「照建議」；029「使用者決定（2026-10-10）：照建議」）**：qwen3.5 9B（`qwen3.5:9b-q4_K_M`、digest `sha256:6488c96f…3ea7`）、
    Ollama 0.35.0 **釘選**（held-out 結束前不升級 Ollama，含 Homebrew 自動更新）、`num_ctx` 262,144、think 關、`num_predict` 8192、預算不變；
    LLM 執行要求高效能模式 + AC 並記錄（`power.jsonl`）；freeze 由程式檢查 soak 與 Pilot 的 LLM 設定（026 修訂 3）。`eval/llm_methods.json` = `approved`。
    原本待確認的三項（版本釘選或只記錄、電力條件、freeze 是否強制）都已決定：釘選、套用並記錄、強制。
  - **已決定（2026-10-11，使用者「同意」；decision 029 修訂 1）**：推論改在 RTX 5070 Ti 桌機（`ollama.host` = `gpu-server`，`./tools/with-remote-ollama`：
    SSH tunnel、WSL Ubuntu-22.04 裡的 Ollama 0.35.0、共用 GPU lock `flock -n /tmp/ai-portfolio-gpu.lock`）；eval、snapshot 與 ground truth 留在 Mac。
    這種執行不需要 Mac heavy lock，電力條件改為記錄 GPU 狀態（GPU 不是 RTX 5070 Ti 或連續兩次讀不到才停止）。三個方法都要在 GPU 上重跑 Pilot
    （Mac 上的 retrieval / agent 結果被取代）；freeze 釘住 `host`。
  - （當時）下一步不需要使用者：遠端檢查、探測、三個方法在 Pilot 上執行（原下一步 8.2）——**已完成**（2026-10-11；021 修訂後的重跑 2026-10-15）。
    執行中被拒絕或停止（`CallError`、釘選、GPU 狀態、GPU lock、gpu-server 離線 → blocked）時回報使用者，不自行改設定或預算，也不改回 Mac 推論（held-out 照樣適用）。
  - （當時）之後需要使用者：LLM 方法的引用要再補 evidence gold——**現在是 A8 /「下一步」1**。`ollama.timeout_s` 要不要加長——**沒有觸發，維持 3600**（「目前位置」）。
  - 已完成並合併進 main（decision 029）：Ollama adapter（只連 loopback、拒絕 cloud 模型；`truncate` / `shift` 關閉、每個回覆檢查——包括不依賴
    `truncate: false` 的送出量與計數下限——截斷或無法確認未截斷一律是不可重試的 `CallError`；解析不了的 tool call 參數照 020 §3 拒收）、
    模型 digest 與 Ollama 版本釘選（每個 incident 的檢查在嘗試開始之前：server 不在或模型被換時執行停止、不用掉 held-out 嘗試）、整個執行只用開始時的設定、
    執行前的 fit check（放不下就拒絕，不改預算）、heavy lock 與 `tools/with-local-ollama`（server 只在 lock 內存在、結束時卸載模型）、
    `run_config.json` 的 `llm`、`eval local-probe`（防護自我測試要求 server 自己拒絕，否則 exit 3）。
    scripted fake model 與合成範例探測都不產生方法結果。審查（2026-10-10，合併前）的修正見 029 開頭。
  - **探測完成（2026-10-10）**：結果見 029「探測結果」；qwen3.5 9B 是唯一三個方法都能提交合格答案的模型（dump-all / retrieval 在修正 020 的更正訊息之後）。
  - **Pilot 上的 LLM 方法沒有嘗試紀錄**（只跑一次與嘗試紀錄是 held-out 的規則，023 §5）：`eval run --set pilot` 被 `CallError`（API / transport 錯誤，
    或 029 的 `context_overflow` 等）、釘選或電力中止時印 `error: …`、exit 2；重跑時整個 Pilot set 從頭執行，已經有 prediction 的 incident 也會再呼叫，
    `run_config.json` 與所有 prediction 都重寫（中途停止的執行不要評分，026 解讀 32）。本機模型重跑只花時間；換回付費 API 時，估算 Pilot 成本要把這種重跑算進去。

已處理（2026-10-10 使用者決定；023「使用者決定」的「追加（2026-10-10）」）：
- 原 A6 系統的 git 壞了（2026-10-10 19:25 xcode-select 指向不相容的 Xcode）：使用者 23:00 已切回 Command Line Tools，`/usr/bin/git` 恢復正常；期間本 session 只在自己的指令前加 `DEVELOPER_DIR`，沒有改任何系統設定。
- 原 A0 grafana 的 plugin 下載逾時：使用者決定暫時關掉（decision 028），**soak #6 PASSED**（`data/external/soak/20261010T053643Z/`，新 lock `sha256:1e749f67…`，
  R1–R9 全過；收集的 preflight 與 freeze 的 soak 檢查（026 解讀 31）都接受它）。`grafana-opensearch-datasource` 沒有安裝、grafana 沒有重啟；
  Grafana 13 的背景安裝器仍會在暖機時下載 4 個沒有固定版本的介面 app（非同步、grafana 不進 snapshot，028「結果」）。
  **使用者 2026-10-10「照建議」第 8 項：背景安裝器維持現狀**（不加 overlay、不重算 lock、不再 soak）。換回原方案或再改，只能在 freeze 前另寫 decision
  （逐 byte 還原 overlay 與 lock 就能沿用 soak #5，028「換回原本的方案」）。不重做校準（policy v1 已凍結、014 的門檻固定）。
- 原 A3 gold 標註量：**照原規定**，不修訂 017（023「追加（2026-10-10，第二次）」第 5 項）。
- 原 A5 Gate 的 Pilot 診斷讀法：**使用者確認**（Pilot 上 K < 2 的 fault 不評估條件 2；held-out 不變；023 第二次追加第 6 項、Gate 解讀 4）。
- 原 A2 的 freeze 前事項：統計 baseline 在 Pilot 上的「最多修訂一次」（decision 014）**放棄**，stat-anomaly 維持 v2（014「補註（2026-10-10）」；
  Pilot 的 8 個失敗 = rule_limit 4、mechanism 4，沒有發現設計缺陷；n = 10、每個 fault 1 個 incident）。
- 原 A4.1 待人處理的 slot：**b，與 Pilot 相同**，`collect ack-failures --set heldout --slot <slot> --reason … --decided-by …`（已實作，026 修訂 2、解讀 11、12）。
- 原 A4.3 held-out 撤回：**不允許**（維持預設，026 解讀 30）。
- 原 A2：Pilot 的 label review 與 evidence gold 標註（human:jingwen，2026-10-10）。
- 原 A0 前半：intlShippingSlowdown 連續 3 次無效（RG-011、RG-012 grafana；RG-013 fault 關閉沒生效）：使用者已 ack（`collect ack-failures`）；
  flag 寫入改為同一個 inode、沒生效就重寫（decision 009 修訂 5，已在 main）。

已處理（2026-10-09 使用者決定）：held-out K = 5（decision 023 Accepted，其餘依保守預設）；正式收集固定高效能模式 + AC 供電（decision 025 修訂 3；原本的自動模式由使用者改掉，RG-002 撤回重收）；
真實 snapshot sample 不進 git（需要時用 synthetic fixture）；`/usr/bin/git` 已由使用者修好；電力模式限制解除。

### B. LLM 方法的估算（原 A1 用；付費 API 時的估算，保留給換回付費 API 時參考）

目前用本機模型（沒有外部費用，`cost_usd` = 0）；時間估計見 029「探測結果」與「使用者決定（2026-10-10）」的 `timeout_s` 一節。
建議值在 `eval/llm_methods.json`（2026-10-10 起 `approved`，預算不變）。每個 incident 的 token 量估算（proxy token ≈ UTF-8 bytes / 4；實際 tokenizer 的數字可能高 0–30%，未實測）：

| 方法 | 呼叫數 / incident | input tokens / incident | output tokens / incident |
|---|---|---|---|
| dump-all（B = 120k） | 1（+ 最多 2 次更正） | 約 12–16 萬 | 約 1–2 千 |
| retrieval（q = 8、k = 25） | 2 | 約 9 萬（概覽約 1.8 萬 × 2 + 檢索結果約 5 萬） | 約 2–3 千 |
| agent（40 次工具、工具輸出 ≤ 120k、30 回合） | ≤ 31 | 典型約 40–60 萬，最壞約 180 萬（每回合重送整段對話；prompt caching 可大幅降低） | 約 1–3 萬 |

- **實測（2026-10-09，soak #5 的 38 分鐘無 fault snapshot，用計量用的假模型，proxy tokens）**：dump-all 一次請求 131k；
  retrieval 兩次請求 17k + 19k（無 fault 時查詢命中很少；有 fault 時第二次最多再加約 50k）；agent 模擬 25 次工具呼叫的探索：26 回合、input 累計 422k、
  最後一回合 59k、工具輸出 51k（工具輸出用滿 120k 時累計約 0.8–1M）。實際 tokenizer 的數字尚未量（需要 API）。
- Pilot（10 個 incident）× 3 個方法：input 約 0.6–2 千萬 tokens（agent 佔大部分）。held-out 的數量在其協定決定。
- 成本 = tokens × 所選模型的單價（使用者確認目前價格）；建議先在 1–2 個 Pilot incident 上跑一次，量到實際 token 後再估全部。
- 需要決定：模型、上面的預算數值、是否用 prompt caching、批准預估成本。

### C. 暫時無法進行（不需要使用者，條件解除後繼續）
- 目前沒有。
- held-out 收集沒有 loop（`collect pilot-loop` 只收 Pilot；026 解讀 28）：Mac heavy lock 被其他 Project 占用時 `./tools/with-mac-lock … collect run --set heldout`
  exit 75，不搶、不刪，之後再跑（期間做 Mac 上不需要 lock 的工作）。
- GPU lock 被占用時 `./tools/with-remote-ollama` exit 75（同樣不搶不刪，之後再跑）；gpu-server 離線（ssh 失敗，exit 3）→ LLM 步驟標記 blocked，繼續 Mac 上的工作。
- 已解除：`/usr/bin/git` 失效（2026-10-08 17:05Z 起，使用者已處理）；Mac 自動電力模式下延後正式收集（2026-10-09 使用者解除；正式收集條件後來改為高效能模式 + AC，decision 025 修訂 3）。

### D. 歷史紀錄與環境狀態
- （歷史）soak #3 曾等 heavy lock（`llm-serving-lab` 11:14:59Z–12:04:19Z 持有），釋放後由本 Project 的 wrapper 取得。
- 歷史紀錄（已解除）：Docker Desktop 在 2026-10-08 09:32:48Z 被另一個 Claude Code session（`rtu-maintenance-platform` 專案，
  執行 `docker compose stop db && docker desktop stop`）停止。使用者回覆「可以再繼續用了」後，本 session 執行 `docker desktop start`
  （理由：跑 decision 004 的 soak test；當時 daemon 是停止狀態，沒有其他 workload 在跑），接著先 `compose down --volumes` 清掉本 Project 被 restart policy 拉起的 container。
- 遠端 RTX 5070 Ti：2026-10-11 起用於 LLM 方法的模型推論（使用者明確要求，decision 029 修訂 1、MACHINE_POLICY「遠端 GPU」）；只透過 `ssh gpu-server`
  與 `./tools/with-remote-ollama`，GPU lock 共用、不搶不刪。其他 Core 工作仍只在 Mac。
- Docker Desktop：依 `MACHINE_POLICY.md`，在 Core 階段是本 Project 專用。
  機器上不屬於本 Project 的 Docker 資源都保持原狀：`pgvector/pgvector:pg17` image、`rtu-maintenance-platform-db-1`（停止中）container、它的 volume `rtu-maintenance-platform_rtu_db_data` 與 network `rtu-maintenance-platform_default`。
- 本機已下載 28 個鎖定的 image（約 11.7 GB），保留給之後的收集使用。
- Docker Desktop VM 的 kernel log（`~/Library/Containers/com.docker.docker/Data/log/vm/init.log*`）約 2.5 分鐘輪替一次，只保留約 25 分鐘；
  OOM 證據要在 run 期間抓（soak 工具的 `docker-events.jsonl`）。

## 歷史紀錄（不再更新；現況以上面「目前位置」「下一步」「Blocked」三節為準）

以下各節保留當時的寫法：其中的「下一步」「尚未」「待使用者決定」與測試數都是當時的狀態。2026-10-16 只做三種修改：失效的指令改成現在的指令
（版本確認 → `uv run python -m eval version-check --set pilot`）、已不存在的分支標明已合併並刪除、會被誤讀成現況的句子加上「（當時）」或結果。
decision 裡的「NEXT 下一步 8.2」指下面「原下一步」的第 8 項第 2 點。

### 原「下一步（Core，依序）」1–8（2026-10-08 – 10-15，全部完成）

held-out 的指令以 README「Held-out」段與上面「下一步」為準；第 8 項第 2 點的遠端唯讀確認與 `with-remote-ollama` 的說明在 held-out 的方法執行照樣適用（`--set heldout`，每個 incident 只跑一次）。

1. ✅ **soak #5 PASSED**（`data/external/soak/20261008T143533Z/`）：這個 lock 可以收集（decision 008「結果」）。
2. ✅ 校準：soak #3 與 soak #5 在 commit `131446d` 上 F1–F6 全過。
3. ✅ **policy v1 已凍結**：`sha256:95bc4b07…`（decision 011「凍結紀錄」）。之後任何改動都是 v2。
4. ✅ **Pilot Set 收集完成**（2026-10-10：INC-002..011，10 個有效 incident，高效能 + AC；RG-002 撤回）。以下流程是 Pilot 的，保留作參考（`pilot-loop` 只收 Pilot；held-out 沒有 loop，026 解讀 28，單步指令見 README「Held-out」）。
   **每個 Pilot fault 的流程**（decision 016 的順序；`uv run python -m collect status --set pilot` 看進度）。
   **一次跑完整個 Pilot**：`uv run python -m collect pilot-loop --labeler agent:claude-code`（**不要**包 with-mac-lock：迴圈只在每個 `collect run` 期間持有 lock，
   run 之間釋放；lock 被占用時每 5 分鐘重試、最多 4 小時，不搶；需要人看的 fault、run 被拒、process 失敗都會停下；全部收齊後自動 leakage → stat-anomaly run / score；
   每一步的輸出在 `data/external/logs/pilot-loop/`；exit 0 完成、3 需要人、75 lock 一直被占用）。開始前會印出目前的電力模式（decision 025）。
   手動的單步流程：
   1. `uv run python -m collect next --set pilot` → 印出下一個 `--flag F --variant V`（全部收齊時不印；exit 3 = 某個 fault 需要人看：
      連續 3 個 run group 無效，或 fault 兩次沒被觸發）。
   2. `./tools/with-mac-lock uv run python -m collect run --set pilot --flag F --variant V`（約 45 分鐘；lock 被占用時 exit 75，不搶）。
      run group 無效 → 記錄原因，`next` 會再給同一個 fault（新 seed，decision 009 §4）。
   3. 有效時：`uv run python -m collect process --incident INC-nnn --labeler agent:claude-code`（normalize → Day 1 #6 replay → a priori label，做過的步驟跳過）。
   4. 收完或告一段落時：`uv run python -m eval leakage --set pilot` → `uv run python -m eval run --method stat-anomaly --set pilot` →
      `uv run python -m eval score --method stat-anomaly --set pilot`（v2；表在 `data/external/results/pilot/stat-anomaly/table.md`）。
   - 每次 run 之間 lock 會釋放（wrapper 一次只包一個 run），其他 Project 可以在空檔取得。
   - 非正式的整條 pipeline 檢查：`./tools/with-mac-lock uv run python -m collect smoke --root <scratch>`（normal 10、fault / recovery 各 2 分鐘，
     資料只寫在 scratch，永不進任何集合；跑完自動 normalize → replay → label → review 工作表 → leakage → 統計 baseline）。
     **冒煙測試進行中整個 working tree 都要保持乾淨**（normalize 檢查 `git status --porcelain`，不只 `collect/`、`env/`）。
   - **run 進行中不改 `collect/`、`env/`**（run 會在中途延遲 import 這些模組；改了會讓一個 run 混用兩個版本），也要保持 working tree 乾淨
     （preflight 與 normalize 都拒絕 dirty tree）；可以改 `eval/`、`agent/`、`baselines/`、文件。
5. ✅ **Gate 前請使用者做的人工作業**（2026-10-10 完成，human:jingwen）：label review（`python -m collect review-sheet --incident <INC>`，decision 018）與 evidence gold 標註（`python -m eval gold-todo --set pilot`，decision 017）。
6. LLM 方法（dump-all / retrieval / agent）已登錄在 `python -m eval run`；`eval/llm_methods.json` 已於 2026-10-10 由使用者批准（`approved`，本機 Ollama 的
   qwen3.5 9B，decision 029）。付費 API 的 adapter 沒有（換回時另寫 decision、先報告成本）。2026-10-11 起推論主機是 RTX 5070 Ti 桌機
   （`ollama.host` = `gpu-server`，029 修訂 1）：執行要求 `./tools/with-remote-ollama`（不需要 heavy lock、不檢查 Mac 電力，記錄 GPU 狀態）。
   host `local`（Mac）的規則不變：heavy lock、`with-local-ollama` 與高效能模式 + AC。
7. ✅ 第一張 baseline 表（Pilot，stat-anomaly v2）已產生（README「結果」）。
8. **（當時）剩下的 Core 依序**（LLM 方法暫時改試本機模型，decision 029；2026-10-11 起在 RTX 5070 Ti 上推論，029 修訂 1；見 A1）：
   0. ✅ **新 lock 的 soak #6 PASSED**（2026-10-10，A0，decision 028「結果」）。
   1. ✅ **合成範例探測**（2026-10-10，三個本機模型，029「探測結果」）；✅ **使用者決定「照建議」**（2026-10-10，029 文末；`llm_methods.json` = `approved`）。
      （探測的指令與看法保留在 029 §5；之後不再需要。）
   2. ✅ **三個 LLM 方法在 Pilot 上用 RTX 5070 Ti 執行**（decision 029 修訂 1；2026-10-11 完成，結果見「目前位置」）。
      ✅ **dump-all 與 retrieval 依 decision 021 的 Pilot 修訂已重跑完成**（2026-10-15，commit `292e125`：封存、版本確認、評分、compare、gate、gold-todo；結果見「目前位置」）。
      下面是原本那次執行（2026-10-11）的紀錄與指令；「先合併 `remote-gpu`」（分支已快轉合併進 main、已刪除）與「開始前 1」都已完成。
      原本的說明：先合併 `remote-gpu` 進 main（測試通過後 push）。
      Mac 上 2026-10-10/11 的 retrieval / agent 結果被取代：三個方法都從頭重跑到 exit 0，`run_config.json`、prediction 與 `power.jsonl` 的新行會寫在同一個目錄
      （舊的 Mac 行留著，評分與 freeze 只看每個 incident 的最後一行與目前的 `run_config.json`）。重跑會**覆寫** Mac 的 prediction、transcript、
      `run_config.json`（評分時也覆寫 `scores.json`、`table.md`），所以先封存（029 修訂 1「審查」第 6 點）。
      **開始前 1：封存 Mac 的輸出（主 session，只複製；封存目錄必須還不存在，在 `results/` 之外，不被評分、`gold-todo` 或 freeze 讀到）**：
      ```bash
      test ! -e data/external/archive/pilot-llm-mac-2026-10-11 && mkdir -p data/external/archive/pilot-llm-mac-2026-10-11 \
        && cp -Rp data/external/results/pilot/retrieval data/external/results/pilot/agent data/external/results/pilot/dump-all \
           data/external/archive/pilot-llm-mac-2026-10-11/
      ```
      **開始前 2：主 session 在 gpu-server 上確認一次（只讀，不改任何設定）**：
      ```bash
      # Ollama 0.35.0 在 WSL 的 home（印出 client version is 0.35.0；沒有 server 時的警告是正常的）
      ssh gpu-server 'wsl.exe -d Ubuntu-22.04 -- bash -lc "$HOME/opt/ollama-0.35.0/bin/ollama --version"'
      # 只給本 project 的 models 目錄：manifest 的 sha256 必須是 6488c96fa5faab64bb65cbd30d4289e20e6130ef535a93ef9a49f42eda893ea7
      ssh gpu-server 'wsl.exe -d Ubuntu-22.04 -- bash -lc "sha256sum $HOME/ii-ollama-models/manifests/registry.ollama.ai/library/qwen3.5/9b-q4_K_M"'
      # wrapper 與 runner 需要的指令都在（flock、pkill、pgrep、nvidia-smi）
      ssh gpu-server 'wsl.exe -d Ubuntu-22.04 -- bash -lc "command -v flock pkill pgrep nvidia-smi"'
      # runner 每個 incident 前後用的同一個 GPU 查詢：一行，名稱含 RTX 5070 Ti
      ssh gpu-server 'wsl.exe -d Ubuntu-22.04 -- nvidia-smi --query-gpu=name,driver_version,power.limit,power.draw,clocks.sm,temperature.gpu,memory.used --format=csv,noheader'
      # Windows 那一側沒有程式在聽 11434（例如 Windows 版 Ollama）：沒有「本機位址 …:11434、外部位址 0.0.0.0:0 或 [::]:0（LISTENING）」的行才繼續
      # （有 → 回報使用者，不停止它；TIME_WAIT 之類的行不算）
      ssh gpu-server 'netstat -ano | findstr :11434'
      ```
      Mac 上不能有程式在聽 `127.0.0.1:11434`（例如 Ollama app；wrapper 會 exit 3）。執行中不改 main checkout。
      wrapper 只用這次啟動的 server：就緒請求（`/api/version?ii_session=…`）必須出現在這次的 serve log；tunnel 接到別的 server 時 exit 3
      （訊息說明是 Windows 那一側有程式在聽，或 log 裡的請求紀錄沒有 query string——兩者都回報使用者）。
      **探測（合成範例，不是結果）**：確認整條路徑（tunnel、GPU lock、WSL2 的 localhost 轉送、server 自己拒絕過長的 prompt）與 GPU 上的速度；
      `num_ctx` 262,144 在 16 GB VRAM 上是否完全放在 GPU 也看這裡的速度與 `/api/ps`：
      ```bash
      ./tools/with-remote-ollama uv run python -m eval local-probe --model qwen3.5:9b-q4_K_M --num-ctx 262144 \
          --context-sizes 8000,32000,100000,200000 --out <session 的 scratchpad>/probe-gpu.json
      ```
      exit 0 才繼續；exit 3 = GUARD FAILED 或 wrapper 拒絕（訊息說明）、exit 75 = GPU lock 被占用（之後再跑，不搶不刪）、ssh 失敗 = blocked → 回報使用者。
      wrapper 結束時印出「WARNING: could not confirm …」→ 照訊息在 gpu-server 上檢查（`pgrep -af ollama`），回報使用者，不刪 lock。
      報告的 `host` 應是 `gpu-server`、`gpu` 是 RTX 5070 Ti、`ollama.digest` 是釘選的 digest。
      **三個方法**（順序：retrieval 當金絲雀、agent、dump-all；每個方法一次 wrapper，方法之間 GPU lock 釋放，讓其他 project 有空檔）：
      ```bash
      ./tools/with-remote-ollama uv run python -m eval run --method retrieval --set pilot
      ./tools/with-remote-ollama uv run python -m eval run --method agent --set pilot
      ./tools/with-remote-ollama uv run python -m eval run --method dump-all --set pilot
      ```
      每個都跑完（exit 0）之後才評分（不需要 wrapper 或 lock）：
      ```bash
      uv run python -m eval score --method retrieval --set pilot
      uv run python -m eval score --method agent --set pilot
      uv run python -m eval score --method dump-all --set pilot
      uv run python -m eval compare --method agent --against stat-anomaly --set pilot   # paired 比較（Pilot：只是描述）
      uv run python -m eval gate --method agent --against stat-anomaly --set pilot      # Pilot 診斷，不是 Gate 判定
      ```
      - 時間要等探測量到 GPU 的速度再估。Mac 上的參考（不可比）：retrieval 平均 280 s / incident、agent 422 s、dump-all 約 27 分鐘。
      - **每個 LLM 方法**開始時 stderr 都會印 `WARNING (decision 029): agent's worst case (409,730 proxy tokens …) is above num_ctx 262,144`：
        只是報告（029 §2.5），不是錯誤。Agent 真的超過時那次呼叫以 `context_overflow` 停止、不會靜默截斷。
      - `timeout_s` 是 3600（不變）。若 Pilot 上有呼叫逾時（`transport_error`、exit 2），或評分表的 dump-all `latency_s` max 接近 3600，回報使用者決定。（2026-10-16：沒有觸發，見「目前位置」。）
      - exit 2（`error: …`）：`CallError`（例如 `context_overflow`、`context_unverified`：`/api/ps` 的 context 不是 262,144）、釘選不符、
        GPU 狀態停止（不是 RTX 5070 Ti，或連續兩次讀不到）、不在 wrapper 之下。exit 75：GPU lock 被占用（之後再跑）。exit 3：wrapper 拒絕或 ssh 失敗
        （gpu-server 離線 → LLM 步驟標記 blocked，繼續 Mac 上的工作）、或結束時無法確認遠端 server 已停止（照訊息在 gpu-server 上檢查、回報使用者，不刪 lock）。
        Pilot 沒有嘗試紀錄，重跑時整個 Pilot 從頭執行；**中途停止的執行不要評分**（freeze 也會以 `power.jsonl` 的 `run_config_sha256` 拒絕，026 解讀 32）。
        例外：021 修訂後的 dump-all / retrieval 重跑與原始執行的 `run_config.json` 相同，freeze 分不出來，改由版本確認擋下：
        `uv run python -m eval version-check --set pilot`（唯讀；exit 1 = 有不是目前版本的 prediction，不評分；原本指向已刪除的「目前位置」第 3 步）。
        原因回報使用者，不自行改預算或設定。
      - 評分表的「Budgets, usage and visible data」段寫推論主機與 GPU（名稱、驅動、功耗上限），並列出前後 GPU 狀態沒有都讀到的 incident（latency 照樣保留）。
      - 之後：`uv run python -m eval gold-todo --set pilot` 產生 LLM 方法新引用的 evidence gold 工作表（只列新的；由使用者標註，decision 017）。
   3. （已由上面「下一步」5–9 取代）held-out：plan → freeze（freeze 之前再跑一次版本確認 `uv run python -m eval version-check --set pilot`，decision 021「審查（2026-10-11）」；`collect heldout-freeze` 現在由程式要求：目前 lock 有通過的 soak（soak #6 已滿足）、三個 LLM 方法的 Pilot `run_config.json`
      正好是 `llm_methods.json` 的設定（含 `host` = `gpu-server`）且分數是從那次執行算的，026 解讀 31、32；013 正式版要 LLM 結果）→ held-out 收集（`collect next --set heldout`，K = 5）
      → held-out 評測與 Gate。
   - 若使用者之後換回付費 API：另寫 decision、加 adapter，**第一次呼叫付費 API 前依 MACHINE_POLICY 報告用途、請求數、token 量與預估成本並等批准**，
     並在 freeze 之前用那個模型重跑 Pilot（029「對實驗的影響」）。模型選擇與 dump-all 的預算數值（decision 011「延後」第 2 項）屬於要由使用者決定的事項。

### 2026-10-11 之前的「目前位置」

**Pilot Set 正式收集完成；label review 與 evidence gold 標註都已由使用者完成（human:jingwen，2026-10-10）；第一張 baseline 表已產生。
A1 已由使用者決定（2026-10-10「照建議」：本機模型 qwen3.5 9B，decision 029「使用者決定（2026-10-10）：照建議」），`eval/llm_methods.json` 是 `approved`；
下一步是三個 LLM 方法在 Pilot 上執行（下一步 8.2，2026-10-11 完成；主 session、不需要使用者；2026-10-11 起依 029 修訂 1 是每個方法一次 `./tools/with-remote-ollama`、
不需要 heavy lock）。A0 已處理（grafana 的 plugin 下載關掉（decision 028）、
新 lock 的 soak #6 PASSED、背景安裝器維持現狀）；A3、A5 已於 2026-10-10 確認。**
- **使用者決定（2026-10-10）「照建議」與實作**（分支 `llm-approve`，已快轉合併進 main、已刪除；decision 029 文末、026 修訂 3、023「追加（2026-10-10，第三次）」、028「結果」）：
  1. 模型 qwen3.5 9B（`qwen3.5:9b-q4_K_M`，digest `sha256:6488c96f…3ea7`），Ollama 0.35.0；2. `num_ctx` 262,144（模型上限；預算不變，dump-all 仍是 120,000 proxy）；
  3. think 關；4. Ollama 版本**釘選**（不符就拒絕；held-out 結束前不升級 Ollama，含 Homebrew 自動更新）；
  5. LLM 執行也要求**高效能模式 + AC**：開始時與每次嘗試之前檢查（不符就停止、不寫該 incident、不用掉 held-out 嘗試），前後的樣本記在
     `results/<set>/<method>/power.jsonl`（不在 `run_config.json`、不在 prediction），之後的樣本不符就停止、結果保留、評分表列出那些 incident 的 latency 不是正式條件；
  6. `num_predict` 8192；7. freeze 另外拒絕：目前 env lock 沒有通過的 soak（026 解讀 31）、任一 LLM 方法的 Pilot `run_config.json` 不是要凍結的設定
     或 Pilot 分數不是從那次執行算的（026 解讀 32）；freeze 紀錄的格式與 held-out 的驗證不變，`heldout-freeze` 印出找到的 soak 報告與各 run_config 的 sha；
  8. grafana 的背景安裝器維持現狀。
  - `ollama.timeout_s` **維持提案的 3600**（不在八項之內；探測速度外插：約 23 萬 tokens 的 dump-all 呼叫約 33–43 分鐘，最壞約 50 分鐘、3600 的 83%）。
    要不要加長是使用者的決定（freeze 之前；Pilot 不需重跑），見 029「`timeout_s`」一節與 A1。（2026-10-16：Pilot 上沒有觸發，維持 3600。）
  - **審查（2026-10-10，只拒絕更多或只增加紀錄）**：`timeout_s` 改回 3600（實作時曾改成 7200，不在使用者同意的範圍）；`power.jsonl` 每一行另記
    `run_config_sha256`，freeze 拒絕「中途停止的 Pilot 執行留下前一次執行的 prediction」（026 解讀 32，原本只靠流程）；held-out 失敗嘗試的 latency
    不是正式電力條件時評分也列出（`failed_not_formal`）；補上不可重試錯誤 / 不合格 prediction 之後電力紀錄的測試；023 的解讀清單補 31、32。
  - 測試：1065 passed（`-m "not network and not docker_daemon"`）；電力一律 monkeypatch，沒有執行任何模型、server、Docker 或 `pmset`。
- **使用者決定（2026-10-10）與實作**（023「使用者決定」的「追加（2026-10-10）」）：
  1. 統計 baseline 在 Pilot 上的那一次修訂**放棄**：stat-anomaly 維持 v2（decision 014「補註（2026-10-10）」；freeze 的 Pilot 修訂宣告 014 = waived，
     freeze 檢查強制這一項）。
  2. held-out **待人處理的 slot** 選 b，與 Pilot 相同：人看過 run record 後
     `uv run python -m collect ack-failures --set heldout --slot <slot> --reason … --decided-by …`，該 slot 重新計數再收，再 3 次無效又待人處理
     （ground-truth 側 `failure_acks.jsonl` 只附加；沒有通過的 freeze 檢查、未知 slot、不是待人處理的 slot、`heldout_incidents.json` 已存在時拒絕、什麼都不寫；
     被確認的 run group 留在所有紀錄與清單的 run group 清單；清單另記錄確認、載入時比對；「3 個 slot 就停止」數確認之後仍待人處理的 slot；
     未觸發 / 關閉的處理與 Pilot 不變）。decision 026 修訂 2（解讀 11、12）。
  3. freeze 之後的修正路徑：使用者選**「沒有偏好」** → 不實作，維持現況（見 A4，freeze 之前仍可決定）。
  4. held-out 撤回：**不允許**（維持預設，026 解讀 30）。
  - **審查（2026-10-10，026 修訂 2 審查；只拒絕更多）**：讀取端原本接受寫入端永遠不會寫的 held-out 確認（手寫一行就能讓 open 的 slot 提前重新計數），
    改為每一筆都必須等於 `ack-failures` 當時會寫的內容（該 slot 全部未確認的失敗、至少 3 個），否則所有 held-out 步驟停止（026 解讀 11）；
    freeze 檢查強制 014 = waived（026 解讀 10）；補上確認已關閉的 slot、兩行重複確認、格式錯誤的行、CLI 參數防護、清單寫出後損壞的確認檔的測試；
    023 狀態行改為「決定三項、一項沒有偏好」，014 補註只留使用者的決定與證據（理由標明是原 A2 建議的理由）。
  - 測試：947 passed（`-m "not network and not docker_daemon"`）；新增的測試只用 synthetic fixture，沒有執行任何收集、Docker 或付費 API。
- **label review 結果**：10 個都是 `fault_exercised = true`、`saw_method_outputs = false`；affected 與 user symptom 全部維持 a priori；
  7 個補了 notes（實際觀察，例如 emailMemoryLeak 沒有 OOM、recommendationCacheFailure 4 次 OOM、adHighCpu 時多數服務 p95 小幅上升）。
  coverage：traces origin 10；metrics origin 9、symptom_only 1；logs none 5、origin 3、symptom_only 2（逐案見 `label_review.json`）。
- **第一張 baseline 表（stat-anomaly v2，Pilot，n = 10，用 reviewed label）**：fault_type 0.30、origin_top1 0.60（top3 0.90）、affected_f1 0.77、symptom_exact 0.50；
  失敗 8 個 = mechanism 4 + rule_limit 4；easy / hard 的 origin_top1 都是 0.60。evidence existence 1.0、弱標籤 temporal / service 1.0、origin 0.625。
  （`data/external/results/pilot/stat-anomaly/table.md`）。**統計 baseline 維持 v2**：沒有發現設計缺陷，使用者 2026-10-10 決定放棄 decision 014 在 Pilot 上的那一次修訂。
- **evidence gold（decision 017）完成**：28 筆（8 個 incident；INC-003、INC-008 沒有引用）、方法盲標，25 筆 relevant。stat-anomaly 的 gold precision 0.906（coverage 1.0），弱標籤 temporal + service 1.0：差在 INC-006 三筆落在 fault 時間窗、affected 服務但看起來正常的訂單（弱標籤算 relevant、人判 not relevant），正是 SPEC §9 要分開報的原因。LLM 方法加入後，它們的引用要另外補標（gold-todo 只會列出新的）。
- **Pilot incident**（每個 fault 一個；RG-002 / INC-001 撤回）：

  | incident | fault | run group | 難度（leakage audit） |
  |---|---|---|---|
  | INC-002 | paymentFailure 100% | RG-003 | easy |
  | INC-003 | productCatalogFailure on | RG-007 | easy |
  | INC-004 | paymentUnreachable on | RG-008 | easy |
  | INC-005 | cartFailure 100% | RG-010（RG-009 無效） | easy |
  | INC-006 | intlShippingSlowdown 10sec | RG-014（RG-011–013 無效，使用者 ack） | hard |
  | INC-007 | productCatalogLockContention on | RG-015 | hard |
  | INC-008 | adHighCpu on | RG-016 | hard |
  | INC-009 | adManualGc on | RG-017 | hard |
  | INC-010 | emailMemoryLeak 1000x | RG-018 | hard |
  | INC-011 | recommendationCacheFailure on | RG-019（fault 期間 recommendation 重啟 4 次，review 時確認） | easy |

  - 有效 run group 10 / 收集的 run group 18（RG-001、004–006、009、011–013 無效；grafana plugin 下載逾時 5 次、fault 關閉沒生效 2 次、RG-001 暖機不穩定）。
    修訂 5 之後（RG-014–019）6 個 run 全部一次有效，12 次 flag 切換都一次寫入就在 1.3 s 內生效。
  - leakage audit：10 個 incident 的詞彙命中全部 0（policy v1 經得起 Pilot）；難度 easy 5、hard 5、medium 0。
  - normalize / replay / a priori label 全部完成；label review 工作表（`label_review_todo.json` 與好讀版 `.md`）全部產生。
- **統計 baseline（stat-anomaly）已在 Pilot 上執行並評分**（`data/external/results/pilot/stat-anomaly/`），**但在使用者完成 label review 之前不在任何地方報告數字**：
  decision 018 §4 要求 review 在看到方法輸出之前完成（看過的會在表上註明）。review 完成後再列出分數、寫第一張 baseline 表。
- **合併**：分支 `heldout-protocol`（held-out 工具、Gate 計算、合成範例與 demo，decision 026、027）已在 Pilot 收完後快轉合併進 main 並 push；918 passed。
- **兩種失敗原因**：
  1. **grafana 下載 plugin 逾時**（RG-004–006、RG-011、RG-012）：暖機前 aborted_unstable，只浪費約 5 分鐘、不影響資料；網路慢時發生（grafana.com 3–9 s）。
  2. **fault 關閉沒生效**（RG-009 cartFailure、RG-013 intlShippingSlowdown，`flag_unconfirmed`）：開啟都在 0.1–0.7 s 內確認，關閉在 10 s 內沒確認；
     RG-013 的 raw trace 顯示關閉寫入 105 秒後 shipping 仍有 10 秒延遲 → flagd 根本沒讀到關閉的設定，fault 延續到 recovery。判無效是對的（否則 label 錯）。
     已處理（decision 009 修訂 5）：單獨 flagd container 的 probe 沒有重現（rename 與同一個 inode 寫入各 40 次切換都在 1.06 s 內生效），
     「rename 換 inode」的推測沒有被證實；harness 改為同一個 inode 寫入、3 s 內沒生效就重寫，每次查詢記錄 flagd 提供的 variant（`served`）。
- **正式收集**：固定高效能模式 + AC 供電（decision 025 修訂 3；preflight 與時間窗內每分鐘取樣都檢查，不符就拒絕 / 判無效）。
  收集期間 main checkout 必須保持乾淨、不改 `collect/`、`env/`：其他開發在獨立的 git worktree / 分支上做，Pilot 收完後再合併。
- **LLM 方法**：付費 API 由使用者決定先延後；2026-10-10 使用者批准本機模型 qwen3.5 9B（A1、decision 029），下一步在 Pilot 上執行（2026-10-11 已執行）。
- **已完成的 Core 範圍**：（當時的表列出三個還在分支 `heldout-protocol` 的項目；它們已在 2026-10-10 合併。最新的表在上面「目前位置」。）

- **本 session 的三輪審查**，找到並修正的都是真實資料才會出現的 bug：
  - 程式碼審查：10 項；
  - 時鐘與單位稽核：9 項；
  - 在無 fault 的真實 snapshot 上試跑：發現 CPU 量測 bug、統計 baseline 在無 fault 時大量誤報、render 把 46% log 行的時間截掉、leakage 樣板出現大量假的 fault 專屬樣板。
- **非正式冒煙測試 #1（`collect smoke`，資料只在 scratch，永不進任何 set）**：2026-10-08 18:08Z 完成，paymentFailure 100%，normal / fault / recovery 各 2 分鐘。
  - 收集 → normalize → replay（每個 id 都能解析）→ label → leakage audit（easy、詞彙命中 0）→ 評分**全部走通**；run group valid，時鐘差 0.014 / 0.021 s。
  - 資料上故障清楚：payment fault 期間 error ratio 1.0（每分鐘只有 4–6 個 span）、checkout 0.23、frontend 0.3%、frontend-proxy 0.2%；
    accounting 在 fault 期間 0 span（訂單失敗 → Kafka 沒訊息；依規則「流量變少不算 affected」，review 時要注意）。
  - review 工作表與 Agent 7 個工具在真實資料上正常（建索引 1.3 s、每次查詢 < 0.05 s）。
  - stat-anomaly **不作答**：時間窗只有 6 分鐘，參考段固定前 10 分鐘 → 沒有可評的分鐘（設計如此，不是 bug）。
    因此冒煙測試的 normal 改為 10 分鐘、並加上 review 工作表一步（開發工具，非實驗設計；正式收集協定不變）。
- **非正式冒煙測試 #2**（2026-10-08 18:35Z，normal 10、fault 2、recovery 2 分鐘，commit `f00a983`）：整條 pipeline 走通，含 review 工作表；run group valid。
  stat-anomaly 第一次在真實 fault 資料上作答：fault_type、origin_top1 對；affected precision 1.0 / recall 0.5（漏 frontend、frontend-proxy）；
  symptom 錯（edge 的 error ratio 約 0.3%，低於門檻）；evidence 4 筆都存在、弱標籤 temporal / service / origin 全 1.0。
  **這是非正式資料，不依它調整任何門檻或規則**（統計 baseline 只能在 Pilot 上修訂一次，decision 014）。
- **離線檢查（冒煙測試 #1 的真實資料，不需 lock、沒有付費 API）**：dump-all 打包 119.7k proxy tokens（0.5 s），fault 的 error 群組都在；
  retrieval 的 BM25 查詢「error」第一筆就是 payment 的 fault span；用照腳本行動的假模型跑 Agent 執行框架 → 評分 → evidence → 失敗分類，
  答對與答錯（`not_seen`）兩條路徑都正確；錯誤的 fault_family 被正確拒收 3 次後記為放棄作答。
  觀察（不需改）：frontend-proxy 的 Envoy access log 本文含絕對時間戳，不會洩漏 fault 時間（normal 長度有 jitter、seed 只在 ground truth）。
- **decision 024（SPEC §7 報告）**：每次 `eval run` 把預算、model、可見資料範圍寫進 `run_config.json`；評分表新增「Budgets, usage and visible data」
  （usage 各欄的 n / mean / median / max、總成本、停止原因、實際看過的 record 與概覽比例）。只報告、不計分。
  另加測試：dump-all / retrieval 送給模型的所有文字都通過詞彙檢查、不描述收集協定（decision 015 §6）。測試 604 passed。
- **`collect pilot-loop`**（SPEC Week 1「自動化 collect → normalize → label」）：next → 一個 run（只在 run 期間持有 lock）→ process，重複到收齊或需要人；
  之後自動 leakage → stat-anomaly。只是把既有步驟串起來，不改任何協定；重新啟動時先補處理「有效但還沒有 label」的 incident。測試 615 passed。**今晚不執行**（電力模式，A7）。
- **decision 025**：run record 與 manifest 記錄收集開始時的電源與 `pmset` 電力設定（唯讀，不改任何設定）；`collect status` 列出每個有效 run 的模式。
  要用哪一種模式收集是使用者的決定（當時的 A5，已處理：decision 025 修訂 3）。測試 608 passed。
- **held-out 工具、Gate 計算、合成範例與 demo（分支 `heldout-protocol`，合併審查後 918 passed（`-m "not network and not docker_daemon"`））**：原本的三個分支
  `heldout-protocol`、`gate-analysis`、`synthetic-sample` 已在 2026-10-10 合成 `heldout-protocol` 一個分支（也含 main 到 `9585027`：
  decision 009 修訂 5、025 修訂、撤回、`ack-failures`）。（當時）還沒合併進 main——**2026-10-10 Pilot 收完後已快轉合併進 main 並 push**（918 passed，見上面「合併」），
  下面當時寫的合併指示已完成：剩下的 Pilot run 與 Pilot 評分都用合併後的程式。
  - **held-out 工具（decision 023 實作說明、026）**：
    `collect heldout-plan` → `heldout-freeze` → 每個 slot `next` → `run --set heldout`（不接受 `--seed`）→ `process` → `eval leakage --set heldout`
    → review（`collect review-sheet` / `collect review`）→ 未觸發的 slot 重收 → `collect heldout-list` → `eval run|score --set heldout`
    → `eval compare` → `eval gate`。沒有 freeze 紀錄時所有 held-out 收集與方法執行一律拒絕；
    **plan、freeze 與收集都要等 LLM 方法已批准並在 Pilot 上跑過**（2026-10-10 已批准；Pilot 上的執行是下一步 8.2，2026-10-11 完成；freeze 另由程式檢查 soak 與 Pilot 的 LLM 設定，026 修訂 3）。freeze 之前必須 commit：API adapter（029 的 Ollama adapter，已完成）、013 正式版（現在是「下一步」5）
    （026「待使用者決定」1 的機制已實作；A4 若在 freeze 前改為要修正路徑，那個程式也要在 freeze 前 commit）；freeze 之後只能改 NEXT.md 與新增 decision 檔（README 也不能改）。
    待人處理的 slot 只記 slot id 與非 valid 的 run group id；人看過 run record 後 `collect ack-failures --set heldout --slot <slot>` 確認、重新計數再收（2026-10-10）。
    電力條件對 held-out 一樣成立（026 解讀 29）。
    **026 修訂 1（程式審查後）**：held-out run group 一律不能撤回（撤回只用於 Pilot；手寫的撤回紀錄讓所有 held-out 步驟停止）；
    方法的 `run.lock` 存在時拒絕評分；transcript 先寫、prediction 最後寫；`up_at` 在 run 任何可能失敗的步驟之前記錄。
    **026「待使用者決定」1–3** 已由使用者在 2026-10-10 處理：1 選 b（已實作）、2 沒有偏好（維持現況，見 A4）、3 不允許。
  - **Gate 計算（023「實作說明：Gate 計算」）**：
    `python -m eval gate --method agent --against stat-anomaly --set <set>` 只讀已寫好的 scores.json 與 `eval compare` 輸出（不跑方法），寫 `gate.json` / `gate.md`：
    條件 1 讀 compare 的 origin_top1 paired 下界（對每個統計 baseline，compare 記錄 scores 的 sha，過期就拒絕）；條件 2（held-out 的 K 用 slot 數，缺格不降低 ⌈K/2⌉）；
    條件 3；coverage 比例、各 fault 等權平均 / 缺格清單、§7 的各 fault k/K 與差異方向只描述（每個 `eval score` 也列出等權 / 缺格）。
    held-out 才是 Gate 判定，Pilot 只是診斷、不是 Gate 判定；Agent 沒有分數（A1）時 exit 2、不寫檔。
    held-out 的 gate 輸出不列 incident id 或 run group id；Pilot 上 K < 2 的 fault 不評估條件 2（使用者 2026-10-10 已確認，原 A5）。
  - **合成範例與 2 分鐘 demo（decision 027）**：
    `uv run python -m collect sample --out data/samples/synthetic` 以程式產生 raw、經真正的 normalize 寫出 `INC-000` / `RG-000`（28 分鐘、280 spans、
    38 logs、112 metric points、全部約 250 KB；snapshot 與 ground truth 的一部分分開），`uv run python -m eval demo` 只讀範例、在記憶體裡跑
    leakage audit、印出分層分數並聲明不是結果（表頭也標明）。
    真實 snapshot 永不進 git：hygiene 測試只接受 `data/samples/synthetic/` 一個目錄（測試逐 byte 重產比對的那個），每個檔案以相同 sha256 列在
    `synthetic: true`、產生器 `collect.sample` 的 `sample.json`，內容只能出現 `INC-000` / `RG-000`（`collect calibrate` 的 soak snapshot 也叫
    `INC-000`，id 本身不代表合成）。`incidents_in` 遇到 `RG-000` / `INC-000` 直接拒絕。
    **Pilot 修訂 011（policy）時**（014 的修訂已在 2026-10-10 放棄），`tests/test_sample.py` 會失敗到範例重產為止：重新凍結並釘選 policy 之後
    `collect sample --out data/samples/synthetic --replace`，與修訂放在同一個 commit（027「對實驗的影響」）。
  - **合併審查（2026-10-10，三個部分合在一起之後）**：`eval` CLI 把 `CallError`（API / transport 錯誤）印成 `error: …`、exit 2（原本是 traceback；
    Pilot 沒有嘗試紀錄，見 A1）；held-out 的 `compare-*.json` 不再帶 incident id 與 valid run group id（原樣複製了 scores.json 的
    `excluded` / `closed_slots`；與 gate 一致，023「Gate 計算 / 輸出」更正）；026 解讀 11 更正（held-out 的 slot 無效上限沒有 Pilot 的
    `ack-failures` 重新計數；**已由 026 修訂 2 取代**，2026-10-10 使用者決定之後 held-out 也有 `ack-failures --set heldout --slot`）並在「待使用者決定」1 註明 Pilot 前例；027 補上 Pilot 修訂時重產範例的順序；README 的 held-out 段補上
    `collect review`、未觸發 slot 的重收、`eval compare` 與 `eval gate`，「評分」段說明 gate.json / gate.md。

### 上次完成（session 紀錄）

#### 2026-10-08 晚 – 10-09（session 4）：細項紀錄

- 記憶體設定已凍結（soak #2）。soak #3（raw export 的新 lock）：R1–R6、R8、R9 通過，R7 失敗 → 維持 FAILED。
- soak #4（同一個 lock）：R7 失敗在 OpenSearch 清佇列時的 ambient 拒收、R8 失敗在一行 `{}`（空的 MetricsData）；raw 完整（accounting 平衡）。修訂 3 只放行 opensearch exporter 的關閉錯誤、把 `{}` 計為空訊息；memcg 探測 container 改名 `ii-probe-…`（policy 當 harness 排除）。soak #4 維持 FAILED。
- R7 失敗原因（診斷 run 重現）：pipeline 都正常關閉後，collector 把 self-telemetry 推給自己已關閉的 4318 → exit 1。
  R7 修訂為「exit 0，或 exit 1 且關閉 log 證明只有這個錯誤」（decision 008 修訂），soak #4 用新標準判定。
- decision 012：docker_stats receiver 啟動 race 讓 shipping 整個 run 沒有 container metrics → up 後補送 no-op `docker update`；
  incident 視窗內缺任何 SUT container metrics 即無效。**補送是否有效還要診斷 run 確認**（`tools/rescan_diag.py`，見下一步 2）。
- loss accounting 完成（decision 008 修訂 2）：soak #3 視窗內 receiver accepted = file exporter sent（三種 signal 完全相等），沒有旗標。
- review workflow（normalize / 收集協定 / replay，24 個確認問題）全部修正並測試：FA-11、X8 套用到所有可見字串、check_snapshot 解碼檢查、
  double 編碼、G0 policy sha 與乾淨 checkout、manifest 先驗證再發布、seed 移到 ground truth（002 / 003 修訂）、report 計數與 schema、
  calibrate 可重跑與凍結條件 F1–F6（decision 011）、取樣失敗只看 normal period、verify-running、crash 也留 run record、收尾遮蔽訊號（009 修訂 2）。
- normalize policy v1 **已凍結**（`sha256:95bc4b07…`）；normalize 會檢查 status、釘選 sha、乾淨 checkout。
- Day 1 清單：1 ✅、2 ✅、3 ✅、4 ✅（待凍結）、5 工具就緒、6 工具就緒。
- 評分與 baseline（decision 013–015）：prediction 格式與分層評分、時間框架（只給「前 10 分鐘正常」）、統計 baseline v1、leakage audit v1；`python -m eval run|score|leakage`、`python -m collect label|freeze`。
- **Pilot 清單已預先登錄（decision 016）**：10 個 fault 與各自的 a priori label（`collect/pilot.py`）；origin 規則（flag 改變誰的程式 / 設定）、
  規則 3 補充（非 origin 只算錯誤或延遲，OOM / 重啟算錯誤）、user_symptom 在 edge 判定、fault 沒被觸發就重收。`collect run --set pilot` 只收清單上的 fault，`collect label` 只從清單取答案。
- **evidence relevance（decision 017）**：pool = 各方法引用的聯集；弱標籤 temporal（fault 窗 + 60 s）/ service / origin；人工 gold 每個方法每個 incident 盲抽 5 筆、只能由人標、不可改；
  `python -m eval gold-todo --set pilot` → 填表 → `python -m eval gold-add --incident … --file … --annotator human:<name>`；score 表分層列出 existence、弱標籤、gold precision。
- 評分必須先有 leakage audit；詞彙命中不是 0 的 incident 不進任何評分、表上列出；主要指標依 Easy / Medium / Hard 分層（decision 015）。
- **label review（decision 018）**：`python -m collect review-sheet --incident <INC>`（ground truth 側工作表：a priori、要檢查的項目、各服務 normal / fault / recovery 摘要、container 事件）→
  使用者填表 → `python -m collect review --incident <INC> --file … --reviewer human:<name>`；寫出另一份 `label.reviewed.json`（a priori 不變、origin 不可改、每個差異要有理由）；
  評分 / leakage / relevance 優先用 review 過的 label，`fault_exercised = false` 的 incident 不進評分。
- **統計 baseline v2（decision 014 修訂 1）**：在無 fault 的校準 snapshot 上試跑發現 v1 把 18 個服務全判 affected：
  docker_stats 的 `container.cpu.utilization` 在這個 stack 是累積比例（量測 bug）→ CPU 改用 `container.cpu.usage.total` 的增量（derive v4）；
  門檻改為每個特徵在無 fault 資料上的最大 z（error 3、warn 3、cpu 3.6、memory 34、p95 45）。只用無 fault 資料，不占「Pilot 上修訂一次」的額度。
- **leakage 樣板修訂（decision 015 修訂 1）**：含數字的整個字遮成 `<n>`（商品 id 不再產生大量假的 fault 專屬樣板；無 fault 資料上 472 → 2）。
- **Agent 工具 v1（decision 019，`agent/tools.py`）**：decision 011 §5 的 7 個資料存取工具、sqlite 索引（依 content digest 快取在 `data/external/cache/`）、
  時間排序 + 子字串比對（沒有排名）、呼叫數 / proxy token 預算、exposure log。尚未接任何 LLM（模型與預算數值待使用者決定）。
- **Agent 執行框架 v1（decision 020，`agent/prompt.py`、`agent/harness.py`）**：共用任務說明（只有 decision 014 那一句框架與答案空間）、
  tool-use 迴圈、`submit_diagnosis` 結構化提交（驗證失敗最多更正 2 次，否則算放棄作答）、回合 / 工具預算到了強制提交、usage 與 transcript。
  只有模型介面，**沒有接任何付費 API**。
- **Dump-all 與 retrieval baseline（decision 021）**：共同的概覽區塊；dump-all = 概覽 → error 等級 record 依樣板分組 → 每分鐘輪流的時間分層樣本，在 B 內從尾端截；
  retrieval = 模型提 ≤ q 個查詢 → 每個 BM25（FTS5）取 k 筆 → 依時間排序交回 → 提交。預算建議值（B 120k、q 8、k 25、Agent 40 次工具 / 120k tokens / 30 回合）**待使用者決定**。
- **失敗分類 v1（decision 022）**：origin 或 fault_type 錯 = 失敗，依序歸一類：no_answer → coverage（review 的 telemetry_coverage 看不到 origin）→ mechanism →
  not_seen（exposure 沒有 origin 在 fault 期間的證據）→ seen_misread（看到了仍判錯 = 推理失敗）→ rule_limit（統計 baseline）。score 表列出各類次數。
- **Held-out 協定（decision 023，當時 Proposed；2026-10-09 使用者決定 K = 5 之後 Accepted）**：與 Pilot 相同的 10 個 fault、每個 K 個（使用者決定）、隨機 block 順序、方法執行前 review、freeze 紀錄、Gate 用單一 paired 檢定。
  已實作與 K 無關的分析：`python -m eval compare --method A --against B --set pilot`（paired run-group bootstrap、leave-one-fault-out）。
- 沒有進入 Advanced / Optional；沒有任何付費用量。測試：602 passed（`-m "not network and not docker_daemon"`）。

#### 2026-10-08 session 3（decision 004–007、soak 工具、label schema、soak #1）

- 使用者決定把 product-catalog 的 memory limit 調到 64 MiB → decision 004（事先固定的 soak 通過條件 R1–R6 與升級規則）。
- decision 005：`ask_agent` 標為 known ambient failure（先不刪）；OpenSearch 不得作為 snapshot / source of truth。
- `env/compose.overrides.yaml` + `env/soak.py` + `python -m env soak`（TDD）。沒有 heavy lock、取樣窗 < 30 分鐘、已有本 Project 的 container 都會拒絕；
  `compose up` 失敗或中途失敗都會 `down` 並寫出報告。
- Docker Desktop 被外部 session 停止（09:32:48Z）→ 使用者回覆可繼續使用 → 本 session `docker desktop start`（理由記在 Blocked 的歷史紀錄）。
- **soak #1**（`data/external/soak/20261008T095930Z/`，64 MiB）：**FAILED**。
  - R1 / R2：checkout（upstream 20 MiB）在暖機期 10:01:05Z 被 memcg OOM-kill（kernel log 保存在 `oom-evidence.*`；dry run 09:27:18Z 也發生過一次）。
  - R6：product-catalog p95 51.4 MiB = 80% of 64 MiB，視窗內碰到上限 22 次。
  - R3 / R4 / R5 通過（0 個 5xx / 1,966 request；health 全程正常；telemetry 每分鐘都有）。
- 發現 R2 的量測漏洞：container 重啟會重建 cgroup，`memory.events` 歸零。修正為加上 `docker events` 的 oom / exit 137 事件，
  並在 soak #1 報告產生**之前**寫進 decision 004「修訂」（更嚴格，門檻不變）。R6 改為判定所有被 overlay 調整的服務。
- 依規則：product-catalog → 128 MiB（004，唯一一次升級）；checkout → 64 MiB（decision 007，比照 004 的規則，可一次升到 128）。lock 已重新 resolve。
- **Day 1 #2 label schema**：decision 006、`schemas/incident_label.schema.json`、`collect/labels.py`（commit `5aba810`）。
- 兩個 review workflow（label schema + R2 修正）：18 個確認的問題都已修正。
- M2 raw export 研究（4 主題 + 逐條反向覆核 + 彙整）→ **decision 008**（raw pipeline 在任何 processor 之前、寫進 collector container、收尾時 `cp` 出來；
  raw 以 run group 為單位放在 `data/external/raw/<RG>/`，Agent 只能讀 `incidents/<INC>/normalized/**`，SPEC §2 目錄差異已記錄）。
  已實作（TDD）：`env/otelcol-config-raw.yml`、`collect/rawfile.py`（串流掃描 OTLP JSONL）、`DataLayout.raw_dir` / `is_agent_readable`、
  soak 的 R7–R9 與 drain → stop → cp 收尾。研究筆記與 decision 001 的三處文件差異已更正。
- GitHub：private repo `jingwenliu0113-afk/incident-investigator` 設為 `origin`，`main` 已 push 並追蹤 `origin/main`
  （push 前稽核全部 history：沒有 telemetry / 資料 / Docker artifact / secret；`.gitignore` 補上 secret 與金鑰檔）。之後每個測試通過的 commit 都 push。
- soak #2 PASSED → 記憶體設定凍結。raw export 的 overlay 與 lock 已更新；鎖定的 collector 0.159.0 `validate` 通過合併後的 config。
- **decision 009（run group 收集協定）**：暖機 → 穩定閘門 G1–G3（最近 5 分鐘）→ normal（10 + U(0,5) 分鐘，seed 決定）→ fault → recovery → drain → raw → down；
  normal period 有異常、raw 不完整、flag 生效未確認、sampling 錯誤都判為無效（保留紀錄、不給 incident id）。
  已實作（TDD）：`collect/faults.py`（原子寫入 flag 檔、targeting rule、OFREP 確認）、`collect/validity.py`、`collect/rungroup.py`（orchestrator 與落地）、
  `collect/live.py`（真實 Docker）、`python -m collect run`。
- **decision 009 修訂**：recovery 改 5 + U(0,5) 分鐘、Pilot fault 一律 10 分鐘、時鐘漂移 > 1 s 判無效（避免窗長洩漏 fault 時間 / 類型）。
- **decision 010**：第一個 incident = `paymentFailure 100%`（Pilot、驗證 pipeline）；affected services = 自己出現因 fault 造成的錯誤或延遲的服務。
- **decision 011**（Core §4 設計 workflow：3 方向 × 3 評審 + 彙整）：ctel/1 snapshot（6 個決定性檔案、18 個 SUT 服務、資料時鐘原值、keyed id）、
  policy v1（X1–X10、控制面子樹 closure、Class A 樣板附 upstream file:line、靜默刪 token、隱私對齊）、GT-blind normalize、fail-closed `check_snapshot`。
  實作：`collect/otlp.py`、`policy.py`、`normalize.py`、`incident.py`（manifest）、`calibrate.py`、`snapshot.py`、`derive.py`、`replay.py`；CLI `normalize` / `calibrate` / `replay`。
- `MACHINE_POLICY.md` 新增「外部費用」：付費 API / 雲端 GPU / 付費資料服務在第一次使用前要報告用途、請求數、token / 運算量與成本，經使用者批准。
- 測試：397 passed（`-m "not network and not docker_daemon"`；`docker_daemon` 會跑一個幾秒的 `--rm` collector validate container）。

#### 2026-10-08 session 2（smoke test + baseline commit）

- 兩輪 Mac smoke test（都持有 heavy lock）。完整紀錄（含所有問題與數字來源）：`docs/smoke-tests/2026-10-08-m1-mac-smoke.md`。
  - Run 1（互動式）：28/28 container 跑的是鎖定的 linux/arm64 manifest；traces / metrics / logs 都有進 backend；flagd 原子寫入 0.33–1.04 s 生效。
    冷啟動 504 風暴；product-catalog 被 OOM-kill 一次，約 08:15:4x 起又卡住；OpenSearch 因 mapping 衝突逐筆拒收 1,624 次（308 個 export request 失敗）。
  - Run 2（不介入觀察 15 分鐘）：沒有 504、沒有重啟、沒有 probe 失敗；`verify-running` 全部通過。
    但 product-catalog 的 cgroup 全程在 17.1–19.9 / 20 MiB，碰到上限 86,416 次；`ask_agent` 約 5.4 次/分失敗；OpenSearch 的 mapping 拒收也持續發生。
- 新增 `env/runtime.py` + `python -m env verify-running [--wait N] [--platform …]`（TDD）：確認 pinned ref、index digest、平台 manifest、running、healthy、
  沒有連續失敗的 probe（Docker 在 Retries=20 時會把失敗遮蔽成 healthy）、沒有重啟；也會列出沒有 healthcheck 的服務。
- `.gitignore` 補上 Docker artifacts（`*.tar`、`*.tar.gz`、`*.tgz`、`*.tar.zst`、compose override）與 `*.log`；`tests/test_repo_hygiene.py` 守住「telemetry dump / Docker artifact / 大型資料不得進 git」以及「會被追蹤的檔案 < 1 MiB」。
- `MACHINE_POLICY.md` 新增「Mac Docker Desktop（Core 階段）」規則，包含 anonymous volume 的歸屬規則，以及診斷 container 要用 `--rm` / `rm -v`。
- 回填 decision 001 / 003 與研究筆記 §7 的 runtime 結果。Code review 一輪（另有一輪核對文件與原始證據），確認的問題都已修正。
- 清理本 session 自己的診斷資源：`alpine:3` image，以及 `ii-inspect-probe` 留下的 anonymous volume `ed5c71e9…`（已確認來源才刪除）。
- 第一個 baseline commit：`chore: establish core baseline`。

#### 2026-10-08 session 1

- 研究（5 個主題 + 反向覆核）→ `docs/research/2026-10-08-otel-demo-3.1.0-notes.md`。
- 決策 001（鎖 3.1.0 = `dedc017`）、002（manifest 與 ground truth 物理隔離）、003（traffic 與 seed 政策）。
- `env/`（lock 工具鏈）、`collect/`（provenance、layout、records、traffic）、`schemas/`，全部 TDD；兩輪 code review 確認的 14 個問題都已修好。
