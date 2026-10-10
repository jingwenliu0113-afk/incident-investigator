# 028 — 暫時關掉 grafana 啟動時的 plugin 下載（`GF_INSTALL_PLUGINS` 設為空）

- 狀態：Accepted（2026-10-10，使用者決定；**暫時**）。在 held-out freeze 與任何 held-out 資料之前寫定。
  使用者原話（回覆 NEXT「Blocked / 需要使用者」A0 的提議）：「先暫時兩個都同意，先關掉 grafana 下載再測本地模型，之後可以考慮再換回來原本的方案」。
  本文件只處理前半（grafana）；「本地模型」屬於 A1，不在這裡。「之後可以考慮再換回來」：換回來的條件與方式見「換回原本的方案」。
- 影響範圍：`env/compose.overrides.yaml`（grafana 的 environment 一個鍵）→ env lock 的 sha256 改變
  （`sha256:055cc7a0…` → `sha256:1e749f6737440e8851ae6f193a4b6f79108336d5c7c551ed8c30694a485f92ab`）；`tests/test_locked_env.py`；`env/README.md`；
  `env/otel-demo.spec.json` 的 notes（不在 lock 的雜湊範圍內）。
  **不改**：SUT 服務、28 個 image digest、collector config、bind mount、normalize policy、指標、split、門檻、預算、收集協定或任何 decision 的規則。

## 背景

- **upstream 的設定**（`env/upstream/opentelemetry-demo/compose.observability.yaml`，service `grafana`）：environment 是 list 形式的
  `"GF_INSTALL_PLUGINS=grafana-opensearch-datasource"`；bind mount `src/grafana/provisioning/` 裡的 `datasources/opensearch.yaml` 是
  type `grafana-opensearch-datasource` 的 datasource（uid `webstore-logs`），Jaeger datasource 的 traces-to-logs 與 4 個 dashboard
  （`apm-dashboard`、`events-by-name`、`demo-dashboard`、`opentelemetry-collector`）都用到它。
  plugin 版本沒有固定，由啟動當下的 grafana.com 決定（decision 001「對實驗的影響」：smoke test 裝到 v2.34.4）；
  Grafana 13.1.0 仍支援這個變數，會印 deprecated 警告（研究筆記 §7）。grafana 沒有 healthcheck，`restart: unless-stopped`。
- **Pilot 的證據**：收集的 18 個 run group 中有 5 個（RG-004–006、RG-011、RG-012）在暖機前 `aborted_unstable`：grafana 從 grafana.com 下載
  plugin 逾時（網路慢，grafana.com 3–9 s）而一直重啟，G1（從 up 起所有 container 的 `RestartCount` = 0）失敗（decision 016「實作說明」、NEXT）。
  另外 RG-001 的 G1 也是因為 grafana：15:25:44Z `die` exit 1、被 restart policy 拉起；原因**無法得知**（container 已 `down`，當時還沒有保存重啟 container
  log 的診斷），當時 grafana 的 memory.current 是 174.9 / 175 MiB；同一個閘門 G2 也因 payment 的 healthcheck 失敗（decision 009「RG-001」）。
  所以已確認是下載逾時的是 5 次；RG-001 是否與下載有關不知道。
  每次只浪費約 5 分鐘、不影響資料，但在 held-out 每一次都算該 slot 的一次無效嘗試：同一個 slot 3 次無效 → 待人處理；同時 3 個 slot 待人處理 → 全部停止收集（023 §4）。
- **grafana 不是 SUT**：decision 011 的 X1 非 SUT 服務；decision 005：grafana 只能當人工檢視的 UI，不得作為方法的資料來源。
- 原 A0：Pilot 期間不改 env lock；held-out freeze 前再決定是否關掉（改 lock、新 soak）。

## 決策

