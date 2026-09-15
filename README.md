# 每日热门论文 Top 10

每天一篇 RSS 日报，关注机器人、强化学习和通用 AI。每天北京时间 09:00 由 GitHub Actions 生成，并发布到 GitHub Pages。GitHub 的定时任务可能延迟，Inoreader 抓取也有延迟，因此不保证整点送达。无需个人电脑开机，无需付费模型 API。

## 如何阅读

在仓库 Settings → Pages 查看网址，在网址后加 `feed.xml`，将完整地址添加到 Inoreader。NewsFlash 使用同一个 Inoreader 账号刷新后即可阅读。RSS 每天只有一条，正文包含全部论文。

## Zotero 个性化接入

已接入 zotero-arxiv-daily 的核心加权摘要相似度算法，适配为 RSS，继续使用现有订阅地址。来源与改动见 `THIRD_PARTY_NOTICES.md`。

- `ZOTERO_KEY`：在 GitHub Actions Secrets 保存只读 Zotero API Key，用户 ID 自动从官方接口识别。
- 可选 `ZOTERO_ID`：用于核对身份；可选 `ZOTERO_COLLECTIONS`：逗号分隔的收藏夹名称或 key，包含子收藏夹。未指定时使用整个文献库中最新 500 条有摘要的论文。
- 模型为 `sentence-transformers/all-MiniLM-L6-v2`，在 GitHub runner 上使用 CPU 计算，不调用付费嵌入或大模型 API。
- 合并 arXiv 的 cs.RO、cs.LG、cs.AI、cs.CV 新论文与 HF 候选，排除本次参考文献中已收藏的 arXiv ID/同名论文。
- 综合分 = 10 ×（0.65 × 摘要相关性 + 0.35 × 归一化热度分），其中热度归一化为 h/(h+3)。相似度不是概率。原有领域名额仍保留。
- 新收藏的摘要权重更高：第 i 条的权重正比于 1/(1+log10(i+1))，i 从 0 开始。
- Zotero 库内容和嵌入仅在内存中使用，不写进代码、缓存、日志或公开输出；公开日报会包含候选论文的相关性分数。密钥只通过请求头发送到 api.zotero.org。
- Zotero/arXiv/模型不可用时退回可用的热度候选，并在日报中说明。手动运行会先验证 Zotero 配置；定时运行允许自动降级。
- Actions → Run workflow 勾选 regenerate 可更新当天日报，仍保持一个稳定的 RSS GUID。Inoreader 更新已有文章可能有延迟。

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

`config.json` 控制领域名额、候选年龄和 RSS 保留期。基础热度生成器使用 Python 标准库；个性化模块依赖 CPU PyTorch 和 sentence-transformers。`state/` 仅存公开论文元数据、热度快照和日报，供每日比较与历史回看；不要在仓库中存储阅读账号、令牌或其他私人配置。GitHub Pages 只发布 `public/`。

测试：`python3 -m unittest -v`。本地生成：`python3 digest.py`。

## License

AGPL-3.0，见 LICENSE 与 THIRD_PARTY_NOTICES.md。
