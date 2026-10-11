# MACHINE_POLICY

## 核心原則

**本 Project 一律以 Mac 作為主要開發環境。**

Claude Code session 在 Mac 啟動。RTX 5070 Ti 桌機只是一台按需遠端算力 worker，不得自行把主要開發搬過去。

## Mac 上負責

- OTel Demo 與 incident pipeline
- telemetry normalize
- baseline / Agent
- evaluation
- 文件與分析

## Mac Heavy Lock

正式 incident collection 可能明顯影響 CPU / RAM / Docker，因此正式收集必須透過：

```bash
./tools/with-mac-lock <正式收集命令>
```

例如：

```bash
./tools/with-mac-lock uv run python -m collect run --set pilot --flag <flag> --variant <variant>   # e.g. --flag paymentFailure --variant 100%
```

`with-mac-lock` 會：

1. 原子性取得 `/tmp/ai-portfolio-mac-heavy.lock`。
2. 記錄目前 lock 的 PID、開始時間、工作目錄與命令。
3. 執行指定工作。
4. 無論工作成功、失敗或被中斷，盡可能自動釋放 lock。

如果 lock 已被其他 Project 取得：

- 正式 incident collection 不得開始。
- 不得手動刪除 lock 來搶資源。
- 可以繼續寫 code、unit test、schema、normalizer、分析。
- 若懷疑是 stale lock，回報使用者處理，不得自行清除。

一般開發工作不需要使用這個 wrapper。

## Mac Docker Desktop（Core 階段，2026-10-08 起）

在目前 Core 階段，Mac 的 Docker Desktop 視為 Incident Investigator 專用資源。
其他 Portfolio Project 不應在 Mac 上啟動、停止、重啟、prune 或修改 Docker workload。

本 Project 可以正常使用 Docker Desktop，但仍需遵守：

- 上面的 Mac Heavy Lock 規則不變：正式 collection 仍需透過 `with-mac-lock`，並在 stack 整個存活期間持有 lock。
- 不得執行全域 `docker system prune`、`docker volume prune`、`docker network prune`、`docker image prune`，除非使用者明確要求。
- 不得刪除不屬於本 Project 的 container / image / volume / network。
  本 Project 的資源是：compose project `ii-otel-demo`（label `com.docker.compose.project=ii-otel-demo`）的 container / volume / network、
  掛在這些 container 上的 anonymous volume（由 image 的 `VOLUME` 自動建立，**沒有** compose label；以 `docker inspect` 的 Mounts 判斷，
  由 `python -m env compose down --volumes` 移除）、`env/otel-demo.lock.json` 鎖定的 image，以及本 Project session 為診斷而自行建立、並記錄在案的暫時資源。
  其他一律視為不屬於本 Project；來源不明、沒有掛載的 anonymous volume 由使用者決定，不得自行刪除。
- 為診斷建立暫時 container 時用 `docker run --rm` 或 `docker rm -v`，避免留下 anonymous volume。
- `docker compose down` 只能針對本 Project 自己的 compose stack，一律透過 `uv run python -m env compose down …`（固定 `--project-name ii-otel-demo` 與鎖定的 compose 檔）。
- 若 Docker Desktop 本身需要 restart，先在 `NEXT.md` 記錄原因，避免把其他可能存在的 workload 當成自己的資源。
- 調查 Docker 問題（OOM、mapping conflict、資源不足…）時，先依本 Project 實際蒐集到的證據歸因，不得在沒有證據時歸因於其他 Project。

## 遠端 GPU

Core 原則上不需要 RTX。

只有 Mac arm64 無法合理執行鎖定的 OTel stack，或使用者明確要求時，才考慮遠端。

遠端桌機離線時，標記 blocked 並繼續 Mac 工作。

### LLM 方法的推論（2026-10-11 起，使用者明確要求）

使用者 2026-10-11 明確要求並同意：LLM 方法（dump-all、retrieval、Agent）的**模型推論**改在 RTX 5070 Ti 桌機上執行
（Mac 的 70 W 充電器供不上高效能模式的本機推論；decision 029 修訂 1）。

- **只有模型呼叫在桌機上**：eval 迴圈、snapshot、ground truth、評分與結果都留在 Mac，不複製到桌機。
  模型呼叫經 `./tools/with-remote-ollama` 開的 SSH tunnel（Mac `127.0.0.1:11434` → 桌機 `127.0.0.1:11434`）送到 WSL Ubuntu-22.04 裡的 Ollama；
  adapter 仍然只連 loopback。這不是付費或第三方服務（「外部費用」不適用：既有的本地硬體）。
- **GPU lock**：桌機的 GPU 與使用者其他 project 共用，一律在 WSL Ubuntu-22.04 裡以 `flock -n /tmp/ai-portfolio-gpu.lock` 取得
  （經 `ssh gpu-server`；`with-remote-ollama` 會做，lock 被占用時 exit 75）。被占用 → 等之後再跑；**不得搶占、不得刪除 lock、不得停止別人的程序**。
  server 只在 lock 內存在，結束時只停止自己啟動的那一個。
- 這種遠端推論**不需要 Mac heavy lock**：Mac 只跑輕量的 eval 迴圈；重的推論在桌機上，由 GPU lock 保護。
- 只使用 Ollama 0.35.0（`~/opt/ollama-0.35.0`）與只給本 project 用的 models 目錄（`~/ii-ollama-models`），都在 WSL 使用者的 home、不需要 sudo；
  不更動桌機的其他設定或其他 project 的檔案。
- **gpu-server 離線或連不上時**：LLM 的步驟標記 blocked，繼續 Mac 上可完成的工作；不改回 Mac 推論（那是使用者的決定）。

## Credential 安全

若遠端已由使用者設定完成，只能使用預設 alias：

```bash
ssh gpu-server
```

不得要求、讀取、保存或修改 Tailscale / SSH / sudo / token credential。

## 外部費用（2026-10-08 起）

任何會產生外部費用的操作（付費 API，例如 LLM baseline / Agent 呼叫的模型 API；雲端 GPU；付費資料服務），**第一次執行前必須先停下來向使用者報告**：

- 用途；
- 預估請求數；
- 預估 token 量或運算量；
- 預估成本。

未經使用者明確批准，不得產生任何付費用量。
不受此限：已存在的本地硬體運算（Mac、遠端 RTX）、一般網路下載、Claude Code 本身的用量。
