# 001 — 鎖定 OpenTelemetry Demo 3.1.0（commit `dedc017`）與啟動參數

- 狀態：Accepted（2026-10-08）
- 影響範圍：實驗環境（Core §1）。任何 incident 的 manifest 都用 sha256 指向 `env/otel-demo.lock.json`。

## 背景

Core §1 要求鎖定 OTel Demo 的 git commit / release tag、Docker image digest、啟動參數、traffic generator 設定、
fault config、random seed 與收集時間窗。2026-10-08 用 5 個平行研究 agent 加上逐條反向覆核，對照 pinned commit 原始碼與
registry（ghcr / Docker Hub / quay）查證，重點發現如下：

1. **只 checkout tag 不等於跑 3.1.0。** 每個 demo service 都寫成 `image: ${IMAGE_NAME}:${DEMO_VERSION}-<svc>`，
   而 tag 上的 `.env` 是 `DEMO_VERSION=latest`。`latest-<svc>` 每天 00:00 UTC 會被 nightly build 覆寫
   （2026-10-08 的 `latest-*` 是從 main `c853f7e` build 的，比 3.1.0 新 70 個 commit），
   而且 main 已經改了 fault 語意（`kafkaQueueProblems` 的 variants、新的 `kafkaConsumerDead`）。
   本機實測：`latest-frontend` ≠ `3.1.0-frontend` ≠ `3.0.0-frontend`。
2. **Tag 停在 "Prepare release" 的前一個 commit。** `3.1.0` 是 lightweight tag，指向 `dedc017`；
   `898ede2`（#3968）才把 `IMAGE_VERSION` 改成 3.1.0 並升級第三方 image。所以 tag 上 `IMAGE_VERSION=3.0.0`，
   會讓所有 telemetry 的 `service.version` 標成 3.0.0。
3. **3.1.0 image 和 tag commit 是一致的。** 全部 21 個 `3.1.0-<svc>` image 的 SLSA provenance 都記錄
   `vcs.revision=dedc017`（release run 35377943879），每一個都有 linux/arm64 + linux/amd64。
   `dedc017` 的 CI 230 個 check 全綠（包含 Telemetry Tests minimal / full）。
4. Tag 與 release 都**不是 immutable**（release `immutable=false`，3.1.0 release workflow 也跑了兩次），
   所以只能靠 commit SHA 與 image digest 鎖定，不能靠名字。

## 決策

| 項目 | 值 |
|---|---|
| Upstream | `open-telemetry/opentelemetry-demo` tag `3.1.0` = commit `dedc0178918e260823323b8d95005a8cb924b007`（以 commit 為準） |
| Compose 組合 | `compose.yaml` + `compose.full.yaml` + `compose.observability.yaml` + 產生的 `env/compose.pinned.yaml`（28 個 service，traces→Jaeger、metrics→Prometheus、logs→OpenSearch，含 Kafka） |
| Env files（順序） | upstream `.env` → `env/otel-demo.overrides.env` |
| Overrides | `DEMO_VERSION=3.1.0`、`IMAGE_VERSION=3.1.0`，並重新宣告 `OTEL_RESOURCE_ATTRIBUTES`（upstream `.env` 解析時就展開了，不重宣告的話 override 不會生效；`tests/test_traffic.py` 負責守住） |
| Images | 28 個 image 全部用 index digest 鎖在 `env/compose.pinned.yaml`；lock 同時記錄每個 image 的 arm64 / amd64 manifest digest |
| 必要平台 | `linux/arm64`（Mac M4 Pro，主要收集機）與 `linux/amd64`（RTX 桌機備援） |
| 啟動指令 | `docker compose … up --detach --no-build --pull missing --remove-orphans --force-recreate --renew-anon-volumes`（`--no-build`：每個 demo service 同時有 `image:` 與 `build:`，pull 失敗時 compose 會默默改成用本機原始碼 build；`--force-recreate` + `--renew-anon-volumes`：每個 run group 都從乾淨的 container **與 anonymous volume** 開始。Prometheus image 宣告了 `VOLUME /prometheus`，只用 `--force-recreate` 的話會沿用上一個 run 的 TSDB，保留期 7 天） |
| Compose project | `ii-otel-demo` |
| 執行環境 | `python -m env compose …` 會把 process env 清成 allowlist（PATH、HOME、DOCKER_HOST/CONTEXT/CONFIG…），避免 shell 裡殘留的 `DEMO_VERSION`、`COMPOSE_FILE`、`_JAVA_OPTIONS`、`DOCKER_DEFAULT_PLATFORM`（會讓 M4 拉 amd64 image 用模擬執行）改到 stack。任何可能啟動 container 的子指令（`up`、`start`、`run`、`scale`、`watch`…）在 `verify` 失敗時都會被拒絕；`verify` 也要求 upstream working tree 乾淨 |
| Bind mounts | lock 記錄每個 bind-mount 來源檔／目錄的 sha256（collector configs、flagd 目錄、grafana / jaeger / prometheus config、postgres init.sql）；host bind（`/`→`/hostfs`、docker.sock）標記為 `host`，不做 hash |

