# 031 — Held-out 結果發布與 Core 收尾：Gate NOT PASSED，照現在的結果收尾，不改題、不進 Advanced

- 狀態：Accepted（2026-10-31，使用者決定）。在所有 held-out 步驟完成、Gate 判定之後寫定。
- 影響範圍：Core 到此結束；不進 Advanced、不改題、不實作 Optional。同一個 commit 新增 [`100-heldout-final-results.md`](100-heldout-final-results.md)（結果）並修改 `NEXT.md`，
  只有這三項（decision 030 §5）。
- **不改任何東西**：指標、門檻、Gate 條件、切分、預算、prompt、incident 清單、程式、測試、資料、README、SPEC 與既有的 decision 都不變。

## 背景

### freeze 紀錄

- plan commit `4b42a4a`（`frozen_from_commit` `4b42a4a287a4cfea10bf4e0a32c9cbe000d34f59`）；freeze commit `045bc27`，frozen_at 2026-10-16T13:47:17Z；
  `docs/heldout/freeze.json` sha256:7d68302545d958c4ba4d787e2d4f6fa558c954ccb27b7369f217b4b14d20cb39。
- incident 清單 `heldout_incidents.json` sha256:e606baae8b8944f1267e6296e7d9784620b952149b12f37e46dc99821a6140b5：列入 50 個，排除 1 個
  （slot H21，fault 沒有觸發；依 023 §5.3 重收一次）。
- 發布前的唯讀確認（2026-10-31，030 §5）：`git diff --name-status 4b42a4a..HEAD` 只有 `M NEXT.md`、`A docs/heldout/freeze.json`、`A docs/heldout/slots.json`；
  `collect status --set heldout` 的 `freeze_problems` 是 `[]`；`eval version-check --set pilot` exit 0。

### held-out 的步驟（全部完成，依序）

| 日期 | 步驟 |
|---|---|
| 2026-10-16 | freeze |
| 2026-10-23 | 50 個 slot 收集完成（3 個 invalid 的 run group 依規則自動重收）；leakage audit（lexicon hits 0） |
| 2026-10-24 | label review（使用者 human:jingwen，50 個）；H21 重收與 review；`collect heldout-list` |
| 2026-10-25 | 四個方法的 `eval run`（第一次執行；dump-all 有 1 次 `transport_error`，依規則重試成功）；`eval score`、`compare`、`gate` |
| 2026-10-26 – 10-30 | held-out evidence gold 盲標（使用者 human:jingwen，604 項全部判定，未判定 0） |
| 2026-10-30 | gold 之後用凍結的工具重跑 `eval score`（四個方法）、`compare`、`gate`：scores.json 只有 gold 欄位改變，gate.json 只有 inputs 的 sha 改變；主要指標與 Gate 判定都不變（gold 之前的輸出備份在 `data/external/logs/heldout-methods/pre-gold/`） |

### Gate 判定：NOT PASSED

照 `agent/gate.md` 轉寫（數字見 100 §5）：

- 條件 1（唯一的主要檢定）**不成立**：agent − stat-anomaly 的 origin_top1 paired 差異 −0.080，95% 區間 [−0.280, 0.120]，n 50（下界 ≤ 0）。
- 條件 2 成立：intlShippingSlowdown 10sec、paymentUnreachable on、productCatalogLockContention on 答錯的都是 seen_misread。
- 條件 3 成立：not_seen + seen_misread 占失敗的 17 / 32 = 0.53。
- 描述（不是 Gate 條件）：coverage 0 / 32 = 0.00。

### SPEC「收尾或改題」

SPEC 只寫了兩種情況，這次的結果都不完全符合：

- 「失敗主要來自 telemetry coverage 不足：完成 failure taxonomy 後收尾」——coverage 是 0 / 32。
- 「Agent 幾乎全對：先加難度，不直接進 Advanced」——agent 的 origin_top1 是 0.580，低於 stat-anomaly 的 0.660。

所以下一步由使用者決定（030 §4 第 13 項；使用者 2026-10-16：不自行進入 Advanced）。

### 030 §4 第 10 項（評測之後發現的 bug）

沒有：評分或稽核沒有發現 bug，freeze 之後沒有改任何程式，沒有修正前後的數字要報告。

## 決策

使用者 2026-10-31 的決定（原話）：

> 我的決定是：照現在的 `NOT PASSED` 結果正式收尾，不改題、不進入 Advanced。

1. **Core 正式收尾**：held-out 的 Gate 判定 NOT PASSED 就是最終結論，數字只在 100（只寫一次，030 §3）。
2. **不改題**：研究問題、指標、門檻、Gate、切分、預算都不因 held-out 結果修改（023 §6）。
3. **不進 Advanced**（SPEC「Gate」：判定不是 `pass`），也不實作 Optional。
4. **發布**：照 030 §5，同一個 commit 只有 `A docs/decisions/100-heldout-final-results.md`、`A docs/decisions/031-heldout-wrap-up.md`（本文件）、`M NEXT.md`；
   commit 前後各跑一次三項唯讀確認。

