# 030 — Held-out 最終結果的發布方式：README 在 freeze 封存，結果寫在固定的新文件

- 狀態：Accepted（2026-10-16，使用者決定 4 選 a）；在 freeze、任何 held-out 資料與任何 held-out 方法結果之前寫定。
  只決定結果寫在哪裡、寫什麼；**不改任何指標、門檻、Gate、切分、預算、評分、引用驗證或 freeze 的程式**（`collect/freeze.py` 不變）。
- 影響範圍：`README.md`（現在加一個預留連結）、held-out 評測之後的結果報告、`docs/decisions/` 的編號（100 保留）。

## 背景

- freeze 之後預設拒絕（decision 023 §6、026 解讀 7）：`collect/freeze.py` 的 `ALLOWED_AFTER_FREEZE` 只允許
  `M NEXT.md`、`A docs/heldout/slots.json`、`A docs/heldout/freeze.json` 與 `A docs/decisions/NNN-*.md`
  （`NEW_DECISION` = `docs/decisions/[0-9]{3}-[^/]+\.md`，只接受新增）。README、SPEC、既有的 decision、程式與測試在 freeze 之後都不能改；
  任何一個改了，`check_freeze` 讓所有 held-out 步驟停止。
- 所以 README 在 freeze 時就封存，而 held-out 的結果出現在 freeze 之後，不能寫進 README。
- 使用者原話（2026-10-16，第 4 項）：
  > README 發布方式選 a，Freeze 前預留正式結果連結，之後以固定的新結果文件及 decision 紀錄呈現，不修改封存的 README。

## 決策

### 1. 固定的檔名：`docs/decisions/100-heldout-final-results.md`

- 現在就決定，讓 README 在 freeze 之前能放連結。符合 `NEW_DECISION`，freeze 之後新增（`A`）會通過檢查（測試見下面）。
- **100 保留給這份文件**；一般的 decision 從 031 依序用到 099，不會撞號。031–099 用完時另寫 decision 決定，不用 100。
- 它放在 `docs/decisions/`，只因為 freeze 之後能新增檔案的目錄只有這裡；它是結果報告，不是設計決策。

### 2. freeze 之前

- README「結果」段現在加上指向 100 的連結，並寫明：held-out 評測完成之前這個檔案不存在，連結打不開。
- README 在 freeze 之前定稿（NEXT「下一步」4：Pilot 的 gold 數字），之後永不修改。README 的結果只有 Pilot（診斷用）。

### 3. held-out 評測之後

- 一個 commit 只做三件事：新增 `docs/decisions/100-heldout-final-results.md`（結果）、新增一份 decision 紀錄（當時下一個空的編號，031–099）、
  修改 `NEXT.md`。decision 紀錄寫：日期、freeze 紀錄、Gate 判定、§4 第 10 項的處理（若有）、下一步怎麼決定（第 13 項）。
- **README 不改**：freeze 檢查拒絕 `M README.md`（測試見下面）。
- **100 寫一次**：之後發現的錯誤寫進另一份新的 decision（031–099），寫明更正什麼、更正前後的數字，100 本身不改。
  這是流程規則，**不是程式檢查**：freeze 的檢查比較的是 frozen commit 與 HEAD，100 在 freeze 之後新增，之後再改它，對 frozen commit 來說仍是「新增」（`A`），
  檢查照樣通過（測試寫明這個行為）。

### 4. 100 的內容（只用既有的規則，不新增任何指標或比較）

1. **範圍與來源**：held-out set（decision 023：Pilot 的 10 個 fault 與 variant、K = 5、slot 順序由 master seed 決定）；`docs/heldout/freeze.json` 的 sha256；
   數字從 `data/external/results/heldout/` 的 `table.md`、`scores.json`、`compare-*.md` 與 `agent/gate.md` 轉寫，並列出 `gate.json` 記錄的 inputs sha256。
2. **模型範圍**：三個 LLM 方法用本機模型 qwen3.5 9B（decision 029：digest、Ollama 0.35.0 釘選、`num_ctx` 262,144、think 關、temperature 0；
   推論在 RTX 5070 Ti，029 修訂 1）。**結論只限於這個本機模型**，不推廣到其他模型。
3. **只用第一次執行的結果**（023 §5、§6）：每個（方法, incident）只跑一次；只有 `api_error` / `transport_error` 依停止原因重試、最多 2 次嘗試，全部記錄；
   列出每個方法的嘗試次數、失敗嘗試的用量。重試後仍沒有 prediction → 放棄作答，**留在分母**、算 022 的 `no_answer`（013 §2、026 解讀 19）。
   方法 bug 的修正版只能另列為探索性結果，永不取代第一次的分數（023 §6）。
4. **分層分數**（013 §2、§3）：每個方法的主要指標 fault_type、origin_top1、affected_f1、symptom_exact 並列（不合成一個數字），加上輔助指標；
   平均值與 run-group cluster bootstrap 95% 區間（10,000 次、seed 0、percentile）與 n。難度層：有 ≥ 10 個 run group 的層報區間，其餘只報 n 與平均（023 §7）。
   詞彙命中而排除的 incident、關閉的 slot 只以 slot、fault 與原因列出（015、023 §5）。