1. **overlay**：`env/compose.overrides.yaml` 加上 `services.grafana.environment.GF_INSTALL_PLUGINS: ""`（設定為空字串）。
   - compose 依變數名稱合併 environment，upstream 的 list 形式與 overlay 的 map 形式不影響結果。用專案自己的 render（`env.compose.render_config`，
     即 `docker compose config`，不需要 daemon）確認：render 後 grafana 的 environment 是 `{"GF_INSTALL_PLUGINS": ""}`（upstream 是
     `grafana-opensearch-datasource`）；整個 stack 與沒有 overlay 時相比，只多了這一個欄位的差異（`tests/test_locked_env.py`）。
   - 只關掉這個變數要求的安裝。Grafana 自己的預設行為（例如預設的 plugin preinstall、更新檢查等其他網路請求）不改，**也沒有驗證過**
     Grafana 13.1.0 實際會做哪些（repo 裡只有研究筆記 §7「13.1.0 仍支援 `GF_INSTALL_PLUGINS`」；upstream `grafana.ini` 的 `[plugins]` 沒有設 preinstall）。
     沒有證據顯示 Pilot 的無效 run 與它們有關（RG-001 的 grafana exit 1 原因不明，見背景），所以不改。
2. **lock 用離線方式重算，image digest 不動**：`env.cli.cmd_resolve` 以「目前 lock 裡的 digest」作為 image resolver（不查 registry；
   lock 裡沒有的 image ref 直接拒絕），其餘照常（upstream checkout 必須乾淨、`docker compose config` render、`build_lock`、`check_lock`、寫出 lock 與 pinned override）。
   結果與舊 lock 的差異只有兩個欄位：`generated_at` 與 `env/compose.overrides.yaml` 的 sha256（`fe1da17d…` → `7d4218ca…`）；
   28 個 image 的 index / 平台 digest、bind mount、`env/compose.pinned.yaml` 都逐 byte 相同。離線的 `python -m env verify`（含 render）通過。
   - 為什麼不用 `python -m env resolve`：它會向 registry 重新查每個 tag，而 tag 可以被改（decision 001 背景 4），重查可能讓與本決定無關的 image digest 改變。
   - 重算方式（記錄以便重現；只在 project 檔改變、image ref 不變時適用）：在專案目錄
     `PYTHONPATH=. uv run python -c 'import json; from env.cli import UPSTREAM_DIR, cmd_resolve; from env.lock import LOCK_PATH, PROJECT_DIR; from env.registry import ResolvedImage; old = json.loads((PROJECT_DIR / LOCK_PATH).read_text()); locked = {i["ref"]: ResolvedImage(i["ref"], i["index_digest"], i["media_type"], dict(i["platforms"])) for i in old["images"]}; print(cmd_resolve(PROJECT_DIR, (PROJECT_DIR / UPSTREAM_DIR).resolve(), resolve_image=lambda ref: locked[ref])[1])'`
     （印出 `[]` 表示寫出；之後用 `git diff env/otel-demo.lock.json` 確認只有上述兩個欄位改變）。
   - 審查後修正了 overlay 的註解（原本寫「image 什麼都不裝」，沒有證據），用同一個方式再重算一次。中間版本的 lock `sha256:88c4989f…`
     （commit `c058a89`）沒有跑過 soak、也沒有收集過任何資料，作廢。
3. **測試**（`tests/test_locked_env.py`，先寫、看到失敗才改 overlay）：
   - render 差異測試：允許的差異加上 `services.grafana.environment.GF_INSTALL_PLUGINS`，其餘不變；
   - grafana 的 environment：overlay 後為 `""`、upstream 為 `grafana-opensearch-datasource`，其他鍵相同；
   - 新增：lock 記錄的每個 project 檔（compose / env 檔、bind mount）的 sha256 都等於 commit 的檔案。只改 overlay、沒重算 lock 時這個測試失敗
     （原本只有 `env verify` 與 `compose up` 會發現；這個測試不讀 upstream checkout，收集進行中改寫 flag 檔也不受影響）。
   - 新增：`env/otel-demo.spec.json` 列出 overlay 內容的那條 note 要提到 overlay 設定的每個 service（spec 不在 lock 的雜湊範圍內，沒有別的檢查）。

