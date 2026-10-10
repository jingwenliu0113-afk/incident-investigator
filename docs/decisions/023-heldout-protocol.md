# 023 — Held-out 評測協定

## 狀態 / 影響範圍

- **狀態**：Accepted（2026-10-09，使用者決定：K = 5，其餘依保守預設；見文末「使用者決定」）。本協定寫在任何 held-out 資料與任何方法結果出現之前。
  2026-10-10 使用者追加決定三項（014 放棄 Pilot 修訂、待人處理的 slot 由人確認後重新計數、不允許 held-out 撤回）；
  freeze 之後的修正路徑使用者選「沒有偏好」（不實作、維持現況，freeze 之前仍可決定）。同樣在任何 held-out 資料與 freeze 之前；
  見文末「使用者決定」的「追加（2026-10-10）」。同日另確認兩項（gold 標註量照 017 現行規定；Gate 解讀 4 的 Pilot 讀法），
  見「追加（2026-10-10，第二次）」。同日使用者批准 LLM 設定（本機模型，decision 029），freeze 多兩項檢查，見「追加（2026-10-10，第三次）」。
  - 標「Pilot 後定稿」的項目，要等 Pilot 的收集、review、leakage audit 與 LLM 方法試跑都完成，並在第一個 held-out run group 之前定稿一次。
  - 定稿之後，每次修改都另寫 decision log。
  - 看到 held-out 方法結果之後，永不修改。
- **影響範圍**：
  - SPEC §10 與 Gate（SPEC.md:309-320）。
  - `collect run|next|status --set heldout` 與 `eval run --set heldout`。
  - 013 正式版：§7 的 paired 比較與 Gate 判準會寫進 013 正式版，用掉 013 唯一的一次修訂。其他由 Pilot 引起的 013 修改，必須和這次併在一起。


> 產生方式：三個獨立設計（統計效力、洩漏與公平、可行性）× 三位評審，再綜合（2026-10-09）；文中的程式行號與數字已抽查。
> 本文件是 Proposed：Pilot 完成後定稿一次；需要使用者決定的事項列在文末，也列在 NEXT.md「Blocked / 需要使用者」。

## 背景

- **SPEC §10**：Pilot 不進 test；同一個 run group 不跨 split；結果要報 CI。
- **Gate 有三個條件**：
  1. Agent 明顯勝過最強的統計 baseline；
  2. 有可重現的穩定失敗案例；
  3. 錯誤主要來自推理路徑。
- **程式現況**：
  - `--set heldout` 目前一律拒絕（009 修訂 3；collect/__main__.py:32-34）。
  - `collect run` 仍然接受 `--seed`（:88、:239）。
- **既有規定**：
  - 018 §7：held-out 的 label 要在任何方法執行前 review 完成。
  - 011 §4：policy 要在任何 held-out 資料出現之前凍結。
  - 013–015、017、019–022：都在 held-out 之前凍結。
- **目前進度**：只有中止的 RG-001。統計 baseline 只有 stat-anomaly（eval/runner.py:48）。

## 決策

### 1. Fault 與 label（Pilot 後定稿）

- held-out 只用 016 的 10 個 fault，variant 也與 Pilot 相同。不加入以下 fault，也不加入新的 variant：
  - kafkaQueueProblems：沒有單一 origin；
  - loadGeneratorFloodHomepage：origin 不在 snapshot 裡；
  - adFailure：約 0.4 次/分，而且沒經過 Pilot 驗證。
- **進入 held-out 的條件**：該 fault 在 Pilot 至少有一個 review 過、且 `fault_exercised = true` 的 incident。
  - 移除 fault 只能依 pipeline、label 或有效性的證據（是否觸發、無效率、詞彙命中），不能依任何方法的分數（016:103）。
  - 預設做法：直接移除，不用未經驗證的 fault 替代，並在報告中列出。
- **a priori label**：以 `PLANS["pilot"]`（collect/pilot.py:65）為起點，寫成 `PLANS["heldout"]`。
  - 只吸收 Pilot label review 發現的差異，每一項都要寫理由。
  - origin 與 fault_type 不改（018 §2）。

### 2. 大小（K 在凍結前定案）

- 每個 fault 收 K 個有效 incident，N = 10K。
- 每個 run group 只切一個 incident（009 §1），所以 013 §3 的 run-group cluster bootstrap 就等於以 incident 為單位重抽。
- 不追加收集、不提前停止、不做期中分析。

下表是 Agent − stat-anomaly 的 origin_top1 paired 差異：
- 「可偵測差異」用常態近似、雙尾 95%、power 80%，兩個方法答案不一致的比例設為 25–40%。
- 「Gate power」用本文 Gate 的 percentile bootstrap 模擬，設定 Δ = 0.20、不一致比例 0.30。

| K | N | lock 時間（不含無效重收） | 可偵測差異 | Gate power |
|---|---|---|---|---|
| 4 | 40 | 約 30 小時 | 0.20–0.26 | 約 0.64 |
| 5 | 50 | 約 38 小時 | 0.18–0.23 | 約 0.74 |
| 6 | 60 | 約 45 小時 | 0.17–0.22 | 約 0.83 |

- N = 60 時，單一方法 accuracy 的 95% 區間半寬約 ±0.13。
- 單一 fault（6 個 incident）約 ±0.4，只能當描述。

### 3. 時間結構（不變）

- fault 一律 10 分鐘。
- normal = 10 + U(0,5) 分鐘，recovery = 5 + U(0,5) 分鐘，兩者用同一個 seed 抽樣（collect/rungroup.py:51-63）。
- 所以每個 fault 的窗長都是同一個分布，介於 25–35 分鐘（009 修訂 2、4）。
- 時間框架照 014 §1。

