# SYNTHETIC sample — 合成範例，不是收集到的 incident

本目錄每個檔案都由 `collect.sample` 從程式產生（decision 027），沒有任何真實環境、flagd 或流量產生器參與；
在這裡算出的任何數字都**不是結果**。真實 incident 的 snapshot 與 ground truth 只在 `data/external/`，永遠不進 git。

- `incidents/INC-000/normalized/`：Agent 與 baseline 唯一可讀的 canonical snapshot（ctel/1），由專案真正的 normalize
  處理產生的 raw OTLP JSON 得到；28 分鐘時間窗，00:12–00:22 payment 的 Charge 全部失敗（模仿 paymentFailure 100%）。
- `ground_truth/`：label（catalog，decision 016 的登錄項目）、injection、normalize report；與 snapshot 物理隔離。
- `predictions/stat-anomaly/INC-000.json`：統計 baseline 在本範例上的預測（latency_s 設為 null，因為它不可重現）。
- `sample.json`：`synthetic: true`，列出每個檔案的 sha256。`next_id` 從 001 開始，不會把 `INC-000` / `RG-000` 分配給收集到的
  run group 或 incident；但 `collect calibrate` 也把 soak 的 snapshot（沒有 fault、不屬於任何 set）寫成 `INC-000`，所以 id 本身不代表合成，
  合成由本目錄、`sample.json`、2000-01-01 的時間窗與 resource 上的 `synthetic-sample` 標記表明。

只有 agent 可讀的 `normalized/` 與 ground truth 的一部分（injection、catalog label、normalize report）；正式 incident 另有的
`manifest.json`、`run.json` 與 harness 取樣、`label.reviewed.json` / `label_review.json`、`leakage_audit.json`、evidence gold 這裡都沒有
（demo 在記憶體裡跑 leakage audit，不寫檔）。

重新產生（測試會比對每個 byte）：`uv run python -m collect sample --out data/samples/synthetic --replace`
2 分鐘 demo：`uv run python -m eval demo`