## 為什麼

- 下載逾時造成的無效 run 只取決於當下的網路，與 fault、SUT 都無關；held-out 有 50 個 slot、約 38 小時 lock（023），每次網路慢都可能把 slot 推向「待人處理」甚至讓收集全部停止。
- 下載的 plugin 版本沒有固定，等於每次啟動的環境都可能不同；關掉之後，至少不再由這個變數從 grafana.com 安裝一個沒有固定版本的 plugin。
  Grafana 自己預設的其他網路行為不在這次的範圍內，也沒有驗證（決策 1），所以不能說 grafana 的內容「完全固定」。
- grafana 不是 SUT，它的資料不進 snapshot（見下方「對實驗的影響」），所以關掉它的 plugin 不改變方法看到的任何資料。

## 放棄的替代方案

- **維持下載（現況）**：見「為什麼」；網路慢時繼續產生無效 run，plugin 版本也繼續不固定。
- **自己 build 一個裝好固定版本 plugin 的 grafana image**：本機 build 不可重現、失去 upstream provenance（decision 001 已放棄本機 build）；
  `up` 使用 `--no-build`，lock 工具也假設每個 image 都能從 registry 用 digest 取得（`verify --online`、`check_rendered`），要另外處理；為了一個非 SUT 的 UI 不值得。
- **把 plugin 放進 repo 用 bind mount 掛進去**：仍要先從 grafana.com 下載一次；plugin 帶有各平台（arm64 / amd64）的 backend 執行檔，不適合放進 git
  （追蹤的檔案有 1 MiB 上限，`tests/test_repo_hygiene.py`），也有再散布授權的問題；放在 git 之外則 lock 無法由 commit 重現。為了一個非 SUT 的 UI 不值得。

## 對實驗的影響

- **收集要等新 lock 的 soak**：collect 的 preflight（`collect/live.py` `LiveStack.preflight` → `passing_soak`）要求
  `data/external/soak/*/report.json` 中有一份 `pass: true`、`teardown.verify == []`、而且 `env_lock_sha256` 等於**目前** lock 的報告（decision 009 §2）。
  soak #5 是舊 lock `sha256:055cc7a0…` 的，所以在新 lock 的 soak 通過之前，`collect run`（Pilot / held-out）、`collect pilot-loop`、`collect smoke`
  一律拒絕（`no passing baseline soak for lock sha256:1e749f67…`）。soak 在 main checkout 合併本變更之後**馬上**、heavy lock 下執行（不必等 A1；
  順序見下方「必須在 held-out freeze 之前」）：
  `./tools/with-mac-lock uv run python -m env soak --minutes 30 --warmup-minutes 5`（約 40–45 分鐘：up、`verify-running` 最多等 5 分鐘、暖機 5、視窗 30、
  drain 3、collector 停止最多 2 分鐘、複製 raw、`down`）。判定沿用 decision 004 / 008 的 R1–R9（含修訂），不改。soak 程式不檢查電力模式；
  建議與正式收集同樣在高效能模式 + AC 下執行（decision 025 修訂 3），讓環境條件一致。
