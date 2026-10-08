# Incident Investigator SPEC

## 一句話問題

LLM Agent 能不能可靠地做 production 根因分析，而且勝過合理的 baseline？

## 研究核心

這題不是做一個「會看 log 的 chatbot」。  
真正要回答的是：

- Agent 是否比統計規則與非 Agent baseline 更準？
- Agent 引用的 evidence 是否真的支持結論？
- 成本、工具呼叫次數、延遲是否合理？
- Agent 失敗時，問題來自 telemetry 不足，還是推理與資訊取得路徑本身？

---

# Core

## 1. 鎖定 OpenTelemetry Demo 版本

必須記錄：

- git commit / release tag
- Docker image digest
- 啟動參數
- traffic generator 設定
- fault config
- random seed
- 收集時間窗

如果 Mac 上的 image 缺少 arm64 支援，可以改用 RTX 桌機收集，但 manifest 必須記錄實際機器。

## 2. Frozen Incident Snapshot

Agent 與所有 baseline 不直接讀 live system。

流程：

```text
Normal period
→ fault on
→ traffic
→ fault off
→ export raw telemetry
→ normalize
→ frozen canonical snapshot
```

目錄建議：

```text
data/
├── samples/              # 可進 git 的縮小範例
└── external/             # gitignore
    └── incidents/
        └── INC-001/
            ├── raw/
            ├── normalized/
            └── manifest.json
```

完整 telemetry 不進 Git。

manifest 必須包含 checksum。

## 3. Ground Truth

Ground truth 與 Agent 可讀資料物理隔離。

建議 label：

- incident_id
- run_group_id
- fault_family
- injected_fault
- origin_service
- affected_services
- user_symptom
- fault_start
- fault_end
- traffic_profile
- seed
- telemetry_coverage

同一次故障執行切出的多個時間窗不得跨 split。

split 最小單位使用 `run_group_id`。

## 4. Canonical Telemetry Schema

Raw export 與 canonical representation 分開。

所有 baseline 與 Agent 只依賴 canonical schema。

至少需要：

- logs
- metrics
- traces

Raw data 只用於 provenance 與重新 normalize。

## 5. Pilot Set

第一批約 10 個 incident 只叫 **Pilot Set**。

用途：

- 驗證 pipeline
- 驗證 label
- leakage audit
- baseline 難度檢查

Pilot Set 永遠不進 final test。

## 6. Leakage Audit

至少測：

- grep fault 名稱
- grep service 名稱
- obvious error messages
- fault flag metadata
- 文件中直接洩漏答案的描述

必要時將 incident 分成 Easy / Medium / Hard。

## 7. Baselines

至少四組：

1. Dump-all telemetry + LLM
2. Retrieval + LLM
3. 統計規則 baseline
   - per-service anomaly score
   - 後續可加入 dependency graph
4. Agent + tools

每組都報：

- 可見資料範圍
- retrieval budget
- tool-call budget
- token budget
- latency
- cost

避免 Agent 因為「看了更多資料」而不公平勝出。

## 8. 分層評分

至少分開評：

- injected fault
- origin service
- affected services
- user symptom

不要壓成單一 root_cause string。

## 9. Evidence Validation

分兩層：

### Existence
引用的 log / trace / metric 是否真的存在。

### Relevance
不要直接把「故障服務 + 故障時間窗」視為 gold evidence。

做法：

- 自動建立 candidate evidence pool。
- 用弱標籤表示 temporal / service relevance。
- 人工標註一部分 gold evidence。
- 報告時把「gold subset relevance」與「weak-label score」分開列。

## 10. Held-out Evaluation

- Pilot Set 不得進 test。
- 同 run_group 不得跨 split。
- 失敗分類必須是正式產出。
- 最終報告需要 confidence interval 或 bootstrap。

---

# Advanced

## Diagnostic Trajectory Failure Localization

唯讀階段測的是「推理 / 資訊取得路徑敏感度」，不是 environment state transition。

對失敗 trajectory 的每個 checkpoint：

- 重建完全相同的 Agent context。
- 從該 checkpoint 重新 rollout。
- 估計 `P(correct diagnosis | checkpoint)`。

取樣策略：

1. 先少量 rollout 掃過整條 trajectory。
2. 在疑似變化區域加密取樣。

目標不是強迫找出單一 fatal step，而是估計 recoverability。

可能結果：

- cliff / abrupt collapse
- gradual drift

可能失敗類型：

- early anchoring
- premature stopping
- wrong tool selection
- confirmation bias
- failure to revisit hypothesis

---

# Optional

- 文件 RAG，但排除直接描述 fault flag 答案的文件。
- 多重故障與 distractors。
- Human approval → remediation → verify recovery。
- 若 Agent Gym 也實作，可比較 readonly diagnosis 與 state-changing task 的 failure structure。

---

# 不做什麼

- 不做通用 Agent framework。
- 不做 observability 產品 UI。
- 不以修復自動化作為 Core 完成條件。

---

# GitHub 最終成果

README 首屏應包含：

- baseline 比較表
- 2 分鐘 demo
- dataset schema
- failure taxonomy

若進 Advanced：

- recoverability curve
- failure localization 分析

---

# Repo 建議結構

```text
incident-investigator/
├── CLAUDE.md
├── SPEC.md
├── NEXT.md
├── env/
├── collect/
├── baselines/
├── agent/
├── eval/
├── schemas/
├── samples/
├── tests/
├── tools/
│   └── with-mac-lock
└── docs/
    ├── EXPERIMENT_RULES.md
    └── decisions/
```

---

# Day 1

1. 鎖定 OTel Demo 版本。
2. 建立 label schema。
3. 建立 manifest schema。
4. 建立 canonical telemetry schema。
5. 完成人工收集 1 個 incident。
6. 驗證刪掉 live system 後仍能只靠 snapshot 分析。

---

# Week 1

目標不是 Agent accuracy。

目標是證明：

> 我們可以製造、凍結、標註並重播一個可信的 incident。

Week 1 產出：

- 約 10 個 Pilot incidents。
- 自動化 collect → normalize → label 流程。
- 第一輪 leakage audit。
- 第一個 simple statistical baseline。
- 第一張 baseline 結果表。

---

# Gate

## 進 Advanced

- Agent 在 held-out 明顯勝過最強統計規則 baseline。
- 有一批可重現的穩定失敗案例。
- 錯誤主要來自推理路徑，不是 telemetry 不足。

## 收尾或改題

- 失敗主要來自 telemetry coverage 不足：完成 failure taxonomy 後收尾。
- Agent 幾乎全對：先加難度，不直接進 Advanced。
