# 037 — 作品集首頁：新增 `.github/README.md`（中英雙語），根目錄的 README 維持凍結

- 狀態：Accepted（2026-11-01，使用者：「寫 decision 037 和新首頁（建議）」、首頁語言「中英雙語（建議）」）。
- 影響範圍：main 新增 `.github/README.md` 與本文件，修改 `NEXT.md`。程式、測試、SPEC、根目錄 README、既有 decision、資料與結果都不變。

## 背景

- 使用者做這個專題的目的，是讓 GitHub 上有作品並放進履歷，讓別人看到這份作品、知道使用者會這些東西（2026-11-01）。
- 根目錄的 `README.md` 在 held-out freeze 時封存，之後不能改（030 §1、`collect/freeze.py` 的 `ALLOWED_AFTER_FREEZE`）。
  它停在 freeze 前的狀態：寫著「Core 還沒完成」、只有 Pilot 的數字，沒有連到 100、031、101。第一次看到 repo 的人會看到過時的狀態。
- GitHub 顯示 repo 首頁 README 的順序是 `.github/`、根目錄、`docs/`。所以新增 `.github/README.md` 就能換掉首頁，根目錄的 README 一個位元組都不用改。
- freeze 檢查是 deny by default：freeze 之後只允許 `M NEXT.md`、`A docs/heldout/slots.json`、`A docs/heldout/freeze.json` 和新的 decision 檔案。
  `.github/README.md` 不在允許的清單裡。
- held-out 的評測已經完成並發布（100、031；探索性結果 101）。freeze 要保證的是「held-out 的結果由凍結的程式產生」；
  那個狀態由 tag `heldout-final`（e47f2c7，發布 100 的 commit）永久保存，之後的 commit 不會改變它。
- repo 目前是 Private。公開與否是使用者的規則（「維持 Private」），主 session 不改。

## 決策

1. **新增 `.github/README.md` 作為作品集首頁**（中英雙語，英文在前）。根目錄的 `README.md` 維持凍結，不改。
2. **這是 freeze 允許清單之外唯一的例外。** 從本 commit 起，`collect status --set heldout` 的 `freeze_problems` 會列出 `.github/README.md (A)`；
   這是預期的結果，不是程式被改。之後的三項唯讀確認改成：
   - `freeze_problems` 只有 `.github/README.md` 這一項；
   - `eval version-check --set pilot` exit 0；
   - `git diff --name-status 4b42a4a..HEAD` 只有 freeze 允許的路徑加上 `A .github/README.md`。
   因為 `freeze_problems` 不再是空的，main 上 `--set heldout` 的收集與方法執行會被拒絕。held-out 已經完成，不會再跑；
   要重現凍結狀態，checkout tag `heldout-final`。
3. **首頁的內容**只轉寫 100、101 的數字（四捨五入到小數兩位），不新增指標或比較，不列 incident id：
   - 一句話的問題；Gate 判定 NOT PASSED；Argon 的探索性結果，並寫明它不是 Gate 判定；
   - 架構與方法、評測方式、事前登記的做法、試跑的指令（只讀合成範例）；
   - 「怎麼做出來的」：程式由 Claude Code 撰寫（commit 標記 `Co-Authored-By: Claude`），以及使用者負責的部分。
     這一段在公開前由使用者確認是否正確。
4. **公開與否由使用者決定**：使用者看過首頁之後，自己在 GitHub 的設定改成 Public，或明確告訴主 session 去改。
5. branch `explore/032-argon` 照常合併 main（只是新增檔案）；branch 仍永不 merge 回 main。

## 為什麼

- 作品集的讀者第一眼看的是 repo 首頁。凍結的 README 是給執行實驗用的工作文件，不是給第一次看的人讀的。
- 放在 `.github/` 不改任何凍結的檔案，也不改寫 git 歷史；freeze 的意義（結果由凍結的程式產生）由 tag `heldout-final` 保留。
- 誠實寫出 AI 協作與使用者的角色：commit 紀錄本來就看得到，事先寫清楚比被問到才解釋好。

## 放棄的替代方案

- **直接改根目錄的 README**：會改一個 freeze 時封存的檔案；新增 `.github/README.md` 效果相同，又不動凍結的檔案。
- **另開一個公開的展示 repo**：要複製程式，而且會失去 175 個 commit 與 decision log 這些展示流程的紀錄。
- **維持現狀**：首頁過時；repo 是 Private 時，別人點履歷上的連結只會看到 404。

## 對實驗的影響

- 沒有。程式、資料、label、gold、結果與 Gate 判定都不變。