- **soak 的哪一條會發現 grafana 起不來**：grafana 照樣 provision `grafana-opensearch-datasource` 類型的 datasource，但 plugin 已不存在。
  - grafana 若因此結束或 crash loop：`restart: unless-stopped` 會把它拉起、`RestartCount` 增加 → **R1**（從 up 到結束，全部 28 個 container 的 `RestartCount` 為 0）失敗；
    被 OOM / SIGKILL 時另有 **R2**。正式 run 的穩定閘門 G1 用同一個條件，所以這種情況下每個 run 都會無效，soak 會先發現。
  - **沒有任何一條規則看 grafana 是否「正常運作」**：grafana 沒有 healthcheck（R4 只看有 healthcheck 的 container）、Locust 不打 `/grafana`（R3）、
    grafana 不送 telemetry（R5、R9）、soak 也不保存 grafana 的 log。grafana 繼續執行但 datasource / dashboard 壞掉，不會被任何規則抓到；
    這不影響 snapshot（見下一項），也不在判定範圍內。
  - 本機沒有用 Docker daemon 實際啟動驗證。**soak 只能確認 grafana 沒有因此重啟（R1）或被 kill（R2），不能確認它真的沒有下載東西**：
    soak 只保存 otel-collector 與 product-catalog 的 log 和 `docker inspect`（`env/cli.py` `cmd_soak`）；`docker inspect` 只證明環境變數是
    `GF_INSTALL_PLUGINS=`，證明不了 grafana 有沒有連 grafana.com。網路快的時候，就算還在下載，soak 照樣 PASS。
  - **soak 期間的人工確認（只讀，不是判定條件）**：soak 開始約 5 分鐘後、soak 結束（`down`）之前，另開終端執行一次
    `docker logs grafana 2>&1 | grep -iE 'plugin|install'`（`grafana` 是 upstream 的 `container_name`），把看到的內容
    （有沒有安裝 / 下載 plugin、OpenSearch datasource 的 provisioning 錯誤）記在本文件的補註。它不改 soak 的判定、不影響 PASS / FAIL；
    若看到仍有下載，回報使用者再決定。
- **不重做校準**：
  - policy v1 已凍結（decision 011 §4）。F1–F6 是凍結條件、只在凍結時用一次，之後任何改動都是 v2。
    校準（`collect calibrate`）與 policy 的凍結都不看 env lock；incident 的 normalize 會以目前 lock 的 sha 檢查 manifest（見下方「Pilot 與 held-out 的可比性」）。
  - 統計 baseline v2 的門檻（decision 014 修訂 1）是由 soak #3 / #5 的校準 snapshot 定下的固定參數；Pilot 上的修訂已由使用者放棄（014 補註 2026-10-10，freeze 檢查強制 waived）。
    在新的 soak 上重算門檻等於修訂統計 baseline，不做。程式也沒有任何地方要求校準與 lock 相符（`collect calibrate` 只要求是 soak 目錄）。
  - grafana 的資料在校準 snapshot 與 incident snapshot 裡都被 X1 丟掉，所以門檻的輸入本來就不含 grafana。
- **grafana 不會出現在方法看得到的資料**（所以 Pilot 與 held-out 在可見資料的定義上相同）：
  - spans / logs：grafana 不送 OTel telemetry（`grafana.ini` 的 tracing 區段是空的，compose 沒有給它 OTEL 變數）；
    frontend-proxy 有 `/grafana` 路由與 `grafana` cluster，但 Locust 不打 `/grafana`，就算有也被 X4（控制面路由，含 Envoy upstream cluster 與 URL path）整棵丟掉。
  - metrics：docker_stats 以 `container.name` 歸屬，`grafana` 在 policy 的 `excluded_services` → X1 丟掉；host_metrics 整個丟掉（X2）。
    decision 012 的 container metrics 覆蓋只檢查 18 個 SUT。
  - grafana 的 alert rule 只查 Prometheus（`webstore-metrics`）與 expression，不用 OpenSearch，行為不變；Prometheus / OpenSearch 本來就不是資料來源（005）。
  - frontend-proxy 對 grafana 的 `depends_on` 是 `service_started`，啟動順序不變。
  - 唯一可能的間接管道：grafana 在共用的 Docker VM 裡用的 CPU / 記憶體可能改變（不再安裝 plugin，也少了 plugin 可能帶的 backend process；
    RG-001 時 grafana 的 memory.current 達 174.9 / 175 MiB 的 upstream limit，decision 009）。這只影響 VM 的資源競爭，量不到、也不在 snapshot 裡；
    與 025 記錄的「soak #3 / #5 沒有電力模式紀錄」同一類已知限制，不因此修改任何門檻。
