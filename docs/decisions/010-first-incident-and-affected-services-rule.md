# 010 — 第一個 incident（Day 1 #5）的 fault 與 affected services 的判定規則

- 狀態：Accepted（2026-10-08）；在收集第一個 incident、寫任何 label 之前寫定
- 影響範圍：Pilot 的第一個 incident；label 的 `affected_services` 定義（decision 006 的補充，適用所有 incident）

## 背景

- Day 1 #5 要「完成人工收集 1 個 incident」，用途是驗證 collect → raw → normalize → label 的 pipeline（Week 1 目標：能製造、凍結、標註並重播一個可信的 incident）。
- decision 006 把 `affected_services` 定義為「telemetry 因 fault 而偏離的服務（含 origin）」，但沒有說「只是流量變少」算不算。
  以 checkout 下單流程為例（`env/upstream/opentelemetry-demo/src/checkout/main.go` PlaceOrder）：
  `prepare`（cart、product-catalog、currency、shipping 報價）→ `chargeCard`（payment）→ `shipOrder`（shipping）→ `emptyUserCart`（cart）→
  `sendOrderConfirmation`（email）→ kafka（accounting、fraud-detection）。payment 失敗時，之後的步驟都不會被呼叫。

## 決策

1. **第一個 incident 用 `paymentFailure` = `100%`**，fault 10 分鐘、recovery 5 + U(0,5) 分鐘（decision 009 與其修訂）。
   - 理由：答案最不模糊（origin 只有一個、每一筆下單都失敗），最適合驗證 pipeline；`fault_type = error_response`，`fault_family = error`。
   - payment 失敗時會把 `demo.user_context.loyalty_level` 標成 `gold`（研究筆記 §2），這是 upstream 原本就有的誤導性相關，保留不處理。
   - 這個 incident 屬於 **Pilot Set**，永遠不進 final held-out test（SPEC §5）。它只用來驗證 pipeline 與 label，不代表 Pilot 的 fault 分布。
2. **a priori label（`labeling.method = catalog`）**：
   - `origin_service = payment`；`user_symptom.kinds = ["errors"]`（下單失敗，`failed to charge card`）。
   - `affected_services = [payment, checkout, frontend, frontend-proxy]`（依下面的規則 3）。
   - 收集完成後，由人對照 frozen snapshot 檢查，改為 `catalog+review` 並填 `telemetry_coverage`（decision 006 §7）。review 若與 a priori 不同，記錄差異與理由。
3. **affected services 的判定規則（補充 decision 006，適用所有 incident）**：
   - **算 affected**：該服務**自己的** span / log / metric 在 fault 期間出現因 fault 造成的錯誤或延遲（包含 origin，以及錯誤或延遲沿呼叫鏈往上傳的服務）。
   - **不算 affected**：只因為上游某一步失敗而**沒被呼叫、流量變少**的服務（例如 payment 失敗時的 shipping `ShipOrder`、cart `EmptyCart`、email、kafka、accounting、fraud-detection）。
     這些記在 `labeling.notes`，不進 `affected_services`。
   - traffic generator（load-generator）是使用者側，它看到的現象記在 `user_symptom`，不列入 `affected_services`。
   - 理由：「流量變少」的服務數量會隨呼叫鏈長度膨脹，而且在 metrics 上不易和正常的流量變異區分；以「自己出現錯誤或延遲」為準，判定可重現，也和 SPEC §8 分層評分的用意一致。

> 規則 3 的補充（origin 以外的服務只算錯誤或延遲、OOM / 重啟算錯誤）見 decision 016 §2。

## 放棄的替代方案

- **第一個 incident 用比較難的 fault（例如 lock contention、低比例失敗）**：Day 1 的目的是驗證 pipeline，不是測難度；難度在 Pilot 與 leakage audit 再處理。
- **把流量變少的服務也算 affected**：答案集合大、邊界模糊，評分會被呼叫鏈長度主導。

## 對實驗的影響

- decision 006 的 `affected_services` 從此依規則 3 判定；在任何 label 寫成之前定案，之後不得依結果修改。
- 第一個 run group 用 `./tools/with-mac-lock uv run python -m collect run --flag paymentFailure --variant 100%`。
