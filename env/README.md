# env/ — 鎖定的 OTel Demo 環境

Core §1。為什麼是這個版本、這組 compose 與這些 override，見 `docs/decisions/001-pin-otel-demo-3.1.0.md`。

| 檔案 | 誰寫的 | 內容 |
|---|---|---|
| `otel-demo.spec.json` | 人 | upstream repo / tag / commit、compose 檔組合、env 檔順序、啟動參數、必要平台 |
| `otel-demo.overrides.env` | 人 | 疊在 upstream `.env` 之上的變數（`DEMO_VERSION`、`IMAGE_VERSION`…）；每改一行都要寫 decision log |
| `otel-demo.lock.json` | `python -m env resolve` | upstream commit、每個檔案 / bind mount 的 sha256、28 個 image 的 index digest 與 arm64 / amd64 manifest digest、`up` 參數 |
| `compose.pinned.yaml` | `python -m env resolve` / `pin` | compose override：每個 service 都改成 `image: <ref>@sha256:<index digest>` |
| `upstream/opentelemetry-demo/` | `python -m env fetch-upstream` | upstream shallow clone（gitignored） |

## 常用指令

```bash
uv run python -m env fetch-upstream   # clone tag 並確認 commit = spec
uv run python -m env verify           # checkout、checksum、pinned override、compose render 都要符合 lock
uv run python -m env verify --online  # 再確認 registry 上每個 digest 都還拉得到
uv run python -m env compose ps       # 用 sanitized env 對鎖定的 stack 執行 docker compose
uv run python -m env verify-running --wait 180   # 執行中的 container = lock 的 image 與平台 manifest，且 running/healthy、沒有重啟
uv run python -m env compose-cmd up   # 只印出完整指令
```

正式 incident collection 必須拿 Mac heavy lock（`MACHINE_POLICY.md`），而且要在 stack **整個存活期間**都持有 lock。
`compose up` 是 `--detach`，所以單獨包 `up` 的話，container 一啟動 lock 就被釋放了。要讓 up → 收集 → down 都在同一個持有 lock 的 process 裡。
手動操作（例如 smoke test）時，可以開一個持有 lock 的 shell，結束時 `exit` 就會自動釋放：

```bash
./tools/with-mac-lock zsh
```

在那個 shell 裡跑 `uv run python -m env compose up` … `uv run python -m env compose down --volumes`。

除了 `ps`、`logs`、`exec`、`stop`、`down`、`config` 這類不會啟動 container 的子指令，`python -m env compose …` 都會先跑等同 `verify` 的離線檢查：
upstream commit、upstream working tree 是否乾淨（`git status --porcelain --untracked-files=all --ignored`，連 Finder 產生的 `.DS_Store` 也算）、所有 checksum、pinned override。
例如上一個 run 留下改過的 `src/flagd/demo.flagd.json`（或 flagd-ui 留下的 `demo.flagd.json.tmp`）時就會拒絕啟動。`resolve` 也會拒絕在不乾淨的 checkout 上產生 lock。
手動修復方式：

```bash
git -C env/upstream/opentelemetry-demo checkout -- .
git -C env/upstream/opentelemetry-demo clean -fdx   # -x: also ignored files such as .DS_Store, which change bind-mount hashes
```

## 改環境的流程

1. 寫 decision log（`docs/decisions/`）。
2. 改 `otel-demo.spec.json` 或 `otel-demo.overrides.env`（換版本時同時改 commit，再 `rm -rf env/upstream && … fetch-upstream`）。
3. `uv run python -m env resolve`：沒有通過檢查（缺 arm64、floating tag、demo image 不是 `<tag>-*`…）就不會寫出 lock。
4. `uv run pytest`。
5. 不同 lock sha256 收集到的資料不得混用。