- **Pilot 與 held-out 的可比性**：Pilot 在舊 lock（`055cc7a0…`，有 plugin）上收集，held-out 會在新 lock（`1e749f67…`，沒有 plugin）上收集。
  decision 001「不同 lock sha256 的資料不得混用，除非另開 decision log」：本文件記錄兩者的差異只有 grafana 的 plugin，而 Pilot 本來就不進 test、
  Gate 只看 held-out（023），兩個 set 從不合併計算；報告中拿 Pilot 與 held-out 做比較時（例如難度、無效率）要註明這個環境差異。
  held-out 的無效率預期只能扣掉 Pilot 已確認是下載逾時的 5 次；RG-001 的 grafana exit 1 原因不明（背景），不能假設它也會消失。
  不能直接拿 Pilot 的無效率當 held-out 的預期。
  Pilot 已有的 snapshot、label、review、gold 與 baseline 結果都不受影響，不重收、不重算；LLM 方法在 Pilot 上執行（A1）讀的也是這些 snapshot。
  Pilot 的 10 個有效 incident 都已 normalize。新 lock 之下，`normalize_incident` 以**目前** lock 的 sha 檢查 manifest（`check_manifest`），
  舊 lock 收集的 run group 會被拒絕（lock sha 不符）。所以若之後在 Pilot 上做 011 的 v2 修訂（011 §4：所有 incident 重跑 normalize），
  Pilot 的重跑會被這個檢查擋下，要在那篇修訂 decision 裡處理（例如改為比對 run 自己記錄的 lock）；這裡不預先改程式。換回舊 lock（見下）則不受影響。
- **必須在 held-out freeze 之前定案，而且新 lock 的 soak 必須在 freeze 之前 PASS**：freeze 紀錄寫入 `env_lock_sha256`（`collect/freeze.py`），
  之後 lock 有任何不同都讓 held-out 收集、清單與 eval 停止（023 §6、026 解讀 7；A4 沒有 freeze 後的修正路徑）。所以 held-out 期間不能換回，也不能混用兩個 lock。
  - `collect heldout-freeze` **不檢查 soak**：`write_freeze` 對 lock 只檢查 `env_lock_sha256` 存在；`passing_soak` 只在收集的 preflight 用到（`collect/live.py`）。
    合併本變更之後，目前的 lock（`1e749f67…`）沒有任何 PASS 的 soak。如果先 freeze、soak 之後才失敗（例如 grafana 缺 plugin 而 crash loop，R1 失敗），
    修正就要改 overlay 或 lock，但 freeze 已經釘住它們：held-out 收集被 preflight 拒絕，又沒有 freeze 後的修正路徑，held-out 就卡死。
  - 所以順序是：**合併後馬上跑新 lock 的 soak（不必等 A1）→ PASS → 之後才能 `collect heldout-freeze`**。
  - soak 沒有 PASS 時，在 freeze 前由使用者決定：逐 byte 還原 overlay 與 lock 換回原方案（沿用 soak #5，見下一節），或另寫 decision 修正後再跑 soak。
  - 這個順序目前只靠流程保證（NEXT A0 與 Core 順序）。要用程式擋（例如在 freeze 檢查加上 `passing_soak(…, env_lock_sha256)`）等於改 freeze 協定
    （023 §6 / 026），要另寫 decision；本文件不改。
    （2026-10-10 使用者決定「照建議」之後已由程式擋下：`collect heldout-freeze` 沒有目前 lock 的通過 soak 就拒絕，decision 026 修訂 3、解讀 31。）

## 換回原本的方案（使用者說之後可以考慮）

- 只能在 held-out freeze **之前**，並另寫一篇 decision（本文件的規則：每個 overlay 設定都要有 decision log）。
- 依程式，lock 的身分是 lock 檔內容的 sha256（`env.lock.lock_sha256`），而 preflight 找的是 `env_lock_sha256` 相同、通過、teardown 乾淨的 soak 報告：
  - 如果把 `env/compose.overrides.yaml` 與 `env/otel-demo.lock.json` **逐 byte 還原**成本變更之前的版本（例如
    `git checkout 36ff785 -- env/compose.overrides.yaml env/otel-demo.lock.json env/otel-demo.spec.json`，spec 只是 notes、不影響 lock；
    同時還原 `tests/test_locked_env.py` 的 grafana 部分），lock 的 sha 會回到 `sha256:055cc7a0…`，`verify` 通過（overlay 的 sha 也回到 `fe1da17d…`），
    soak #5（`data/external/soak/20261008T143533Z/`，PASS、teardown 乾淨）重新符合 preflight，**不需要再跑 soak**。
  - 如果改用重算（`python -m env resolve`，或上面的離線方式）產生 lock，`generated_at` 會不同 → sha 不同 → 需要再跑一次 soak。
