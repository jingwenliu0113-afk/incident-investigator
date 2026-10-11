# Mac Heavy Lock

這個資料夾的 `with-mac-lock` 用來避免不同 Project 同時執行會互相污染結果的 Mac heavy workload。

## 使用方式

```bash
./tools/with-mac-lock <command> [args...]
```

## 不需要鎖的工作

- 寫 code
- unit tests
- correctness tests
- 文件
- 小型 smoke tests

## 需要鎖的工作

依 `MACHINE_POLICY.md` 定義。

不要自行刪除其他 session 建立的 lock。

## 本機模型（decision 029）

`with-local-ollama` 讓本機 Ollama server 與載入的模型只在一次 heavy lock 的期間存在：檢查 lock、拒絕已經在跑的 server、
以固定的環境啟動只綁 loopback 的 `ollama serve`、執行指令、一定停掉 server。

```bash
./tools/with-mac-lock ./tools/with-local-ollama <command> [args...]
```

## 遠端推論：RTX 5070 Ti 桌機（decision 029 修訂 1）

`with-remote-ollama` 讓 LLM 方法的模型呼叫在使用者的 RTX 5070 Ti 桌機上執行，eval 本身留在 Mac：
只用既有的 alias `ssh gpu-server` 開一個 session，同時把 Mac 的 `127.0.0.1:11434` 轉送到桌機的 `127.0.0.1:11434`，
並在 WSL Ubuntu-22.04 裡以共用的 GPU lock（`flock -n /tmp/ai-portfolio-gpu.lock`）啟動 Ollama 0.35.0（`~/opt/ollama-0.35.0`，
只給本 project 的 models 目錄 `~/ii-ollama-models`）；等 server 回應後以 `II_INFERENCE_HOST=gpu-server` 執行指令，結束時只停止自己啟動的 server。
不需要 Mac heavy lock（Mac 只跑輕量的 eval 迴圈）。

```bash
./tools/with-remote-ollama <command> [args...]
```

- exit 75：GPU lock 被其他工作占用（不等、不搶、不刪 lock，之後再跑）；exit 3：本機或桌機的 11434 已經有程式在聽（不使用也不停止它）、
  `ssh gpu-server` 失敗（離線 → LLM 步驟標記 blocked）、server 沒有回應，或結束時無法確認遠端 server 已停止（印出檢查指令）；其他：指令自己的 exit code。
- `ollama.host` 是 `local` 時仍用 `./tools/with-mac-lock ./tools/with-local-ollama <command>`。
