# 023 — Held-out 評測協定（Proposed）

## 狀態 / 影響範圍

- **狀態**：Proposed（2026-10-09）。本協定寫在任何 held-out 資料與任何方法結果出現之前。
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