工具：`python -m env {fetch-upstream, resolve, pin, verify [--online], compose, compose-cmd}`（見 `env/README.md`）。
人工編輯的輸入是 `env/otel-demo.spec.json`，產生物是 `env/otel-demo.lock.json` 與 `env/compose.pinned.yaml`。

## 為什麼是 3.1.0

| | 3.1.0 | 3.0.0 | 2.2.0 |
|---|---|---|---|
| maintainer 態度 | 目前最新的穩定版；沒有 3.1.1 在準備中 | release note 寫明 "problematic — please use v3.1.0"（k6 load generator 是 AGPL） | 舊版 |
| load generator | Locust（Apache-2.0） | k6 + xk6-otel，browser scenario 有 bug（#3820，`imageSlowLoad` 下會 timeout） | Locust |
| fault flags | 18 個（15 個是 fault） | 15 個 | 15 個（含 llm*，cartFailure 只有 on/off） |
| 已知問題 | load generator 關閉時偶發 crash（#4021/#4022，只發生在 teardown）；currency #3989 | k6 browser 在 `imageSlowLoad` 下會 timeout（#3820） | flagd-ui 記憶體問題（#3022，在 k8s 量到約 2.3 GB）；accounting memory leak；舊的 `app.*` attribute schema |
| arm64 | 21/21 image 都有 | 有 | 有 |

## 放棄的替代方案

- **跟 main / nightly**：會一直變，而且已經改了 fault 語意。
- **鎖 `898ede2`（Prepare release commit）**：它升級的依賴（OpenSearch 3.8、Jaeger 2.21）弄壞了 telemetry tests（#4012），也跟實際發布的 3.1.0 image 不一致（image 是從 `dedc017` build 的）。
- **只鎖 tag、不鎖 digest**：會跑到 `latest-*` image；tag 本身也可能被改。
- **本機自己 build image**：base image 與 build 過程不可重現，在 M4 上也慢；而且會失去 upstream provenance。
- **只用 core 或 core+observability**：core 只輸出到 debug exporter，什麼都不會留下；不含 full 的話，`kafkaQueueProblems` 不會有作用。

## 對實驗的影響

- 環境與 upstream tag 預設的差異（都寫在 `env/otel-demo.overrides.env`）：`DEMO_VERSION`、`IMAGE_VERSION`、`OTEL_RESOURCE_ATTRIBUTES`。
  Agent 看到的 `service.version` 會是 `3.1.0`（正確值），而不是 tag `.env` 預設的 `3.0.0`。
- 任何啟動參數改變（例如 M2 要加的 raw-export collector overlay）都必須重新 `python -m env resolve`，產生新的 lock sha256。
  **不同 lock sha256 收集到的資料不得混用**，除非另開 decision log。
