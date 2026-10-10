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
