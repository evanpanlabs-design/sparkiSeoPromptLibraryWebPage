# 01 — ApifyCrawler.crawl()

**状态：** ✅ Verified（爬取进行中）

**调用位置：** `src/crawler/apify.py` → `ApifyCrawler.crawl(query, max_cost_usd)`

---

## 调用方法

```python
import asyncio
import os
from dotenv import load_dotenv

PROJECT_ROOT = "e:/2027_GET_A_JOB/Get_An_AI_Job/视界Sparki/16_NewCrawler"
load_dotenv(PROJECT_ROOT + "/.env")

from src.crawler.apify import ApifyCrawler

async def crawl_veo_prompts():
    crawler = ApifyCrawler(
        actor_id="nfp1fpt5gUlBwPcor",  # apify twitter-scraper-lite
        api_token=os.environ.get("APIFY_API_TOKEN", ""),
        timeout_ms=600000,   # 10 min
        max_retries=2,
    )

    queries = [
        "Veo prompt",
        "Gemini video prompt",
        "AI video generation prompt",
        "cinematic video prompt",
    ]

    all_tweets = []
    for query in queries:
        print(f"Starting: {query}")
        tweets = await crawler.crawl(query, max_cost_usd=10.0)
        print(f"  → {len(tweets)} tweets")
        all_tweets.extend(tweets)

    return all_tweets

tweets = asyncio.run(crawl_veo_prompts())
print(f"Total: {len(tweets)} tweets")
```

---

## 保存到 last_crawl.json

```python
import json
from pathlib import Path

cache = {"prompt: cinematic": tweets}  # 按 query key 组织

with open("outputs/last_crawl.json", "w", encoding="utf-8") as f:
    json.dump(cache, f, ensure_ascii=False, indent=2)

print(f"Saved {len(tweets)} tweets to outputs/last_crawl.json")
```

---

## 参数说明

| 参数 | 类型 | 默认值 | 说明 |
|------|------|--------|------|
| `query` | str | 必填 | X.com 搜索关键词 |
| `max_cost_usd` | float | 10.0 | 每次查询最大花费（$10≈200条推文） |
| `timeout_ms` | int | 600000 | 超时时间（10分钟） |
| `max_retries` | int | 2 | 失败重试次数 |

---

## 返回值

```python
list[dict]  # 每个 dict 格式：
{
    "tweet_id": "2057010211659903201",
    "url": "https://x.com/user/status/2057010211659903201",
    "text": "Full tweet text...",
    "short_text": "...",
    "author": {
        "name": "Display Name",
        "screen_name": "username",
        "profile_url": "https://x.com/username",
        "followers_count": 1234,
    },
    "favorite_count": 50,
    "retweet_count": 10,
    "reply_count": 5,
    "view_count": 1000,
    "created_at": "2026-05-21T07:39:50Z",
}
```

---

## 注意事项

1. **async 函数** — 必须用 `asyncio.run()` 或在 async context 里调用
2. **.env 必须加载** — `load_dotenv(PROJECT_ROOT + '/.env')` 否则 `APIFY_API_TOKEN` 为空
3. **输出格式** — `last_crawl.json` 结构是 `{"query_key": [tweets...]}`，多个 query 会覆盖（建议每次单 query）
4. **成本控制** — `$10/查询` 是当前配置，实际消耗可在 Apify dashboard 查看

---

## 当前运行状态

```
Cmd: python scripts/run_master.py
Query: "Veo prompt"
Budget: $10
Status: 正在爬取（127+ pages，~2540条推文）
Started: 2026-05-21 15:39 UTC
```

---

## 文档历史

| 日期 | 操作 | 结果 |
|------|------|------|
| 2026-05-21 | 测试调用（$10 budget） | ✅ 爬取成功，进行中 |