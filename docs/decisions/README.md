# Decision Logs

只有會影響架構、資料格式、評測協定、benchmark 公平性或研究問題的決策才需要寫 decision log。

命名建議：

```text
001-xxxx.md
002-xxxx.md
```

編號 **100 保留**給 held-out 的最終結果 `100-heldout-final-results.md`（decision 030：held-out 評測完成後才新增、寫一次；README 在 freeze 封存）。
一般的 decision 從 031 依序用到 099。

每篇至少包含：

- 背景
- 決策
- 為什麼
- 放棄的替代方案
- 對實驗的影響