### 4. 順序、seed、收集的拒絕規則

- **順序**（延伸 016；Pilot 仍用固定順序）：
  - 共 K 個 block，每個 block 是 10 個 fault 的一個隨機排列。
  - 在凍結時用 master seed 20261009 產生，存成 slot 清單 H01–H{10K}，連同它的 sha256 一起 commit 之後才開始收。
- **seed**：
  - 每個 run group 由 SystemRandom 產生（collect/__main__.py:239），只記在 ground-truth 側（002 修訂）。
  - `--set heldout` 拒絕 `--seed`。
  - 無效的 run 用新的 run group、新的 seed 重收同一個 slot（009 §4）。
- **`collect run --set heldout` 在以下情況拒絕**：
  - 沒有 freeze 紀錄，或 checkout / env lock 的 sha 與 freeze 紀錄不符；
  - Pilot 或 Pilot 的 review 還沒完成；
  - flag / variant 不是 `collect next` 給出的下一個 slot；
  - slot 清單已經收滿。
- **無效次數改以 slot 計算**：
  - 原本 pilot.py:97、137 是以 fault 累計，那是為 K = 1 設計的。K = 6、無效率 25% 時，約有 98% 的機率會有某個 fault 停下來。
  - 新規則：
    - 同一個 slot 累計 3 個無效 run group → 該 slot 標為「待人處理」，記進 NEXT 的 Blocked，`collect next` 跳到下一個 slot。
      （2026-10-10 使用者決定：人看過 run record 後記錄確認，該 slot 重新計數、再收；見文末「追加（2026-10-10）」第 2 項。）
    - 同時有 3 個 slot 待人處理 → 全部停止收集，因為這可能是 stack 本身的問題。

### 5. Review、替補、清單凍結（全程看不到任何方法結果）

1. 全部 slot 收完 → process（normalize → replay → a priori label）→ 在 ground-truth 側跑 leakage audit。
2. 使用者 review 全部 label，`saw_method_outputs` 必須全部是 false（018 §4、§7）。
3. `fault_exercised = false` 的 slot：用新的 run group 補收一次，再 review（016 §5）。
   - 仍然沒觸發 → 預設關閉該 slot 並列出。
   - 這延伸了 pilot.py:134：原本的程式是交給人決定。
4. 詞彙命中不是 0 的 incident 不進任何評分，並列出（015）。不在 held-out 上改 policy（011 §4）。
5. 寫出 `heldout_incidents.json`，內容是 incident 清單，以及每份 reviewed label 與 audit 的 sha。在這之前，任何方法（包括 stat-anomaly）都不在 held-out 上執行。

方法執行的規則：
- `eval run --set heldout` 在以下情況拒絕：
  - `heldout_incidents.json` 不存在；
  - 方法程式、prompt、設定或模型的 sha 與 freeze 紀錄不符。
- 每個（方法, incident）只跑一次，不在 held-out 上試跑。
- 只有 API / 傳輸錯誤可以重試：依停止原因判斷，不看輸出內容；每個 incident 最多 2 次，全部記錄。

### 6. 凍結與 bug

**freeze 紀錄**（在第一個 held-out run group 之前寫好；Pilot 後定稿）包括：
- commit 與 env lock 的 sha；
- policy 版本：v1，或 Pilot 後唯一一次的 v2；
- 013 正式版；
- 014 的參數；
- 015；
- 017（含 gold 抽樣）；
- 019–022（含預算）；
- 模型、版本、temperature，以及 `llm_methods.json` = approved；
- `PLANS["heldout"]`、K、slot 清單。

各 decision 允許的「Pilot 上修訂一次」，在凍結前要嘛已經用掉，要嘛明確放棄。

**bug 的定義**：程式與已凍結的書面定義不一致。除此之外的修改都算設計變更，不允許。修正要寫 log；測試用 Pilot 或無 fault 資料，不用 held-out。

**方法執行前發現的 bug**：
- 收集或 normalize 程式的 bug：修好之後，全部 held-out 用同一個 policy 重新 normalize，或把受影響的 run group 判無效並重收。
- 如果需要新的 policy 或要改 env lock，就違反 011 §4 / 001：先停止收集，交由使用者決定。預設是排除受影響的 incident，不讓兩種設定混在同一個 test set。

**方法執行後發現的 bug**：
- 評分或稽核的 bug：改成符合書面定義，所有方法重新評分。Gate 用修正後的數字，修正前後的數字都報告。
- 方法的 bug：Gate 一律用第一次的結果。修正版只能另列為探索性結果；重跑會產生新的付費用量，要先經使用者批准。
- 門檻、prompt、預算、指標、incident 清單永不因 held-out 結果修改。

### 7. 分析與 Gate 判準

**區間**
- 沿用 013 §3：run-group cluster bootstrap，10,000 次、seed 0、percentile 區間。
- 新增 paired 差異：兩個方法用同一組重抽的 run group 計算。目前 eval/score.py:66 只算各方法自己的區間，這部分要另外實作。

**Gate 條件 1（唯一的主要檢定）**
- Agent − stat-anomaly 的 origin_top1 paired 差異，95% 區間下界 > 0。
- 凍結時如果有多個統計 baseline，Agent 必須對每一個都成立。
- 估計量是所有計分 incident 的平均。有缺格時就不再是各 fault 等權，所以另外報告各 fault 等權的平均與缺格清單，只作描述。

**fault_type 不進 Gate 判準**
- stat-anomaly 只能輸出 4 種 type，10 個 fault 中最多答對 6 個（016:106），兩個方法的差異有一部分是結構性的。
- fault_type 與另外兩個主要指標的 paired 區間都會報告，只作描述，不宣稱做過多重比較校正。