5. **Gate**（023 §7 與「實作說明：Gate 計算」）：照 `python -m eval gate --method agent --against stat-anomaly --set heldout` 寫出的 `gate.md` / `gate.json` 轉寫，
   不手算、不改寫：條件 1（每個統計 baseline 的 origin_top1 paired 差異、95% 區間與下界，下界 > 0 才成立）、條件 2（各 fault 的 K、⌈K/2⌉、答錯數、過半的類別）、
   條件 3（not_seen + seen_misread 的比例 > 0.5）與判定（`pass` / `not_passed`）。描述段照列：其他主要指標與 fault_type 的 paired 差異、LOFO 下界、
   各 fault 的 k/K 與差異方向、coverage 比例——都只是描述，不是 Gate 條件。
6. **各 fault 表**（023 §7、Gate 解讀 10）：每個方法的各 fault 平均、等權平均與所有計分 incident 的平均並列；缺格（關閉的 slot、詞彙命中排除）
   與 Pilot 之後移除的 fault（023 §1，附依據）都列出。
7. **失敗分類**（022）：每個方法的六類次數；Agent 的各 fault 類別（條件 2 用）。不只報成功的案例。
8. **Evidence**（013 §4、017 §4）：existence、弱標籤（temporal / service / origin / weak）、gold precision（含 coverage 與 n）分開列，永不合成。
   gold 由人盲標（017 §3）；一個方法的樣本全部判定之前不報它的 gold precision（017「對實驗的影響」），100 寫明沒有報告的原因與 coverage。
9. **預算、用量與可見資料**（024）：每個方法的預算、tokens、工具呼叫、retrieval、latency、cost、停止原因、`records_share` / `overview_share`；
   推論主機與 GPU 狀態，以及 latency 不是正式條件的 incident（029、026）。
10. **評測之後發現的 bug**（023 §6）：評分或稽核的 bug 修正後，修正前後的數字都報告，Gate 用修正後的數字；方法的 bug 只列探索性結果。
    freeze 之後程式不能改（使用者 2026-10-10 對修正路徑「沒有偏好」，維持現況：評測停止、由使用者決定），所以這一項通常不會發生；發生時照當時使用者的決定寫。
11. **Pilot 分開報**：Pilot 的數字只當診斷、不是 Gate 判定（SPEC §5、013 §3「Pilot Set 與 held-out 分開報，永不合併」）；100 只連到封存的 README 的 Pilot 表，不合併計算。
12. **不列任何 held-out incident id 或 run group id**（023 解讀 23 與「實作說明：Gate 計算」的「輸出」；理由見 026 解讀 23）：只用 slot 與 fault。也寫出 bootstrap 能說明與不能說明的範圍（023 §7「其他」）。
13. **下一步**：依 SPEC「Gate」——判定 `pass` 才可能進 Advanced（使用者 2026-10-16：不自行進入 Advanced，要使用者確認）；不通過時依 SPEC「收尾或改題」。
    100 只記錄判定與數字；下一步的決定寫在同一個 commit 的 decision 紀錄裡，由使用者決定。

## 為什麼

- freeze 的預設拒絕是 held-out 結果可信的前提；把 README 加進 freeze 之後允許的檔案，等於改 `collect/freeze.py`、放寬 freeze，不採用。
- 檔名現在固定：連結可以在 freeze 之前寫進 README；發布的位置與格式在看到任何 held-out 結果之前就定了，不依結果選。
- 用 100 而不是「下一個號碼」：一般 decision 會繼續增加，下一個號碼現在無法預知；100 與 031–099 不會撞號。
- 內容只列既有規則要求的東西：不在看到結果之後新增比較或指標（EXPERIMENT_RULES、CLAUDE.md「不得只回報成功案例」）。

## 放棄的替代方案

- **freeze 之後改 README**：freeze 檢查拒絕（`M README.md`），所有 held-out 步驟會停止；要允許就得放寬 freeze。
- **把結果放在 `docs/heldout/`**：freeze 之後那裡只允許新增 `slots.json` 與 `freeze.json`。
- **用 freeze 時下一個空的 decision 編號**：之後的一般 decision 也會用編號，README 的連結可能指到別的文件。
- **只在 NEXT.md 寫結果**：NEXT 是工作紀錄，會一直改；正式結果要固定在一份寫一次的文件。

## 對實驗的影響

- 只影響結果寫在哪裡；指標、門檻、Gate、切分、預算、評分、freeze 程式都不變。030 本身在 frozen commit 裡，freeze 之後不能改。
- README 現在加上連結（held-out 評測完成之前打不開）；`docs/decisions/README.md` 註明 100 保留。
- 測試（`tests/test_heldout_freeze.py`）：
  - 新增 `test_the_final_results_are_a_new_decision_file_after_the_freeze_and_the_readme_stays_frozen`：在真的 git 歷史上，freeze 之後的 commit 新增
    `docs/decisions/100-heldout-final-results.md` 與一份 031 decision → `check_freeze` 與 `commit_problems` 都沒有問題；之後再改 100 仍通過（上面 §3 寫明的程式限制）；
    改 `README.md` → 只有一個問題，指名 `README.md (M)`。（把 `NEW_DECISION` 改成只接受 0xx 時這個測試會失敗，已確認。）
  - 既有的 `test_next_and_new_decision_files_may_change_after_the_freeze` 與 `test_each_departure_from_the_frozen_state_is_one_named_problem[readme]`
    用合成的 observed 檢查同樣兩條規則。
- 沒有執行任何收集、模型、Docker、ssh 或網路；沒有寫 `data/external`。
