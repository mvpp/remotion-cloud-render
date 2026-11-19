---
name: hf-cloud-render
description: 把 HyperFrames 视频放到自己的 Google Cloud Run 上渲染：从领 Google AI Ultra 每月送的开发者额度、建项目挂结算、设预算提醒，到建镜像、部署、渲染、下载、拆除；带工程体检、一条命令渲染和画质对比脚本，以及按实测单价算出的「100 美元额度能出多少分钟片子」。Use for 云渲染、HyperFrames 上云、cloudrun 渲染、本机渲长片内存不够、用 Google Cloud 额度渲视频、AI Ultra 开发者额度能干什么。
---

# hf-cloud-render：HyperFrames 云渲染

HyperFrames 的片子本质是网页，渲染就是开一个无头 Chrome 一帧帧截图再压成视频。这件事吃 CPU 和内存，跟显卡关系不大。一台 16 GB 的 Mac mini 渲 11 分钟的片子，交换区会一路涨过 5 GB，整台机器都卡住。HyperFrames 自带 `cloudrun` 命令，可以把同样的渲染丢到自己的 Google Cloud Run 上：片子切成几十块，10 台 4 核 16 GB 的机器同时渲，渲完自动拼好放进存储桶，空闲时一台机器都不留。

我们在 2026 年 11 月拿一期 11 分钟的 AI 讲解片实测：整条 14 分钟渲完，按 Google 牌价算 0.89 美元；同一段跟本机逐帧比，放大四倍看不出差别。Google AI Ultra 20x 会员每月送 100 美元的 Google Cloud 额度，按这个单价，1080p 一个月够渲 1,000 分钟左右的成片。

## 什么时候用

适合上云的是 HyperFrames（或任何靠 Chrome 截图出帧的）工程，尤其是这几种情况：本机内存小、片子长（5 分钟以上）、想改一处就整条重渲、要出 4K、要批量渲同一个模板的很多份、本机还要同时剪别的东西。

不适合或要先改造的：

- 用了 WebGPU 的工程。云上没有显卡，Chrome 走 SwiftShader 软件渲染，WebGPU 不可用。WebGL 能跑但慢；纯 HTML、CSS、SVG、GSAP 最合适。
- 工程里有软链接、本机绝对路径（`/Users/...`、`C:\...`、`file://`），或者依赖本机装的字体。云上只拿到你上传的那个文件夹，这些都会丢。字体要放进工程用 `@font-face` 引用。
- 一二十秒的小段、改完马上要看的试渲：本机 1 分钟就出来，上云要打包上传、冷启动、再下载，不一定更快。本机适合小段试渲、拼接、混音，整条交给云。

上云前先跑 `python3 scripts/check_project.py <工程目录>`，它会查出软链接、绝对路径、WebGPU、没打包的字体和外链资源。

## 操作逻辑

完整步骤在 [references/setup.md](references/setup.md)，标了哪些必须本人在浏览器里点。大致顺序：

1. 领额度（本人，浏览器）：订阅 Google AI Ultra，加入 Google Developer Program，在开发者权益页把每月 Cloud 额度领到一个结算账户上。
2. 建项目、挂结算、设预算提醒（本人，浏览器；预算提醒也能用命令建）。
3. 装 gcloud 和 Terraform，`gcloud auth login` 加 `gcloud auth application-default login`（会弹浏览器，本人登录）。
4. 建镜像：npm 装的 HyperFrames 命令行建不了镜像，用 `scripts/build_image.sh` 拉同版本源码交给 Cloud Build 建，约 10 分钟。
5. 部署：`hyperframes cloudrun deploy --image <镜像> --max-instances 10`，Terraform 建好 Cloud Run 服务、Workflows、存储桶和告警。
6. 渲染和下载：`scripts/cloud_render.sh <工程目录>`，一条命令体检、打包（自动解开软链接）、上云渲、下载，可选合上音轨。
7. 不用了就拆（看 setup.md 最后一节）。不拆的话空闲成本每月约 0.15 美元，只有镜像存储费。