**穩健性報告（描述用，不是 Gate 條件）**
- leave-one-fault-out（LOFO）的 10 個下界、各 fault 的 k/K 與差異方向。
- LOFO 只看得出優勢是否依賴「單一」fault。如果把它列為 Gate 條件，K = 6 時 power 會從約 0.83 降到約 0.66。

**Gate 條件 2（可重現的穩定失敗，預設定義）**
- 至少有一個 fault，Agent 在 ≥ ⌈K/2⌉ 個 incident 上 origin_top1 答錯，而且這些失敗中過半屬於 022 的同一個類別。
- 對同一個 incident 重跑 Agent（檢查 LLM 抽樣的重現性）要付費，由使用者決定。重跑結果另列，不取代第一次的分數。

**Gate 條件 3**
- Agent 的失敗中，not_seen + seen_misread 的比例 > 0.5（022 §3）。

**其他**
- Agent 幾乎全對時，要另開新的集合並寫新的 decision，不屬於本協定。
- 難度分層：有 ≥ 10 個 run group 的難度層報 bootstrap 區間，其餘只報 n 與平均（eval/runner.py 目前一律只報平均）。難度和 fault 高度重疊（015）。
- **bootstrap 能說明的**：在同一個 stack、同一個 traffic profile、同樣這 10 個 fault（含 variant）、fault 10 分鐘的條件下重新收集時的變異，來源包括 traffic 時序、seed、單次 LLM 抽樣。
- **bootstrap 不能說明的**：
  - 不能推廣到其他 fault、variant 或系統；
  - 不分層重抽會讓 fault 組成也跟著隨機變動，所以相對於固定設計偏保守；
  - n 很小或比例接近 0、1 時，percentile 區間會覆蓋不足（例如某 fault 6/6 時區間寬度是 0）。

## 為什麼

- **只用經 Pilot 驗證的 fault**：label、variant 與 leakage 都只在 Pilot 驗證過（SPEC §5）。
- **fault 固定 10 分鐘**：
  - prompt 會把窗長給方法看（agent/prompt.py:26-27），所以窗長必須與 fault 無關。
  - 可變的 fault 長度即使與 fault 類型獨立，也會透過替補洩漏。例如 intlShippingSlowdown 在 10 分鐘內完全沒觸發的機率約 5%，5 分鐘約 22%；短窗被替補掉之後，留下來的窗長會偏長。
  - emailMemoryLeak 1000x 約要 6–8 分鐘才 OOM（研究筆記 §8:143、147）。
- **隨機 block 順序**：
  - 016:98 認為每個 run group 都從乾淨的 stack 開始，所以順序沒有影響。
  - 但 009:141-142 記錄了各次 soak 的記憶體貼近 limit 的程度不同，lock 也與其他 Project 共用，多天收集可能會漂移。
  - 隨機化沒有額外成本，收集中途停下時各 fault 仍然平衡。
- **只用一個 paired 主要檢定**：兩個方法各自的區間重疊，不等於沒有差異；事先只指定一個比較，可以避免挑選結果；power 表也和實際的判準一致。
- **Gate 用第一次的結果**：通常是方法表現差才會去找 bug，如果用修正版取代，就等於多抽一次。

## 放棄的替代方案

- **加入新的 fault 或 variant**：label 沒有驗證過，也會稀釋每個 fault 的樣本數。
- **可變的 fault 長度，或每種 fault 不同長度**：前者會透過替補洩漏；後者直接洩漏 fault 類型（009 修訂 2）。
- **固定收集順序**：收集期間的漂移會和 fault 混在一起。
- **把 LOFO 或 fault_type 列為 Gate 條件**：前者降低 power；後者在結構上偏向 Agent。
- **在 Pilot 上挑出「最強 baseline」**：只有 10 個 incident，雜訊太大。
- **以 fault 為 cluster 做 bootstrap**：只有 10 個 cluster，區間不穩定。
- **分層 bootstrap**：每層只有 4–6 個時，percentile 區間的變異只剩 (K−1)/K。
- **一個 run group 切多個窗**：窗與窗之間相關，有效樣本增加有限。
- **凍結前先收 held-out 再封存**：違反 013/014/017 的字面規定，開發時也會看到 held-out snapshot。
- **先收小的 K，看結果再追加**：這是 optional stopping。
- **依 Pilot 上兩方法的不一致比例決定 K**：這會讓協定依賴方法結果。
- **每個 incident 做多次 LLM 抽樣**：成本會成倍增加。

## 對實驗的影響

- **程式**（在 Mac 上用 TDD 完成，不需要 lock，可以先做）：
  - `PLANS["heldout"]` 與 slot 清單的產生；
  - freeze 紀錄與檢查；
  - `collect` 的拒絕規則與以 slot 計算的無效上限；
  - `heldout_incidents.json`；
  - `eval` 的前置檢查與重試規則；
  - paired bootstrap、LOFO、難度層的區間。
- **lock**：表中的時數，再加上無效重收。無效比例由 Pilot 量出；RG-001 已經是無效 run。
- **磁碟（估計）**：
  - 每個 incident 的 raw 約 0.42 GB、snapshot 約 0.27 GB，N = 60 時約 41 GB。
  - sqlite/FTS cache 每個 incident 約 0.66 GB，可以由 content sha 重建；全部保留的話約 80 GB。
  - 目前可用空間約 94 GB，所以 cache 用完就清。
  - 無效 run 的 raw 依 009 §4 保留，另外計算。
- **人工**：
  - N 份 label review，一次完成。
  - gold 依 017 最多 20N 筆（K = 6 時為 1,200 筆）。