- 換回之後的 held-out 會與 Pilot 在同一個 lock 上；plugin 下載逾時造成的無效 run 也會回來。

## 結果（2026-10-10，soak #6；在 held-out freeze 與任何 held-out 資料之前）

- **soak #6 PASSED**：`data/external/soak/20261010T053643Z/`（commit `0319280`，lock `sha256:1e749f67…`；開始前確認高效能模式 + AC；heavy lock 等 rust-hnsw 的 benchmark 釋放後才開始，
  沒有搶占）。視窗 2026-10-10T05:42:23Z – 06:12:31Z，R1–R9 全部通過（R1：141 筆狀態樣本，沒有任何 container 重啟；R3：2124 個請求 0 個 5xx），
  teardown 乾淨。ambient（decision 005）與之前同性質：ask_agent 失敗 111 次、OpenSearch mapping 拒收 8706。
  `collect.live.passing_soak(data/external, 新 lock)` 回傳這份報告 → **收集的 preflight 接受新 lock**；本文件「必須在 held-out freeze 之前」的順序已滿足。
- **grafana 的人工確認**（只讀，不是判定條件；grafana 啟動 5 分鐘後讀一次 `docker logs grafana`，`RestartCount = 0`）：
  - `grafana-opensearch-datasource` **沒有**被安裝：關掉的正是 Pilot 中造成無效 run 的同步安裝。
  - **但 Grafana 13.1.0 自己的背景安裝器（`plugin.backgroundinstaller`，預設的 preinstall 清單）仍會連網**：暖機期間（05:37:14–05:37:29Z，視窗開始之前）
    從網路下載並安裝 `grafana-lokiexplore-app` v3.0.0、`grafana-pyroscope-app` v2.3.1、`grafana-exploretraces-app` v2.2.1、`grafana-metricsdrilldown-app` v3.0.0
    （版本沒有固定），`elasticsearch` 與 `zipkin` 嘗試更新失敗（bundled 目錄 permission denied），失敗只寫 log、grafana 沒有重啟。
    這就是決策 1 寫的「其他網路行為不改、也沒有驗證過」，現在有了證據。
  - 判讀：本決定的目的（不再因下載逾時讓 run 在暖機前無效）由這次的證據支持：背景安裝是非同步的，失敗不會讓 grafana 結束。
    **環境並沒有因此完全離線、完全固定**：grafana 仍會連到 grafana.com、安裝沒有固定版本的介面 app。grafana 是 X1 非 SUT 服務、不進 snapshot，
    背景安裝發生在暖機期間，對方法看到的資料沒有可量測的影響。Pilot 期間同一個 image 應該也有這個背景安裝（推測，Pilot 沒有保存 grafana 的 log，未驗證）。
  - 若要連背景安裝也關掉（Grafana 的 `[plugins]` preinstall 停用設定），是另一個 overlay 設定、需要新的 decision、重算 lock 與再一次 soak；
    目前沒有證據顯示它造成任何無效 run，**不做**，列為使用者可選的後續（NEXT A0）。
  - **使用者決定（2026-10-10）**：使用者「照建議」（decision 029「使用者決定（2026-10-10）：照建議」第 8 項）：背景安裝器**維持現狀**，
    不加 overlay、不重算 lock、不再跑 soak；soak #6 的 lock（`sha256:1e749f67…`）就是 held-out 要凍結的 lock。之後要改仍只能在 freeze 之前另寫 decision。
