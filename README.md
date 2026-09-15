# 每日热门论文 Top 10

每天一篇 RSS 日报，关注机器人、强化学习和通用 AI。每天北京时间 09:00 由 GitHub Actions 生成，并发布到 GitHub Pages。GitHub 的定时任务可能延迟，Inoreader 抓取也有延迟，因此不保证整点送达。无需个人电脑开机，无需付费模型 API。

## 如何阅读

在仓库 Settings → Pages 查看网址，在网址后加 `feed.xml`，将完整地址添加到 Inoreader。NewsFlash 使用同一个 Inoreader 账号刷新后即可阅读。RSS 每天只有一条，正文包含全部论文。

## 排序方法

- 数据：Hugging Face Papers 最新 100 篇与热门 100 篇，合并去重，仅保留最近 30 天发表的论文；不覆盖全部 arXiv。
- 领域：按标题、摘要、关键词识别，优先机器人和强化学习各最多 3 篇，再用剩余高分候选补齐 10 篇。跨领域论文不重复占位；最终按综合分排列。
- 分数结合 HF 热榜位置、点赞、讨论、论文年龄，以及历史快照中观测到的日均增长。
- 首次运行及新候选无增长历史时，只用当前热度与新鲜度，不虚构增长。代码仓库可能对应多篇论文，其累计 Star 仅展示。
- 同一篇论文可连续几天上榜；每日 RSS GUID 稳定，重复运行不会产生重复日报。
- 展示英文原始摘要节选、论文/PDF/代码链接；领域自动分类可能有误差，热度不代表学术质量。

详细公式见 `digest.py` 中 `rank_and_select`。数据接口文档：[Hugging Face HfApi](https://huggingface.co/docs/huggingface_hub/package_reference/hf_api#huggingface_hub.HfApi.list_daily_papers)。

## 部署与维护

在 Settings → Pages 将 Source 设为 GitHub Actions。Actions → Daily paper digest → Run workflow 可手动更新或重试。抓取失败时不覆盖已发布内容；只要次日任务运行成功即可恢复，也可手动重试。代码中的网络抓取会自动尝试三次。

`config.json` 控制领域名额、候选年龄和 RSS 保留期。只使用 Python 标准库。`state/` 仅存公开论文元数据、热度快照和日报，供每日比较与历史回看；不要在仓库中存储阅读账号、令牌或其他私人配置。GitHub Pages 只发布 `public/`。

测试：`python3 -m unittest -v`。本地生成：`python3 digest.py`。