- **LLM 用量**（依 NEXT B）：
  - 三個 LLM 方法合計，每個 incident 的 input 約 0.61–0.85M tokens，最壞約 2.05M；實際 tokenizer 的數字可能再高 0–30%。
  - input 合計：

    | N | 典型 | 最壞 |
    |---|---|---|
    | 40 | 約 2,400–3,400 萬 | 約 8,200 萬 |
    | 50 | 約 3,000–4,300 萬 | 約 1 億 |
    | 60 | 約 3,700–5,100 萬 | 約 1.2 億 |

  - output 每個 incident 約 1.3–3.5 萬 tokens。
- **前置條件**：
  - Pilot 收完並 review；
  - LLM 方法經使用者成本批准後，在 Pilot 上跑過；
  - freeze 完成。

## 需要使用者決定的事項

1. **K**：建議 6（N = 60），也可選 4 或 5。K 會影響 lock 時間、磁碟、人工與費用。
2. **LLM 設定與費用**：模型、版本、temperature、是否用 prompt caching、單價，以及 held-out 預算的批准（NEXT A1、MACHINE_POLICY「外部費用」）。都要在凍結前定案。
3. **gold 標註量**：有兩個選項，建議抽樣。
   - 依 017 全部標（最多 20N 筆）；
   - 或在凍結前修訂 017（用掉 017 唯一一次修訂），以固定種子每個 fault 抽 2 個 incident，共 20 個、最多 400 筆。
4. **Gate 定義**：確認 §7 三個 Gate 條件的操作定義；以及是否付費重跑 Agent 來檢查失敗的重現性（預設不重跑）。
5. **Pilot 驗證失敗的 fault**：預設從 held-out 移除；也可以改為在 held-out 收集開始前，補收該 fault 的 Pilot。
6. **需要新 policy 或改 env lock 時**：預設排除受影響的 incident。
7. **方法 bug 修正後的重跑費用**：重跑結果只作探索性結果。

以下由 Project 自行固定：§1 的規則、§3、§4、§5、§6 的規則、§7 的統計方法。

## 使用者決定（2026-10-09，在任何 Pilot 正式資料與任何方法結果之前）

1. **K = 5**（N = 50，約 38 小時 lock，另加無效重收）：每個 fault 5 個有效 incident，各自不同的 seed 與 run group；run group 不得跨 split（§4）。
2. **LLM 設定與費用**：付費 LLM API 方法**先延後**；在使用者批准之前，held-out 不會凍結 LLM 方法的設定，也不產生任何付費用量。
   scripted fake model 只用來驗證 harness，不產生任何方法結果。
3. **gold 標註量**：使用者未另外指定 → 依保守做法**不修訂 017**（全部依 017 現行規定）；若要改為抽樣，須在 freeze 之前由使用者決定並寫 decision。
4. **Gate 定義**：§7 三個條件依本文的操作定義；不付費重跑 Agent（預設）。
5. **Pilot 驗證失敗的 fault**：從 held-out 移除並列出（預設）。
6. **需要新 policy 或改 env lock**：排除受影響的 incident（預設）。
7. **方法 bug 修正後的重跑**：只作探索性結果；重跑的付費用量另行批准（預設）。
- 另外：真實 incident snapshot 的 sample 不進 git；需要範例時用 synthetic / tiny generated fixture。
- 標「Pilot 後定稿」的項目（§1 的 fault 清單與 `PLANS["heldout"]`、§6 的 freeze 紀錄內容）仍在 Pilot 收集與 review 完成後、第一個 held-out run group 之前定稿一次。

### 追加（2026-10-10，Pilot 的 label review 與 evidence gold 完成之後；任何 held-out 資料與 freeze 之前）

使用者在對話中處理了四項：1、2、4 是決定，3 使用者選「沒有偏好」。只記錄這四項，不延伸到其他規則、門檻、指標、切分或預算。

1. **統計 baseline 的「Pilot 上修訂一次」（decision 014）放棄**：stat-anomaly 維持 v2，v2 就是 freeze 時凍結的版本；freeze 紀錄的 Pilot 修訂宣告寫
   `"014": {"status": "waived"}`（§6「用掉或明確放棄」）。Pilot 的證據：8 個失敗 = rule_limit 4、mechanism 4，沒有發現設計缺陷；
   n = 10、每個 fault 只有 1 個 incident（014「補註（2026-10-10）」）。
2. **待人處理的 slot（§4；026「待使用者決定」1）選 b，與 Pilot 相同**：人看過該 slot 的 run record 之後記錄一筆確認
   （`collect ack-failures --set heldout --slot <slot> --reason … --decided-by …`，ground-truth 側只附加的 `failure_acks.jsonl`，與 Pilot 的
   016「實作說明（2026-10-09）」同一個機制與檔案，以 slot 為單位），該 slot 再收，無效次數重新計數；再 3 個無效 run group 又待人處理。
   - 沒有 freeze 紀錄或 freeze 檢查不通過時拒絕、什麼都不寫（與所有 held-out 步驟一樣）；未知的 slot、沒有可確認的失敗、`heldout_incidents.json`
     已存在時都拒絕（清單永不改變，§5.5、§6）。
   - 被確認的 run group 留在所有紀錄裡，也留在 `heldout_incidents.json` 的 run group 清單裡（不刪任何東西）。
   - 「同時有 3 個 slot 待人處理」數的是確認之後仍待人處理的 slot。確認不改變未觸發（§5.3）與關閉的處理，也不改變 Pilot 的行為。
   - 實作與解讀見 026 解讀 11、12。
3. **freeze 之後的 bug 修正路徑（§6；026「待使用者決定」2）**：使用者選**「沒有偏好」** → 不實作任何機制，維持現況：freeze 之後發現 bug 時，
   held-out 評測停止，由使用者當時決定。freeze 之前仍可以改變這個決定（freeze 釘住所有程式，之後就無法加入）。
