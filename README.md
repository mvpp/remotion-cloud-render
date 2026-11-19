# HyperFrames 云渲染

把 HyperFrames 视频放到你自己的 Google Cloud Run 上渲染。本机只负责打包上传和下载，渲染交给云上 10 台 4 核 16 GB 的机器同时跑，空闲时一台都不留、不收算力钱。

它是一个 skill：给 Claude Code、Codex 这类 AI 编程助手读的操作手册，加上几个能直接跑的脚本。人也可以照着做。

## 为什么要上云

HyperFrames 的片子本质是网页，渲染就是无头 Chrome 一帧帧截图再压成视频，吃 CPU 和内存。我们用一台 16 GB 的 Mac mini 渲一期 11 分钟的 AI 讲解片，交换区一路涨过 5 GB，整台机器卡死，渲不下来。放到 Cloud Run 上：

| | Mac mini 16 GB | Windows 电脑 | Cloud Run（10 台） |
|---|---|---|---|
| 23 秒小段 | 60 秒 | 230 秒 | 41–55 秒，0.024–0.04 美元 |
| 11 分钟整条 | 渲不了 | 估约 57 分钟 | 14 分钟，0.89 美元 |

画质上，同一段在 Mac、Windows、云端各渲一份逐帧比：纯背景三处都在 51 dB 左右，等于没差别；差异只在文字边缘的抗锯齿，把字幕放大四倍看字形和位置一样。数据细节见 [references/results.md](references/results.md)。

## Google AI Ultra 送的 100 美元能渲多少

Google AI Ultra 20x 会员每月送 100 美元 Google Cloud 额度（Ultra 5x 送 40 美元，AI Pro 送 10 美元），Cloud Run 能抵。按实测单价（1080p 每分钟成片约 0.08 美元渲染费，加下载流量约 0.01 美元；4K 约 3 倍），扣掉每月约 0.15 美元的镜像存储：

| 规格 | 每条成本 | 100 美元每月约能渲 |
|---|---|---|
| 1080p，1 分钟短片 | 0.07–0.11 美元 | 900–1,400 条 |
| 1080p，10 分钟长片 | 约 0.9 美元 | 约 110 条（约 1,100 分钟） |
| 4K，1 分钟短片 | 0.23–0.34 美元 | 290–430 条 |
| 4K，10 分钟长片 | 约 2.7 美元 | 约 37 条 |

这是每条只渲一遍的数，改几轮就除以几。前提是画面复杂度和我们那期差不多（HTML、SVG、GSAP 动画加截图）；大量模糊、粒子、WebGL 会更贵。额度领取条件、有效期、单价出处和推算过程见 [references/cost.md](references/cost.md)，里面也写了哪些数还不确定。

## 适合什么工程

适合：HyperFrames 或其他靠 Chrome 截图出帧的工程，片子长、本机内存小、要整条重渲、要出 4K、要批量渲模板。

要先改造：用了 WebGPU（云上没有显卡）；有软链接、本机绝对路径；依赖本机装的字体（要放进工程用 `@font-face` 引用）。`scripts/check_project.py` 会把这些查出来。

不划算：一二十秒的小段试渲，本机一分钟就出来，上云还要上传、冷启动、下载。

## 怎么用

先按 [references/setup.md](references/setup.md) 部署一次：领额度、建项目挂结算、设预算提醒（这几步要本人在浏览器里做），装 gcloud 和 Terraform，然后

```bash
export PROJECT=<你的项目 ID>
bash scripts/build_image.sh
```

之后每次渲染一条命令：

```bash
python3 scripts/check_project.py ./my-video                 # 体检
bash scripts/cloud_render.sh ./my-video                      # 1080p 30fps，下载成 my-video.mp4
bash scripts/cloud_render.sh ./my-video --4k --audio mix.wav --out final.mp4
bash scripts/compare.sh local.mp4 final.mp4                  # 和本机渲的逐帧比画质
```

装成 skill 给 AI 助手用：

```bash
git clone https://github.com/garycaogan/gary-hf-cloud-render.git ~/.claude/skills/hf-cloud-render
```

Codex 等其他助手放进它们读 skill 的目录即可。依赖：gcloud、Terraform 1.5+、Node.js 20+、ffmpeg、Python 3、rsync。实测版本 HyperFrames 0.9.28。

## 文件

- `SKILL.md`：给 AI 助手读的入口。
- `scripts/check_project.py`：上云前体检。
- `scripts/cloud_render.sh`：体检、打包、渲染、下载、合音轨。
- `scripts/build_image.sh`：Cloud Build 建镜像并部署。
- `scripts/compare.sh`：两份视频逐帧算 PSNR 和 SSIM。
- `references/setup.md`、`cost.md`、`results.md`：部署步骤、额度和成本、实测数据。

## 许可

MIT，见 [LICENSE](LICENSE)。HyperFrames 本身是 HeyGen 的开源项目，遵循它自己的许可。
