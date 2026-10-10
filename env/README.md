# env/ — 鎖定的 OTel Demo 環境

Core §1。為什麼是這個版本、這組 compose 與這些 override，見 `docs/decisions/001-pin-otel-demo-3.1.0.md`。

| 檔案 | 誰寫的 | 內容 |
|---|---|---|
| `otel-demo.spec.json` | 人 | upstream repo / tag / commit、compose 檔組合、env 檔順序、啟動參數、必要平台 |
| `otel-demo.overrides.env` | 人 | 疊在 upstream `.env` 之上的變數（`DEMO_VERSION`、`IMAGE_VERSION`…）；每改一行都要寫 decision log |
| `otel-demo.lock.json` | `python -m env resolve` | upstream commit、每個檔案 / bind mount 的 sha256、28 個 image 的 index digest 與 arm64 / amd64 manifest digest、`up` 參數 |
| `compose.pinned.yaml` | `python -m env resolve` / `pin` | compose override：每個 service 都改成 `image: <ref>@sha256:<index digest>` |
| `compose.overrides.yaml` | 人 | 本 Project 的 compose overlay：memory limit（decision 004 / 007）、collector 的 raw export layer（decision 008）、grafana 啟動時不依 `GF_INSTALL_PLUGINS` 下載 plugin（設為空，decision 028，暫時；Grafana 自己預設的其他網路行為不變）；每一項都要有 decision log |
| `otelcol-config-raw.yml` | 人 | collector 的 extras layer：只新增 `traces/raw`、`metrics/raw`、`logs/raw` 與 `file/raw_*`，不改任何 upstream pipeline（decision 008） |
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

## Baseline soak test（decision 004）

正式 collection 前、以及任何環境變更之後，都要在 heavy lock 下跑一次：

```bash
./tools/with-mac-lock uv run python -m env soak --minutes 30 --warmup-minutes 5
```

指令會自己執行 up → `verify-running` → 暖機 → 30 分鐘取樣 → 收集證據 → `down --volumes` → `verify`。
從 `up` 之前到 `down` 之前，另外用 `docker events` 記錄本 Project container 的 oom / die 事件（`docker-events.jsonl`）：
container 重啟時 cgroup 會重建、`memory.events` 歸零，只看 memcg 會漏掉 OOM kill（decision 004 修訂）。
取樣窗少於 30 分鐘、沒有持有本 Project 的 heavy lock、或已經有本 Project 的 container（要先 `compose down --volumes`），都會被拒絕。
`compose up` 失敗時仍會 `down` 並寫出報告。
鎖定的 stack 有 raw pipeline 時（decision 008），視窗結束後再 drain 3 分鐘（`--drain-minutes`），接著 `stop -t 120 otel-collector`，
在 `down` 之前把 `/raw` 用 `compose cp` 複製到結果目錄的 `raw/`，再用 R7（collector 正常停止、檔案都在；這個 lock 的 collector 停止時一定 exit 1，所以 exit 1 要靠保存下來的 `otel-collector-shutdown.log` 證明只是 self-telemetry 推給自己失敗，見 decision 008 修訂）、R8（每行都能解析）、R9（視窗內每分鐘三種 signal 都有資料）判定。
結果寫在 `data/external/soak/<UTC 時間>/`（`report.md`、`report.json`、`samples.jsonl`、`docker-events.jsonl`、`raw/`、log、docker inspect）；
R1–R6（有 raw pipeline 時加上 R7–R9）全部通過才算 baseline 穩定。報告記錄 lock 的 sha256，收集前會檢查「這個 lock」通過過 soak（decision 009）。

## 改環境的流程

1. 寫 decision log（`docs/decisions/`）。
2. 改 `otel-demo.spec.json`、`otel-demo.overrides.env` 或 `compose.overrides.yaml`（換版本時同時改 commit，再 `rm -rf env/upstream && … fetch-upstream`）。
3. `uv run python -m env resolve`：沒有通過檢查（缺 arm64、floating tag、demo image 不是 `<tag>-*`…）就不會寫出 lock。
   它會向 registry 重查每個 tag 的 digest（tag 可以被改）；只改 project 檔、image 不變時，可以改用離線重算，沿用 lock 裡的 digest
   （decision 028「決策 2」的指令），之後用 `git diff env/otel-demo.lock.json` 確認只有預期的 sha 與 `generated_at` 改變。
4. `uv run pytest`。
5. 不同 lock sha256 收集到的資料不得混用。
6. 新 lock 要先通過 soak（上面的指令）才能收集：collect 的 preflight 只接受 `env_lock_sha256` 等於目前 lock、通過且 teardown 乾淨的 soak 報告。
   held-out freeze 會釘住 lock 但**不檢查 soak**，所以新 lock 的 soak 要在 `collect heldout-freeze` 之前 PASS（decision 028）。