4. **held-out 撤回（026「待使用者決定」3）**：**不允許**，維持預設：`withdraw` 拒絕 held-out run group，手寫的撤回紀錄讓所有 held-out 步驟停止（026 解讀 30）。

### 追加（2026-10-10，第三次；LLM 設定批准時，任何 held-out 資料、freeze 與 Pilot 上的 LLM 執行之前）

使用者「照建議」（decision 029「使用者決定（2026-10-10）：照建議」）批准了上面 2026-10-09 決定 2 延後的 LLM 設定（本機模型 qwen3.5 9B、Ollama 版本釘選、
`num_ctx` 262,144、think 關；沒有外部費用），同時把 §6 的兩項前提寫進 freeze 檢查，只會拒絕更多：要凍結的 env lock 必須有通過的 soak
（decision 028「必須在 held-out freeze 之前」）；每個 LLM 方法的 Pilot 結果必須正好用要凍結的模型、runtime 與預算產生（§6「模型、版本、temperature」
與 023 第 6 行「LLM 方法試跑」的機械檢查）。實作與解讀見 decision 026 修訂 3（解讀 31、32）；freeze 紀錄的內容與 §6 的其他規則不變。

## 實作說明（2026-10-09）

本節只記錄「對實驗的影響 / 程式」已實作的內容，不改上面任何規則；每一項解讀的理由與放棄的替代方案在 decision 026。
「Pilot 後定稿」的內容（實際的 fault 清單、`PLANS["heldout"]`、slot 清單、freeze 紀錄）**都還沒有產生**，只寫好產生它們的指令；
在 freeze 紀錄存在之前，所有 held-out 收集與方法執行一律拒絕。

### 已實作

- `collect/heldout.py`：plan 的建立與檢查（`build_heldout_plan`、`pilot_evidence`、`pilot_problems`）、slot 清單（`heldout_slots`）、
  以 slot 計算的進度（`slot_status`、`next_slot`）、`fresh_seed`、清單（`heldout_incidents`、`load_heldout_incidents`）。不執行 git。
- `collect/freeze.py`：freeze 紀錄（`freeze_record`）、預設拒絕的檢查（`observe`、`freeze_problems`、`check_freeze`、`commit_problems`）、
  兩個 writer（`write_heldout_plan`、`write_freeze`）與共用的前置檢查（`post_pilot_problems`）。只用唯讀的 git 指令。
- `collect/rungroup.py`：`Plan.slot`、`Plan.freeze_sha256`；held-out ⇔ 兩者都有，Pilot 兩者都沒有（Pilot 的 run.json 形狀不變）。
- `collect/__main__.py`：`run|next|status --set heldout`、`heldout-plan`、`heldout-freeze`、`heldout-list`；incident 指令的 freeze 檢查；freeze 後 Pilot 關閉。
- `agent/harness.py`：`CallError`（adapter 依停止原因設定 reason）；`investigate`、dump-all、retrieval 在重新拋出前附上失敗前的用量。
- `eval/runner.py`：`heldout_guard`、嘗試紀錄、執行鎖、只跑一次與重試、放棄作答的評分、報告中的排除 / 關閉 slot / 移除的 fault / 失敗嘗試的用量、
  gold-add 與 compare 的檢查。paired bootstrap、LOFO、難度層區間在這之前已完成（§7）。

### 指令（依序）

1. `collect heldout-plan --amendments <file>`：寫一次 `docs/heldout/plan.json`；人檢查後 commit。
2. `collect heldout-freeze --pilot-revisions <file>`：在乾淨、plan 已 commit 的 checkout 上寫一次 `slots.json` 與 `freeze.json`；**只把這兩個檔案 commit 成一個 commit**。
3. 每個 slot：`collect next --set heldout` → `./tools/with-mac-lock uv run python -m collect run --set heldout --flag F --variant V`（不接受 `--seed`）
   → `collect process --incident <INC> --labeler …`。
   待人處理的 slot（2026-10-10 使用者決定）：人看過 run record → `collect ack-failures --set heldout --slot <slot> --reason … --decided-by …`
   → 該 slot 重新計數、回到 `collect next`；只在 `heldout-list` 之前。
4. 全部 slot 收完：`eval leakage --set heldout` → 使用者 review（`collect review-sheet` / `collect review`，`saw_method_outputs = false`）→ 未觸發的 slot 重收一次。
5. `collect heldout-list`：寫一次 `heldout_incidents.json`（只印數量）。
6. `eval run|score --method <m> --set heldout`、`eval compare --set heldout`。進度：`collect status --set heldout`。

### 檔案格式（摘要）

- **修正輸入**（不進 git）：`{"amend": [{"flag", "variant", "field": "affected_services" | "user_symptom" | "notes", "value", "reason"}],
  "remove": [{"flag", "variant", "basis": "not_exercised" | "invalid_rate" | "lexicon_hits" | "pipeline" | "label", "reason", "decision"?}]}`。
- **`docs/heldout/plan.json`**：`entries`（PILOT 的形狀與順序）、`amended`（a priori、held-out 值、理由、review 數）、`not_absorbed`（只有計數與原因）、
  `removed`（依據、理由、decision、證據計數）、`methods_with_pilot_results`。
- **Pilot 修訂宣告**（嵌入 freeze）：`{"011" … "022": {"status": "used", "decision": <file>} | {"status": "waived"}}`。
- **`docs/heldout/slots.json`**：`master_seed`、`k`、`plan_sha256`、`faults`、`slots`（H01…：block、flag、variant）。
- **`docs/heldout/freeze.json`**：`frozen_at`、`frozen_from_commit`、`frozen_tree`、`decisions`（blob）、`env_lock_sha256`、`policy`、`llm`、
  `pilot_revisions`、`plan`、`k`、`master_seed`、`slots`。