## 為什麼

使用者給的理由（原話，供紀錄）：

> 1. 直接回答 SPEC.md 的核心研究問題：本專案的核心問題是「LLM Agent 能不能可靠地做 production 根因分析，而且勝過合理的 baseline？」。在事前凍結的 held-out 協定（50 個 incident、本機模型 `qwen3.5:9b-q4_K_M`）下，gate.md 條件 1 未通過（`agent − stat-anomaly` 的 `origin_top1` 為 `-0.080`，95% CI `[-0.280, 0.120]`），這本身就是對研究問題完整且誠實的實證結論，不應在看到 held-out 結果後事後改題或放寬標準。
> 2. Core 產出與失敗分類（Failure Taxonomy）已完整具備：
>    * 雖然這筆結果不屬於「telemetry coverage 不足」（`coverage = 0/32`）或「Agent 幾乎全對」（`origin_top1 = 0.58`），但四個方法的分層指標、604 項全數判定的 held-out gold precision（無任何未決 `null` 項，四個方法的 gold precision 皆可完整報告）與 022 失敗分類都已完整產出。
>    * 結果清楚呈現統計規則與 LLM 方法在不同故障機制上的互補與限制（例如 `stat-anomaly` 在資源飽和與延遲類故障穩定、gold precision 達 `0.850`，但在 `cartFailure`、`productCatalogFailure`、`productCatalogLockContention` 因規則限制得 0 分；`agent` 在錯誤訊息明確的故障拿滿分、gold precision 達 `0.727`，但在 `paymentUnreachable`、`intlShippingSlowdown`、`productCatalogLockContention` 出現穩定的 `seen_misread`，在 `emailMemoryLeak`、`adHighCpu` 則受限於 `not_seen` / `no_answer` / `mechanism`）。這些發現直接作為 Core 的最終結論收尾即可。

### 轉寫核對（主 session 對照凍結輸出；不改變使用者的決定與理由）

- 理由中的數字與 100 一致：條件 1 −0.080 [−0.280, 0.120]；coverage 0 / 32；agent origin_top1 0.580；gold precision stat-anomaly 0.850、agent 0.727；
  604 項全部判定、未判定 0。
- stat-anomaly 在 cartFailure、productCatalogFailure、productCatalogLockContention 的 origin_top1 都是 0.000（100 §6），這 15 個 incident 的 022 類別都是 `rule_limit`
  （stat-anomaly scores.json 各 incident 的 `failure`）。與理由一致。
- agent 在 emailMemoryLeak、adHighCpu 的失敗類別：100 §5「Condition 2 by fault」（origin 答錯的 incident）是 emailMemoryLeak no_answer 2、not_seen 1、seen_misread 2，
  adHighCpu no_answer 1、not_seen 2、seen_misread 1。依 agent scores.json 各 incident 的 `failure`，這兩個 fault 沒有 `mechanism`；agent 的 11 個 `mechanism`
  出現在 adManualGc（4）、productCatalogLockContention（2）、recommendationCacheFailure（5）。所以這兩個 fault 的類別是 not_seen / no_answer / seen_misread，
  不是理由所寫的 not_seen / no_answer / mechanism。這不影響決定（Gate 判定與收尾都不依這一句），理由照原文保留。

### 其他

- 收尾不需要再收集、執行模型或重算：所有 held-out 步驟都已完成，100 只轉寫凍結工具寫出的檔案。
- 023 §7「其他」寫明「Agent 幾乎全對時，要另開新的集合」；這次不是這種情況，所以不開新的集合。

## 放棄的替代方案

- **改題**：會在看到 held-out 結果之後變動研究問題（CLAUDE.md「不得自行擴張研究問題」、「不得看到結果後偷偷修改指標、測試題、資料切分或 benchmark protocol」）。使用者決定不改。
- **進 Advanced**：Gate 沒有通過（SPEC「Gate」）。
- **加難度或另開新的 held-out 集合**：SPEC 與 023 §7 只在「Agent 幾乎全對」時才這麼做；這次 agent 沒有勝過 stat-anomaly。
- **對同一個 incident 重跑 Agent 檢查抽樣重現性**（023 §7 條件 2 的備註）：不是 Gate 的一部分；重跑結果只能另列、不取代第一次的分數。使用者沒有要求，不做。

## 對實驗的影響

- Core 結束；held-out 的最終數字只在 100，Pilot 的數字只在封存的 README（診斷用，永不合併）。
- **結論只限於本機模型 qwen3.5 9B（q4_K_M）**（decision 029）；付費 API 模型延後，沒有執行。
- 沒有改任何程式、測試、資料、門檻、Gate、README 或 SPEC；沒有執行任何收集、模型、Docker、ssh 或網路（push 到私有 origin 除外）。
- 100 只寫一次：之後若發現錯誤，寫新的 decision（032–099）說明更正什麼、更正前後的數字，100 本身不改（030 §3）。
- 環境沒有清理：`data/external/`（snapshot、結果、gold、log）與本機的 Docker image 都保留；要不要清理由使用者決定。
