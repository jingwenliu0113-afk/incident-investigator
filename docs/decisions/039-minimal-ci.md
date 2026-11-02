# 039 — 最小 CI：GitHub Actions 跑測試與 ruff（`.github/workflows/ci.yml`、`ruff.toml`）

- 狀態：Proposed（2026-11-02）；合併到 main 即為 Accepted。
- 影響範圍：main 新增 `.github/workflows/ci.yml`、根目錄的 `ruff.toml` 與本文件，修改 `.github/README.md`（標題下加 CI badge；decision log 的份數 40 → 41）與 `NEXT.md`。
  程式、測試、SPEC、根目錄 README、`pyproject.toml`、`uv.lock`、既有 decision、資料與結果都不變；tag `heldout-final` 不動。

## 背景

- repo 公開之後（037、038）沒有任何 GitHub Actions workflow。測試結果只記在 NEXT.md：乾淨 clone 跑 `python -m env fetch-upstream` 之後
  1116 passed、5 deselected（`-m "not network and not docker_daemon"`）；沒有 fetch 時 23 個測試失敗，原因都是缺 gitignored 的 `env/upstream/opentelemetry-demo/`。
- `python -m env fetch-upstream`（`env/cli.py` 的 `cmd_fetch_upstream`）只用 git 淺層 clone 鎖定的 tag（`env/otel-demo.spec.json` 的 `upstream`：tag 3.1.0），
  再核對 commit；不需要 Docker。`env/upstream/` 在 `.gitignore` 裡。
- 三個 marker（`network`、`docker_cli`、`docker_daemon`）定義在 `pyproject.toml` 的 `[tool.pytest.ini_options]`，`--strict-markers`。
- 本 repo 沒有 ruff 設定，ruff 也不是專案的依賴。ruff 0.12.0 的預設規則（`ruff check --isolated .`）有 23 項：
  - 22 項 F811，全在 `tests/test_cli.py`、`tests/test_lock.py`、`tests/test_runtime.py`：這三個檔從 `tests/lockfixtures.py` import pytest fixture `tree`，
    再把它當成測試函式的參數；ruff 把參數看成重新定義了 import（pytest fixture 的慣用寫法，不是 bug）。
  - 1 項 F541：`env/soak.py:266` 的 f-string 沒有 placeholder。
- freeze 檢查是 deny by default（`collect/freeze.py` 的 `ALLOWED_AFTER_FREEZE` 與 `_change_problems`）：freeze 之後只允許 `M NEXT.md`、slot list、freeze record 與新的 decision 檔案。
  `.github/workflows/ci.yml` 與 `ruff.toml` 都不在允許的清單裡；程式、測試與 `pyproject.toml` 是 freeze 時封存的檔案（038 第 1 點）。

## 決策

1. **新增 `.github/workflows/ci.yml`**：push 到 main、pull request 與手動執行（`workflow_dispatch`）時，在 `ubuntu-24.04` 上依序執行：
   1. `uv sync --locked`；
   2. `uv run python -m env fetch-upstream`（淺層 clone 鎖定的 OpenTelemetry Demo tag 並核對 commit；不快取）；
   3. `uv run pytest -q -m "not network and not docker_daemon and not docker_cli"`；
   4. `uvx ruff@0.12.0 check .`（ruff 不是專案的依賴；版本與本機使用的相同）。前面的步驟失敗時也照樣執行（`if: ${{ !cancelled() }}`），
      所以測試紅燈時仍看得到 lint 的結果；只有整個執行被取消時才跳過。
   - action 的版本與 llm-serving-lab、agent-gym、inspection-robot-active-perception 的 CI 相同：`actions/checkout@v7`、`astral-sh/setup-uv@v10.2.0`。
     權限只有 `contents: read`。
   - CI 只做檢查：不收集 incident、不執行任何方法、不需要 Docker、GPU、模型或 `data/external/`，也不改任何結果。
2. **新增根目錄的 `ruff.toml`**：ruff 的預設規則，加兩個只限定在現有位置的例外；不重排、不修改任何程式：
   - `tests/test_cli.py`、`tests/test_lock.py`、`tests/test_runtime.py` 忽略 F811（fixture 的慣用寫法）；
   - `env/soak.py` 忽略 F541（凍結的程式，不改）。
   其他檔案出現 F811、F541，ruff 照樣會報。
3. **首頁 `.github/README.md`**：標題下加 CI badge；decision log 的份數從 40 改成 41（加上本文件）。
4. **freeze 檢查的第三個例外**：與 037 第 2 點、038 第 2 點相同的理由。從本 commit 起，`collect status --set heldout` 的 `freeze_problems` 會列出四項：
   `.github/README.md`、`LICENSE`、`.github/workflows/ci.yml`、`ruff.toml`（都是 `A`），這是預期的。之後的三項唯讀確認改成：
   - `freeze_problems` 只有這四項；
   - `eval version-check --set pilot` exit 0（本文件沒有改任何程式或 Pilot 資料）；
   - `git diff --name-status 4b42a4a..HEAD` 只有 freeze 允許的路徑，加上這四個 `A`。
   held-out 結果的完整性仍由 tag `heldout-final`（e47f2c7）保留。
5. **第一次 CI 的結果**記在 NEXT.md。Linux runner 上若出現本機沒有的失敗，先記錄，再另寫 decision 處理，不在 CI 裡跳過測試。

## 為什麼

- 公開的 repo 應該有任何人都看得到的測試結果；「1116 passed」目前只寫在 NEXT.md。
- 在 CI 裡先 fetch，而不是把依賴 upstream 的測試改成缺少時 skip：測試是封存的檔案，不改；CI 也照首頁「Try it」的順序，先 fetch 再跑測試。
- 不快取 `env/upstream/`：淺層 clone 只抓一個 tag；快取要再引入一個 action（`actions/cache`），上面三個 repo 的 CI 都沒有用過，版本無法事先確認。
- `docker_cli` 也排除：CI 不檢查 Docker 相關的行為（`network`、`docker_daemon` 在首頁的指令裡本來就排除）。
- 設定放在新的 `ruff.toml`，不放 `pyproject.toml` 的 `[tool.ruff]`：新增檔案不改任何封存檔案的位元組；ruff 用 `uvx` 執行，所以 `uv.lock` 也不用改。

## 放棄的替代方案

- **把依賴 `env/upstream/` 的測試改成缺少時 skip**：要改封存的測試，CI 也就不會跑那 23 個測試。
- **修改 `env/soak.py:266`（拿掉 `f`），或在測試檔加 `# noqa: F811`**：改凍結的程式與測試，freeze 檢查會多出 `M` 的項目。之後若要修，另寫 decision。
- **把 ruff 加進 dev 依賴、設定寫進 `pyproject.toml`**：要改兩個封存的檔案（`pyproject.toml`、`uv.lock`）。
- **整個 `tests/` 忽略 F811，或全域忽略 F541**：範圍比需要的大，之後真正的問題會被藏起來。
- **快取 `env/upstream/`**：見「為什麼」。

## 對實驗的影響

- 沒有。程式、測試、資料、label、gold、結果與 Gate 判定都不變。
