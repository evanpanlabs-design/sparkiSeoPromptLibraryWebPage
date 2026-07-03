# Apify 整合方案

## 现状

`CrawlerConfig` 已扩展了 Apify 字段（main.py 已读入 `type`、`apify_*`）。`src/crawler/apify.py` 待实现。

---

## 需要改的地方

### 1. `src/crawler/apify.py`（新建）

实现 `ApifyCrawler` 类，对外接口：

```python
class ApifyCrawler:
    def __init__(
        self,
        actor_id: str,
        api_token: str,
        timeout_ms: int = 120_000,
        max_retries: int = 2,
        retry_delay_s: int = 30,
    ): ...

    async def crawl(self, query: str, max_cost_usd: float = 0.05) -> list[dict]:
        """调用 Apify Actor，返回 tweet dict 列表（格式同 extraction.py）"""
```

Apify API 调用方式（来自文档）：
- `POST https://api.apify.com/v2/acts/{actor_id}/runs`
- Body: `{"searchTerms": [query], "tweetsDesired": 100, "maxTweetsPerQuery": 100}`
- 或通过 `apify-client` SDK
- 完成后 `GET https://api.apify.com/v2/acts/{actor_id}/runs/{runId}/dataset/items` 取数据

关键：Actor 返回的字段需要映射到 `Tweet` 格式。

---

### 2. `src/agent/nodes.py` 的 `_crawl_query`

在函数开头分支：

```python
if cfg.type == "apify":
    from src.crawler.apify import ApifyCrawler
    import os
    token = os.environ.get(cfg.apify_api_token_env, "")
    crawler = ApifyCrawler(
        actor_id=cfg.apify_actor_id,
        api_token=token,
        timeout_ms=cfg.apify_timeout_ms,
        max_retries=cfg.apify_max_retries,
        retry_delay_s=cfg.apify_retry_delay_s,
    )
    raw_tweets = asyncio.run(crawler.crawl(query, max_cost_usd=cfg.apify_max_cost_usd))
    # 不需要 enrichment — Apify 数据已包含所有字段
    # 直接进过滤阶段
else:
    # 现有 Playwright 路径
    from src.crawler import BrowserManager, scroll_and_extract, enrich_tweet
    ...
```

---

### 3. 需要确认：Apify 能否拿到完整长文本？

根据之前测试，Apify 返回 `short_text` 但可能缺长文本。需要在 `apify.py` 里验证：
- 如果 Apify 返回的 `text` 就是完整文本 → 直接用
- 如果缺长文本 → 仍需 `enrich_tweet` 单独访问详情页拿长文本

方案：先用 Apify 数据进 pipeline 试跑，看 worker_node 拿到的文本够不够用。

---

### 4. 文档更新（过时的部分）

| 文档 | 需要更新 | 说明 |
|------|---------|------|
| `docs/01_PRD.md` §2.1 F2 | ⚠️ 重大更新 | "Playwright-based" 改为"Playwright/Apify 双引擎" |
| `docs/02_DevGuide.md` §2.1 | ⚠️ 系统图更新 | Crawler Node 说明 |
| `docs/02_DevGuide.md` §3.2 | ⚠️ crawler.yaml 示例更新 | 加 `type: apify` 配置示例 |
| `docs/03_InterfaceContract.md` §5.4 | ⚠️ 注释更新 | `author_enriched=True` 对 Apify 不适用 |
| `docs/08_ApifyIntegration.md` | ✅ 已是最新 | 无需改动 |

---

### 5. 成本控制

- `apify_max_cost_usd` 已在 `CrawlerConfig` 里（默认值 1.0）
- 每个 query 消耗约 `$0.05`（125 tweets）到 `$1.0`（2000 tweets）
- 5 个 query 全部用 `$1.0` 约 `$5`

建议默认值：先用 `$0.10` 测试（~200 tweets/query），确认数据够用后再加大。

---

### 6. 待新 Claude Code 窗口实现的具体步骤

**Step 1**: 实现 `src/crawler/apify.py`
- 参考 `docs/08_ApifyIntegration.md` 的 API 说明
- 参考 `src/crawler/extraction.py` 的字段映射方式
- 先写一个最小测试：`asyncio.run(crawler.crawl("veo prompt", max_cost_usd=0.05))` 确认返回数据

**Step 2**: 写一个独立测试脚本 `test_apify_tweets.py`
- 调用 ApifyCrawler，抓 5 条 tweet
- 打印返回的 dict，确认字段和 extraction.py 的契约对齐
- 对比 `Tweet` dataclass 的字段

**Step 3**: 修改 `nodes.py` 的 `_crawl_query`
- 在函数开头加 `if cfg.type == "apify"` 分支
- Apify 路径：调用 crawler，直接返回结果，跳过 enrichment

**Step 4**: 改配置 `configs/crawler.yaml`
```yaml
crawler:
  type: "apify"
  apify:
    max_cost_usd: 0.10   # 先用小预算测试
```

**Step 5**: 跑 `python -m src.main run --all`，看 Apify 路径完整跑通
