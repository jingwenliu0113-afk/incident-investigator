# 038 — 公開之後的整理：MIT 授權（`LICENSE`）、About 描述與 topics、之後的 commit 用 noreply email

- 狀態：Accepted（2026-11-01，使用者：「用mit吧」、「設定 About 描述與 topics」、「之後的 commit 改用 noreply email」、「從乾淨 clone 重跑測試與 demo」）。
- 影響範圍：main 新增根目錄的 `LICENSE` 與本文件，修改 `.github/README.md`（加授權一節）與 `NEXT.md`；GitHub repo 的 About 描述與 topics；
  本 repo 的本機 git 設定 `user.email`。程式、測試、SPEC、根目錄 README、`pyproject.toml`、既有 decision、資料與結果都不變。

## 背景

- 使用者 2026-11-01 要求「把 repo 改成 Public」（作品集；037）。主 session 公開前掃過兩個 branch 的完整歷史，沒有 API key、token 或私鑰。
- 使用者要求對照 robot 專案的公開規則。`../PORTFOLIO.md`「GitHub 公開策略」要求 README 最上方寫目前狀態（已在首頁補上，commit c9d114b）。
- 使用者其他公開的 repo（inspection-robot-active-perception、rust-hnsw、agent-gym、llm-serving-lab）都有 LICENSE、About 描述，
  公開後的 commit 用 GitHub 的 noreply email。本 repo 三項都沒有。
- 沒有 LICENSE 的公開 repo 只能看，別人不能合法重用程式。

## 決策

1. **授權：MIT。** 根目錄新增 `LICENSE`，內容與 llm-serving-lab 的 `LICENSE` 逐位元相同（`Copyright (c) 2026 jingwen`）。
   - 首頁 `.github/README.md` 加「License / 授權」一節。
   - `pyproject.toml` 沒有 license 欄位；它是 freeze 時封存的檔案，不改。
   - 第三方內容：程式都是本專案寫的。OpenTelemetry Demo（Apache-2.0）只以 image digest 引用（`env/otel-demo.lock.json`、`env/compose.pinned.yaml`），
     沒有複製它的程式碼；`data/samples/synthetic/` 是程式產生的合成資料。所以不另寫 third-party notices。
2. **freeze 檢查的第二個例外**：與 037 第 2 點相同的理由。從本 commit 起，`collect status --set heldout` 的 `freeze_problems` 會列出
   `.github/README.md` 與 `LICENSE` 兩項，這是預期的。之後的三項唯讀確認改成：
   - `freeze_problems` 只有這兩項；
   - `eval version-check --set pilot` exit 0；
   - `git diff --name-status 4b42a4a..HEAD` 只有 freeze 允許的路徑，加上 `A .github/README.md`、`A LICENSE`。
   held-out 結果的完整性仍由 tag `heldout-final`（e47f2c7）保留。
3. **About 描述與 topics**（GitHub 的 repo 設定，不在 git 裡）：
   - 描述：「Pre-registered evaluation: can an LLM agent do root-cause analysis on frozen OpenTelemetry Demo incidents? Gate NOT PASSED.」
   - topics：llm、llm-agents、root-cause-analysis、opentelemetry、observability、evaluation、aiops。
4. **commit email**：本 repo 的本機 git 設定 `user.email` 改成 `232231837+jingwenliu0113-afk@users.noreply.github.com`（與其他專案相同），
   從本 commit 起生效。已經公開的歷史不改寫（禁止改寫 remote history）。
5. **乾淨 clone 的確認**：從公開的 repo 匿名 clone 到暫存目錄，照首頁的指令跑 `uv sync`、demo 與測試，結果記在 NEXT.md。

## 為什麼

- 和使用者其他公開的 repo 一致；MIT 是使用者選的。
- 加在根目錄的 `LICENSE` 是 GitHub 偵測授權的位置；不改任何凍結的檔案。

## 放棄的替代方案

- **BSD-3-Clause**（其他三個 repo 用的）：使用者選 MIT（與 llm-serving-lab 相同）。
- **不加授權**：別人不能合法重用程式，與其他公開的 repo 不一致。

## 對實驗的影響

- 沒有。程式、資料、label、gold、結果與 Gate 判定都不變。
