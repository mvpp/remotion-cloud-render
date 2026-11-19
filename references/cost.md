# 100 美元额度能出多少片

单价和额度条件在 2026 年 11 月 19 日从 Google 官方页面核对。Google 改价或改权益很常见，用之前点开出处再看一眼。

## 额度是怎么回事

Google 在 2026 年 1 月把 Google Developer Program 的 premium 权益并进了 AI Pro 和 AI Ultra 订阅，不另收钱，其中一项是每月的 Google Cloud 额度。现在三档的数额是：

| 订阅 | 每月 Cloud 额度 |
|---|---|
| Google AI Pro | 10 美元 |
| Google AI Ultra 5x | 40 美元 |
| Google AI Ultra 20x | 100 美元 |

早期文章说「Ultra 每月 100 美元」，那时还没有 5x 和 20x 两档，现在 100 美元只对应 20x。单独的 Developer Program premium 订阅已经停止新开。

几条使用条件：

- 要有 Google Developer Program 开发者资料，并和 AI 会员是同一个账号；在开发者权益页把额度领到一个 Cloud 结算账户上，可以设成每月自动入账。领取人要有结算账户的兑换权限。
- 按领取日每月发一次。每笔额度自发放起一年内有效，过期作废；官方页没有单独说「当月没用完顺延到下月」，但一年有效期意味着没用完的在一年内还能继续花。
- 能抵 Google Cloud 和 Google Maps Platform 的「符合条件的产品」，官方举例有 Gemini API、AI Studio、Firebase、Vertex AI、Cloud Run。不能抵的看 Google 的折扣排除清单（cloud.google.com/skus/exclusions），我们没逐条核。
- 额度不能和家庭组成员共享。
- 官方权益页没写要不要绑卡、超出后怎么扣钱。按 Google Cloud 结算的通常做法，建结算账户要填付款方式，额度先抵，抵不完的部分记到付款方式上。所以一定要设预算提醒，并在部署时限制最大实例数。
- 官方页没提地区限制，但订阅 AI Ultra 本身有地区要求。

出处：

- Google Developer Program 权益 FAQ：https://developers.google.com/profile/help/benefits
- Google 博客，把 premium 权益并进 AI Pro 和 Ultra：https://blog.google/innovation-and-ai/technology/developers-tools/gdp-premium-ai-pro-ultra/
- Google One 帮助，使用 AI Ultra 权益：https://support.google.com/googleone/answer/16286513

## 单价

渲染服务部署出来是 Cloud Run「请求计费」模式（只在处理请求时收 CPU 钱，`run.googleapis.com/cpu-throttling=true`），us-central1 牌价：

| 项目 | 单价 | 每月免费 |
|---|---|---|
| Cloud Run CPU | 0.000024 美元 / vCPU 秒 | 18 万 vCPU 秒 |
| Cloud Run 内存 | 0.0000025 美元 / GiB 秒 | 36 万 GiB 秒 |
| Cloud Run 请求 | 0.40 美元 / 百万次 | 200 万次 |
| Workflows 内部步骤 | 按千步计 | 5,000 步 |
| Artifact Registry 存储 | 约 0.10 美元 / GB·月 | 0.5 GB |
| Cloud Storage 标准存储 | 约 0.02 美元 / GB·月 | — |
| Cloud Build（e2-standard-2） | 0.006 美元 / 分钟 | 2,500 分钟 |
| 下载流量到中国大陆 | 0.23 美元 / GB | — |
| 下载流量到亚洲其他地区（含香港）和全球 | 0.12 美元 / GB | — |

出处：cloud.google.com 的 run/pricing、workflows/pricing、artifact-registry/pricing、storage/pricing、build/pricing。

一台 4 vCPU、16 GiB 的渲染机跑一秒是 4×0.000024 + 16×0.0000025 = 0.000136 美元，一小时约 0.49 美元。每月的免费量按牌价约值 5 美元（内存那项先用完，大约 6 个机时），这部分不计在下面的推算里，当作余量。

上传工程到云上不收流量费。下载成品按你下载时出口 IP 所在地计费：直连国内按 0.23 美元/GB，走香港或海外代理按 0.12 美元/GB。

## 固定开销

- 镜像约 1.8 GB，扣掉 0.5 GB 免费，每月约 0.13 美元。
- 渲染桶里的文件 7 天自动删，一条 500 MB 的成片放 7 天不到 0.003 美元，可以忽略。
- Cloud Build 只在升级版本时跑一次，10 分钟左右，在免费分钟内。
- Workflows 一条片子几十步，在免费额度内。

合计每月约 0.15 美元，不管渲不渲都要付。

## 推算

以实测为准（见 [results.md](results.md)）：1080p 30fps high 档，11 分钟整条 0.89 美元，每分钟成片 0.079 美元；同一段 4K 是 1080p 的 3 倍。1080p high 档每分钟成片约 44 MB，4K 约 150 MB。

每分钟成片的全部成本（下载按直连国内的 0.23 美元/GB 算，偏保守）：

| | 渲染 | 下载 | 合计 |
|---|---|---|---|
| 1080p 30fps | 0.079 美元 | 0.010 美元 | 约 0.09 美元 |
| 4K 30fps | 约 0.24 美元 | 0.035 美元 | 约 0.27 美元 |

100 美元扣掉 0.15 美元固定开销，约 99.8 美元可用：

| 规格 | 每条成本 | 每月约能渲 |
|---|---|---|
| 1080p，1 分钟短片 | 0.07–0.11 美元 | 900–1,400 条 |
| 1080p，10 分钟长片 | 约 0.9 美元 | 约 110 条（约 1,100 分钟） |
| 4K，1 分钟短片 | 0.23–0.34 美元 | 290–430 条 |
| 4K，10 分钟长片 | 约 2.7 美元 | 约 37 条 |

短片给了一个范围，因为短片的冷启动和分块固定开销占比高，我们测的 23 秒小段两次分别是每分钟 0.064 和 0.10 美元。

换成别的档：Ultra 5x 的 40 美元乘 0.4，1080p 约 440 分钟；AI Pro 的 10 美元乘 0.1，1080p 约 110 分钟。

## 哪些地方不确定

- 每分钟 0.08 美元是一期片子的实测，画面复杂度不同单价会变。大面积模糊、粒子、WebGL 在软件渲染下很慢，可能贵几倍。最准的办法是拿自己的片子渲 20 秒，看 `--json` 里的费用乘时长。
- 4K 的 3 倍只测了一个 23 秒的小段，整条 4K 没跑过。60fps 帧数翻倍，费用大约也翻倍，没实测。
- 费用是 HyperFrames 按牌价算的，没扣免费额度，也没计入冷启动之外的实例空转。正式账单还没核对，核过再更新。
- 额度能不能抵 Cloud Run 以外的某个具体 SKU，要看 Google 的排除清单。
- 额度和 Gemini API、AI Studio 共用一个池子，其他地方花了，渲染能用的就少。