几条踩过的坑，命令里已经处理了：

- `--max-parallel-chunks` 不能超过部署时的 `--max-instances`。不加这个参数，长片会被切成十几块同时发出去，超出的被 Cloud Run 回 429，整条失败、白跑。
- 画质档：`--quality standard` 是 x264 CRF 18，`high` 是 CRF 15，本机 `hyperframes render` 默认 CRF 16。想不比本机差就用 `high`。
- 云端按时长向上取整出帧，常比本机多 1 帧。合声音时加 `-shortest`。
- `--output-resolution 4k` 是按 1080p 排版超采样出 4K，排版不用改。

## 实际效果

数据都来自同一期片子（11 分 17 秒，1080p 30fps，20,302 帧），详见 [references/results.md](references/results.md)。

画质：同一段 23 秒（695 帧）分别在 Mac mini、一台 Windows 电脑、Cloud Run 上渲，和 Mac 那份逐帧比，Windows 是 PSNR 41.6 dB、SSIM 0.993，云端是 34.9 dB、0.990。纯背景区域三处都在 51 dB 左右，跟本机自己重压一遍的误差一样；分数差全在文字边缘的抗锯齿（三个系统画字方式不同），把字幕放大四倍看，字形和位置完全一样。

速度和花费：

| | Mac mini 16 GB | Windows 电脑 | Cloud Run（10 台） |
|---|---|---|---|
| 23 秒小段 | 60 秒 | 230 秒（含首次下载 Chrome） | 41–55 秒，0.024–0.04 美元 |
| 11 分钟整条 | 渲不了，交换区超 5 GB | 估约 57 分钟 | 14 分钟，0.89 美元 |
| 23 秒小段出 4K | 没试 | 没试 | 142 秒，0.075 美元 |

0.89 美元是 HyperFrames 按 Google 牌价算的计算费，没扣每月免费额度，也没算存储和下载流量。实际账单以 Google Cloud 计费页为准。

## 100 美元额度能出多少片

额度条件、单价出处和推算过程在 [references/cost.md](references/cost.md)。按实测单价，1080p 30fps 每分钟成片约 0.08 美元渲染费，加上下载到国内的流量约 0.01 美元；4K 约是 1080p 的 3 倍。扣掉每月约 0.15 美元的镜像存储，Ultra 20x 的 100 美元大约够：

| 规格 | 每条成本 | 每月约能渲 |
|---|---|---|
| 1080p，1 分钟短片 | 0.07–0.11 美元 | 900–1,400 条 |
| 1080p，10 分钟长片 | 约 0.9 美元 | 约 110 条（约 1,100 分钟） |
| 4K，1 分钟短片 | 0.23–0.34 美元 | 290–430 条 |
| 4K，10 分钟长片 | 约 2.7 美元 | 约 37 条 |

这是每条只渲一遍的数。实际做片要改几轮，整条重渲两三遍很正常，按三遍算，1080p 长片一个月也有 35 条左右，对个人和小团队基本用不完。Ultra 5x 每月是 40 美元，表里的数乘 0.4；AI Pro 是 10 美元，乘 0.1。同一笔额度也能花在 Gemini API 上，两边一起用就要分着算。

这些数的前提是画面复杂度跟我们那期差不多（HTML、SVG、GSAP 动画加几张截图和光晕）。大量模糊、粒子、WebGL 的场景渲得慢，单价会更高。先拿自己的片子渲一小段，看 `--json` 输出里的费用，再乘时长。

## 文件

- `scripts/check_project.py`：上云前体检。
- `scripts/cloud_render.sh`：体检、打包、渲染、下载、合音轨一条命令。
- `scripts/build_image.sh`：用 Cloud Build 建渲染镜像并部署。
- `scripts/compare.sh`：两份视频逐帧算 PSNR 和 SSIM。
- `references/setup.md`：从零开始的完整步骤和拆除方法。
- `references/cost.md`：额度条件、单价、产出量推算。
- `references/results.md`：实测数据。
