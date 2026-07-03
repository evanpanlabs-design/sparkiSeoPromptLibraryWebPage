# 04 — sync_images_from_gcs.py

**状态：** ✅ Verified

**调用方式：** 直接 Python 执行

```bash
python scripts/sync_images_from_gcs.py
python scripts/sync_images_from_gcs.py --dry-run   # 预览不下载
python scripts/sync_images_from_gcs.py --limit 10  # 只下载前10张
```

---

## 调用方法

```python
import sys
sys.path.insert(0, '.')

# 返回 dict: {downloaded, skipped, errors, total_gcs_blobs}
from scripts.sync_images_from_gcs import download_all

stats = download_all(dry_run=False, limit=None)
print(stats)
# {'downloaded': 114, 'skipped': 0, 'errors': 0, 'total_gcs_blobs': 114}
```

---

## 功能

从 GCS `gs://sparki-op-test/prompts/` 下载所有图片到本地：

```
outputs/images/
├── cinematic/2026-05/{prompt_id}.png
├── video-generation/2026-05/{prompt_id}.png
├── other/2026-05/{prompt_id}.png
└── ...
```

路径结构：`outputs/images/{category}/{yyyy-mm}/{prompt_id}.png`

---

## 去重逻辑

- 如果本地文件已存在且大小与 GCS 一致 → 跳过（不重复下载）
- 如果大小不同 → 重新下载覆盖

---

## GCS 路径映射

| GCS blob | 本地路径 |
|----------|----------|
| `gs://sparki-op-test/prompts/38.png` | `outputs/images/other/2026-05/38.png` |
| `gs://sparki-op-test/prompts/2056672624747647050.png` | `outputs/images/other/2026-05/2056672624747647050.png` |

（当前所有图都放在 `other/`，category 映射待完善）

---

## 验证结果

```
find outputs/images -name "*.png" | wc -l
→ 77  (第一批下载完成)
→ 114 (当前 GCS 总 blob 数)
```

---

## 文档历史

| 日期 | 操作 | 结果 |
|------|------|------|
| 2026-05-21 | 测试 --dry-run + --limit 5 | ✅ 下载成功 |