- **`heldout_incidents.json`**（ground-truth 側）：`incidents`（slot、id、8 個檔案的 sha）、`excluded`、`closed_slots`、`removed_faults`、
  `run_groups`、`by_fault`。
- **`attempts.jsonl`**：每次嘗試一行 start、一行 end（outcome：ok | api_error | transport_error | invalid_prediction | error，含用量）。
  held-out 的 `run_config.json` 另記 `freeze_sha256` 與 `heldout_incidents_sha256`。

### 解讀（理由見 026 §2 的同一編號）

1. `PLANS["heldout"]` = 進 git 的 `docs/heldout/plan.json`，只從明確的專案目錄讀。
2. plan 與 freeze 都要等 Pilot 收集、review、audit 與 LLM 方法試跑完成 → 目前被 NEXT A1 擋住。
3. 只吸收所有 exercised 且沒看過方法輸出的 review 一致發現、且與 a priori 不同的值；每項要理由；修正後仍符合 PILOT entry 規則。
4. 進 git 的文字不得有 `INC-` / `RG-` id。
5. 移除只依 Pilot 驗證失敗，每種依據對照 Pilot 資料；pipeline / label 需要 HEAD 上的 decision 檔；永不依分數。
6. 進入條件：至少一個 reviewed 且 `fault_exercised = true` 的 Pilot incident；review 完成 = 每個 valid Pilot incident 都有兩個 review 檔。
7. freeze 預設拒絕：只允許 `M NEXT.md`、新增 slots / freeze、新增 decision 檔；freeze 後既有 decision 不再修改。
8. env lock、policy、llm 的 sha 寫入紀錄並由 diff 釘住；資料端仍逐筆比對。
9. freeze 要求 llm 已 approved 且 model、model_version、temperature 非 null。
10. 「Pilot 上修訂一次」：011、013–015、017、019–022 各宣告 used / waived；013 必須 used；011 隨 policy 版本；
    014 必須 waived（使用者 2026-10-10 決定；026 修訂 2 審查起由 freeze 檢查強制）。
11. slot 的無效上限累計沒有被確認的非 valid run group（invalid 與所有 aborted_*）。2026-10-10 使用者決定（026「待使用者決定」1 選 b，與 Pilot 相同）：
    待人處理的 slot 由人看過 run record 後以 `collect ack-failures --set heldout --slot <slot>` 確認（`failure_acks.jsonl`，只附加），重新計數、再收；
    再 3 個無效又待人處理。只確認待人處理的 slot；freeze 檢查不通過、未知的 slot、`heldout_incidents.json` 已存在時拒絕；被確認的 run group 留在所有紀錄與清單的
    run group 清單裡；清單另記錄確認，之後多出來的確認會被發現（見 026 解讀 11）。手寫的確認必須等於指令當時會寫的內容
    （該 slot 全部未確認的失敗、至少 3 個），提前或部分的確認讓所有 held-out 步驟停止（026 修訂 2 審查）。
    （同日稍早的更正說 held-out 沒有這種確認、永不重新計數；使用者決定後已不成立。）
12. 狀態優先：filled > needs_person > closed > open；損壞或不符的紀錄（包括確認紀錄）exit 2，需要人 exit 3；「3 個 slot 待人處理就停止」數確認之後仍待人處理的 slot。
13. 未觸發重收一次，再未觸發就關閉；詞彙命中排除、不重收。
14. `run --set heldout` 自己算下一個 slot；slot 與 freeze sha 只寫進 run.json。
15. held-out 拒絕 `--seed`，seed 由 SystemRandom 抽且不與任何 run group 重複。
16. slot 順序只由 `Random(20261009).random()` 決定，可重新產生驗證。
17. 只對 api_error / transport_error 重試，每個（方法, incident）最多 2 次，全部記錄用量。
18. 每個（方法, incident）只跑一次；續跑需要相同設定；O_EXCL 執行鎖；prediction 原子寫入、不覆寫；transcript 先寫、prediction 最後寫。
19. 重試後仍無 prediction → 放棄作答，留在分母、`no_answer`、列出；使用者可在 freeze 前推翻。該方法的 `run.lock` 存在時拒絕評分。
20. 每個 held-out eval 路徑先過 `heldout_guard`；清單存在後 leakage 拒絕。
21. 作用在 held-out incident 的 collect 指令要求 freeze 檢查通過。
22. freeze 之後 `collect run --set pilot` 拒絕。
23. held-out 的輸出不顯示 incident id 與 valid run group id。
24. `heldout_incidents.json` 寫一次、釘住 8 個檔案與所有 held-out run group，並檢查每個 run group 來自凍結的程式、在 freeze 之後（`up_at` 在 run 任何可能失敗的步驟之前記錄）。
25. 使用者決定 6：任何 policy / env lock 不符都 fail closed；將來的修訂指令必須排除、不混用。
26. 依收集順序配發的 id 加上進 git 的 slot 清單，仍可讓人對應 id 與 fault；方法看不到，接受。
27. held-out 需要的程式（API adapter、Gate 2 / 3、等權表、013 正式版）都要在 freeze 前 commit。
28. 這一批不做 held-out loop。
29. decision 025 修訂 2、3 的電力條件對 held-out 一樣成立（同一個 preflight 與時間窗判定）；`power_not_formal` 算 slot 的無效嘗試；清單時再查每個計入的 valid run group 的電力證據。
30. held-out run group 一律不能撤回（026 修訂 1：撤回會讓 slot 不受限地重收，放寬本文 §2、§4、§5.3）；手寫的撤回紀錄讓所有 held-out 步驟停止，由人以新的 decision 決定；
    decision 025 修訂 3 的撤回只用於 Pilot，撤回的 Pilot incident 不是 plan 的證據。