- `src/flagd/demo.flagd.json` 是 bind-mount 進 flagd 與 flagd-ui 的可寫檔案（flagd-ui 會寫入 host 上的 checkout）。
  lock 有記錄它的 hash，`verify` 與 `compose up` 會擋下「上一個 run 留下 flag」的狀況。
- 已知但不修的 upstream 行為（記錄起來，leakage audit 與 failure taxonomy 要考慮）：
  - Grafana 啟動時會抓沒有固定版本的 `grafana-opensearch-datasource` plugin（只影響 UI，不影響 telemetry 匯出）。
    （2026-10-10 起暫時關掉：project overlay 把 `GF_INSTALL_PLUGINS` 設為空，新的 lock，見 decision 028。）
  - observability 模式下 collector config 會丟掉 `prometheus/ad` receiver（ad 的 Prometheus custom metrics 不會被收集；ad 的 OTLP metrics 不受影響）。
    （更正，decision 008：是 full layer 的 metrics receivers list 拿掉的；我們的組合一定載入 full，效果相同。）
  - observability 的 profiles pipeline 會輸出到 firepit，但 firepit 只存在於 profiling layer → collector 自己的 log 裡可能出現 exporter 錯誤。
  - `_JAVA_OPTIONS`（JDK-8345296 在 macOS/AArch64 的 SIGILL workaround，值是 `-XX:UseSVE=0`）會從環境傳進 ad / fraud-detection / kafka / opensearch。
    我們的 sanitized env 讓它**一律不設定**。3.1.0 arm64 image 裡 ad（JDK 24.0.2）、fraud-detection（17.0.18）、kafka（21.0.11）的 JDK 都已經包含修正；
    opensearch 內建的 JDK 版本沒有查。若 smoke test 發現 M4 上 JVM 會 SIGILL，改在 `otel-demo.overrides.env` 設定（已驗證 bare key 會從 `--env-file` 取值），並補一篇 decision log。
  - `ask_agent` 背景錯誤與 traffic 相關議題見 003。
- **Runtime 驗證（2026-10-08 Mac smoke test，見 `docs/smoke-tests/2026-10-08-m1-mac-smoke.md`）**：
  28/28 container 實際跑的是 lock 的 pinned ref、index digest 與 **linux/arm64** manifest（`python -m env verify-running`），
  JVM 沒有 SIGILL（`_JAVA_OPTIONS` 維持不設定）；traces / metrics 都有流到 backend，logs 有，但被 OpenSearch 大量丟棄（見下）。
  這一步很重要：upstream 的 arm64 image 是在 x64 runner 上用 QEMU cross-build 的，upstream CI 的 telemetry tests 只跑 amd64。
- Smoke test 發現的環境性質（不修改鎖定環境；正式收集前要在收集協定或另一篇 decision log 處理）：
  - product-catalog 長期貼著 upstream 的 20 MiB memory cgroup 上限運作（run 2：`memory.current` 17.1–19.9 MiB，15 分鐘內碰到上限 86,416 次，持續 swap）。
    Run 1 因此被 memcg OOM-kill 一次；另外約 08:15:4x 起卡住，直到收集證據時都還沒恢復（是否也是記憶體壓力造成，推測但未證實）。
    Run 2 的 15 分鐘內兩者都沒有觀察到。
  - Run 1 冷啟動時有大量 504（product-catalog 很慢）；run 2 沒有。只排除暖機期不足以保證穩定。
  - OpenSearch exporter 因 `attributes.http` mapping 衝突持續拒收相當比例的 log（run 1 逐筆拒收 1,624 次、run 2 3,073 次）→ OpenSearch 不能當 snapshot 的 source of truth。
  - Grafana runtime 安裝的 plugin 版本是 `grafana-opensearch-datasource` v2.34.4（未鎖定，只影響 UI；decision 028 起暫時不安裝）。
  - upstream 把 compose network 名稱寫死成 `opentelemetry-demo`。
