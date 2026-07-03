# Apify Crawler Integration — 给 Claude Code 的指令

## 项目背景

Sparki pipeline: `INITIALIZING → QUERY_PLANNING → CRAWLING → EXTRACTING → SCORING → IMAGING → COMPOSING → DONE`

爬虫处于 CRAWLING 阶段（`crawler_node` + `_crawl_query`），现有实现用 Playwright 直接爬 X.com。

## 爬虫接口契约

`_crawl_query` 返回类型：
```python
tuple[list[dict], int, str | None]
# (raw_tweets, filtered_count, error_msg)
```

每条 `raw_tweet` 的字段（定义在 `src/crawler/extraction.py` `TweetExtractor.extract_search_tweets`）：
```python
{
    "tweet_id": str,
    "tweet_url": str,          # e.g. "/user/status/123"
    "profile_url": str,        # e.g. "/username"
    "author_name": str,
    "author_screen": str,
    "short_text": str,
    "created_at": str,         # ISO datetime
    "favorite_count": int,
    "retweet_count": int,
    "reply_count": int,
    "view_count": int,
}
```

## 目标

在 `src/crawler/` 下新建 `apify.py`，实现 `ApifyCrawler` 类，满足上述接口，供 `_crawl_query` 调用。

## 指令

### 1. 阅读文档理解项目
- `docs/01_PRD.md` — 了解 pipeline 目的
- `src/crawler/extraction.py` — 理解 tweet 数据格式（上方接口契约）
- `src/agent/nodes.py` 第 470-600 行 — `_crawl_query` 如何被调用、返回什么

### 2. 阅读 Apify 文档，理解 API
- Actor 文档：如何启动、传参、拿结果
- 确认返回的 tweet 数据字段和上方契约的对齐方式

### 3. 实现 `src/crawler/apify.py`
```python
class ApifyCrawler:
    def __init__(self, actor_id: str, api_token: str, config: CrawlerConfig): ...
    async def crawl(self, query: str) -> list[dict]:  # 返回上方契约格式
```

### 4. 修改 `_crawl_query`（`nodes.py` 第 470 行附近）
在函数开头根据配置选择用 BrowserManager 还是 ApifyCrawler：
```python
if use_apify:
    from src.crawler.apify import ApifyCrawler
    # 用 ApifyCrawler.crawl(query) 替代 BrowserManager 方案
else:
    from src.crawler import BrowserManager
    # 现有 Playwright 逻辑
```

### 5. 加配置项（`configs/crawler.yaml`）
```yaml
crawler:
  type: "browser"  # 或 "apify"
  apify:
    actor_id: "your-actor-id"
    api_token: "your-token"  # 或从环境变量 APIFY_API_TOKEN 读
```

### 6. 最小验证
- 单独测试 `ApifyCrawler.crawl("veo prompt")` 返回的 dict 格式正确
- 确认字段数和字段名与 extraction.py 的契约一致