023 與使用者決定沒有涵蓋的三件事（待人處理的 slot 如何解除、freeze 之後的修正路徑、held-out 撤回）原本列在 026「待使用者決定」；
使用者 2026-10-10 已處理（見上面「使用者決定」的「追加（2026-10-10）」）：1 選 b、已實作（解讀 11）；2 沒有偏好，不實作、維持現況，freeze 之前仍可決定；3 不允許（解讀 30）。

## 實作說明：Gate 計算（2026-10-09）

本節只記錄 §7 Gate 判準與描述性報告的程式，**不改上面任何規則、門檻、指標、切分或預算**；有歧義的地方取保守的一側（讓 Gate 更難通過、缺東西就拒絕），每一項列在下面。
這補上 026 解讀 27 列為 freeze 前必須 commit 的「Gate 條件 2 / 3 的程式」與「各 fault 等權平均與缺格表」。付費 LLM 方法延後（NEXT A1），所以目前還沒有任何 Agent 結果，也沒有算過任何 Gate。

### 指令

1. `python -m eval score --method agent --set <set>`、`python -m eval score --method stat-anomaly --set <set>`（每個統計 baseline 都要）。
2. `python -m eval compare --method agent --against stat-anomaly --set <set>`（條件 1 的 paired 差異，已存在；現在另記錄它讀到的兩份 scores.json 的 sha256）。
3. `python -m eval gate --method agent --against stat-anomaly --set <set>`：只讀已寫好的 scores.json 與 compare 輸出，**不執行任何方法、不重抽 bootstrap**；
   寫 `results/<set>/agent/gate.json` 與 `gate.md`，並印出摘要。held-out 上是本文 §7 的 Gate 判定；Pilot 上只是診斷，**不是 Gate 判定**。

程式：`eval/gate.py`（純函式：三個條件、coverage 比例、各 fault 表）、`eval/runner.py`（`gate_methods`、`fault_table`、`STATISTICAL_BASELINES`、`GATE_METHOD`）、`eval/__main__.py`（`gate`）。

### 輸出

- `gate.json`：`kind`（held-out 為 `gate_decision`，Pilot 為 `diagnostic`）、`statement`、`all_met`、`decision`（held-out 為 `pass` / `not_passed`，Pilot 為 null）、
  `conditions`（`1`：每個統計 baseline 的 n、平均差異、區間、下界；`2`：每個 fault 的 K、⌈K/2⌉、計分數、origin 答錯數、各類別次數、過半的類別、是否評估；`3`：失敗數、not_seen / seen_misread 次數、比例）、
  `descriptive`（coverage 比例、其他主要指標的 paired 差異、origin_top1 的 LOFO、對每個統計 baseline 的各 fault origin_top1 答對數 k/K 與差異方向、Agent 與每個統計 baseline 的各 fault 表）、`inputs`（讀到的 scores.json 與 compare 的 sha256）；
  held-out 另有 freeze 與清單的 sha、移除的 fault、關閉的 slot（只列 slot、fault 與原因）。held-out 的 gate 輸出（`gate.json`、`gate.md`、印出的摘要）不列 incident id 或 run group id；
  gate 讀的 compare 輸出（`compare-*.json` / `.md`）也一樣（2026-10-10 合併審查補上：原本原樣複製 scores.json 的 `excluded` 與 `closed_slots`，
  帶著 incident id 與 valid run group id）：關閉的 slot 只列 slot、fault 與原因，排除的 incident 只列 slot 與原因。
  incident id 只在清單與各方法自己的結果（prediction、`attempts.jsonl`、scores.json、table.md）裡。唯一的例外：compare 的 paired `only_in_one`
  列出只有一個方法計分的 incident；held-out 上兩份 scores.json 屬於同一份清單、每個列表內 incident 都計分（放棄作答也算），所以正常情況下
  它是空的（例如 scores.json 被手改時才不是）；不是空的時 gate 拒絕（解讀 8）。
- 每個方法的 `eval score` 也在 scores.json 的 `by_fault` 與 table.md 的「Per fault」段列出各 fault 平均、等權平均與缺格清單。
  表中「scored / K」是該 fault 計分的 incident 數 / K，不是答對數（答對數 k/K 見解讀 14）。

### 追加（2026-10-10，第二次；同樣在任何 held-out 資料與 freeze 之前、在任何 LLM 方法結果之前）

使用者確認兩項，都是維持現行規則，不改任何門檻、指標、切分或預算：

5. **gold 標註量（上面 2026-10-09 決定 3；NEXT A3）**：照原規定，**不修訂 017**，不改為抽樣。
6. **Gate 的 Pilot 診斷讀法（「實作說明：Gate 計算」解讀 4；NEXT A5）**：確認。Pilot 上 K < 2 的 fault 不評估條件 2（not evaluated、不算成立）；
   held-out 照 §7 原文（K 是設計的 slot 數），程式不變。

### 解讀

1. **只讀、不重算條件 1**：條件 1 讀 `compare-agent-vs-<baseline>.json`（`eval.compare.paired`），不重新實作。只接受：由目前的 scores.json 算出（sha 相符）、set 與方法相符、
   origin_top1 的 bootstrap 是 013 §3 的 10,000 次、seed 0。缺少、過期或設定不同 → exit 2，要求重跑 `eval compare`。下界 > 0 是嚴格的。
