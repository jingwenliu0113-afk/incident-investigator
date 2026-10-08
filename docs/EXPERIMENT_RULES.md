# Incident Investigator 實驗規範

## 實驗前

- 先寫 hypothesis。
- 先固定 dataset split。
- 先固定 metrics。
- 先固定 tool / retrieval / token budget。
- ground truth 與 Agent 可讀資料分離。

## 資料

- 完整 telemetry 不進 Git。
- manifest 記錄 checksum。
- Pilot Set 不得進 final test。
- 同 run_group 不得跨 split。

## 執行

- 記錄 git commit。
- 記錄 OTel Demo 版本與 image digest。
- 記錄 traffic profile、seed、fault window。
- baseline 與 Agent 必須讀同一份 frozen snapshot。

## 報告

- 不只報 overall accuracy。
- 分層報 injected fault / origin / affected / symptom。
- evidence existence 與 relevance 分開。
- gold relevance 與 weak-label score 分開。
- 報工具呼叫、token、latency、cost。
- 報失敗模式與 confidence interval。