2. **統計 baseline**：`eval/runner.py` 的 `STATISTICAL_BASELINES`（目前只有 stat-anomaly；測試保證每個登錄的方法不是 LLM 方法就是統計 baseline）。
   Agent 必須對**每一個**登錄的統計 baseline 都成立（§7「多個統計 baseline」）；任何一個沒有分數或 compare 就拒絕，不略過、不當成通過。`--against` 必須是其中之一。
3. **Gate 只針對 Agent**：`--method` 只接受 agent（SPEC Gate）；其他方法只用 score / compare 描述。
4. **條件 2 的 K**：held-out 用驗證過的 `heldout_incidents.json` 中該 fault 的 slot 數（設計的 K = 5）；缺格（關閉的 slot、詞彙命中排除）**不降低**門檻 ⌈K/2⌉，
   缺格不會讓條件 2 比較容易成立。Pilot 用該 fault 實際計分的 incident 數（由資料推得）。只看有計分 incident 的 fault。
   **Pilot 上 K < 2 的 fault 不評估條件 2**（2026-10-10 review 修正）：K = 1 時 ⌈1/2⌉ = 1，一次答錯本身就「過半」，單一 incident 無法顯示可重現性；
   這種 fault 標為 not evaluated、不算成立，gate.md 與印出的摘要註明「one incident cannot show reproducibility」。這只讓 Pilot 診斷更難成立，
   held-out 照 §7 原文計算（K 是設計的 slot 數），程式行為不變。使用者 2026-10-10 確認這個讀法（「追加（2026-10-10，第二次）」第 6 項）。
5. **條件 2 的「答錯」與「同一個類別」**：答錯 = origin_top1 = 0，包括放棄作答（013 §2、026 解讀 19）；只有 fault_type 錯（mechanism）不算。
   依 §7 的文字，「同一個類別」是 022 六類中的任一類（包括 no_answer、coverage），輸出寫出是哪一類。「過半」是嚴格大於一半（2/4 不算）。
   「這些失敗」只指 origin 答錯的 incident：過半的分母是 origin 答錯數，不含只有 fault_type 錯的失敗。
6. **條件 3**：分母是 022 §1 的所有失敗（origin 或 fault_type 錯）；> 0.5 是嚴格的；沒有任何失敗時比例無定義，條件不成立。
7. **判定只在 held-out**：三個條件都成立才是 `pass`。held-out 的輸出寫明這是 §7 的 Gate 判定，只用第一次執行的結果（§5、§6：每個（方法, incident）只跑一次，預測永不覆寫）。
   Pilot 照樣計算三個條件，但 `decision` 是 null，輸出寫明「DIAGNOSTIC ONLY, NOT a Gate decision」（SPEC §5：Pilot 永不進 test）。
8. **held-out 的前置檢查**：第一個陳述是 `heldout_guard`（026 解讀 20）；每份 scores.json 必須屬於目前的 freeze 與清單；兩個方法計分的 incident 必須相同
   （compare 的 `only_in_one` 不是空的就拒絕；放棄作答本來就留在分母）。任何 set 上，scores.json 記錄的方法與 set 都必須與它的路徑相符。
9. **coverage 比例只描述**（SPEC「收尾或改題」）：coverage 次數 / 失敗數，不設門檻、不下判斷；並列出沒有 review 就分類的失敗數（022 §2：這些無法判為 coverage）與失敗數 / 計分數。
   「Agent 幾乎全對」沒有數值門檻，程式也不判斷。
10. **各 fault 等權平均與缺格清單**（只描述，沒有區間）：等權平均 = 有計分 incident 的 fault 各自平均的平均；另列所有計分 incident 的平均（§7 的估計量）作對照。
    缺格：held-out 是沒有計分 incident 的 slot（附原因：關閉或詞彙命中排除）與 Pilot 後移除的 fault；Pilot 是 Pilot 清單中沒有計分 incident 的 fault。
11. fault_type 與另外兩個主要指標的 paired 差異、origin_top1 的 LOFO 下界從 compare 讀出，只列在描述段（§7：fault_type 與 LOFO 不是 Gate 條件）。
12. **沒有分數就不寫**：Agent 沒有分數（付費 LLM 方法延後，NEXT A1）時，exit 2、印出「the Gate cannot be evaluated yet」、不寫任何檔案；
    統計 baseline 沒有分數、compare 缺少或過期時也一樣。所有檢查都在寫入之前。`gate.md` 與 `gate.json` 的內容都先產生完，再各自以 atomic replace 寫入，
    `gate.md` 先、`gate.json` 最後：任何一個新的 `gate.json` 旁邊都是它自己的 `gate.md`。
13. gate 是決定性的，可以重跑。§6 的評分 bug 修正後重新評分，scores.json 會改變，要先重跑 compare 才能重跑 gate；修正前後兩組數字的並列報告不是這個指令做的事
    （freeze 之後的修正路徑：026「待使用者決定」2，使用者 2026-10-10 沒有偏好，維持現況；freeze 之前仍可決定）。只重新評分統計 baseline 也一樣：compare 記錄的兩份 sha 都要與目前的 scores.json 相符。
14. **§7 穩健性報告的「各 fault 的 k/K 與差異方向」**（2026-10-10 review 補上；只描述，不設門檻）：對每個統計 baseline、每個 fault，列出 Agent 與該 baseline 的
    origin_top1 答對數 k / K（k 數各自計分的 incident；K 取各自的各 fault 表：held-out 是設計的 slot 數，Pilot 是計分數），以及 Agent − baseline 在該 fault
    兩者都計分的 incident 上的差異方向（+ / 0 / −；沒有共同 incident 時不給方向）。LOFO 的下界照舊從 compare 讀出（解讀 11）。
