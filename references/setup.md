# 从零开始部署

标「本人」的步骤要在浏览器里自己点：涉及付款方式、订阅、条款和登录，脚本和 AI 都不该代做。其余步骤可以交给命令行或 AI 跑。

下面的命令用这几个变量，先按自己的情况设好：

```bash
export PROJECT=<你的项目 ID>          # 例如 my-video-render-123456
export REGION=us-central1             # Cloud Run 一档价区，单价最低的一批
export HF_VERSION=0.9.28              # 本文实测的 HyperFrames 版本
```

## 1. 领每月 Cloud 额度（本人）

1. 订阅 Google AI Ultra（20x 档每月 100 美元额度，5x 档 40 美元，AI Pro 10 美元）。
2. 打开 Google Developer Program（developers.google.com/program），用同一个 Google 账号建开发者资料。会员和开发者资料要在同一个账号上。
3. 进开发者权益页（developers.google.com/program/my-benefits），找到 Google Cloud 额度那一项，选要入账的 Cloud 结算账户。勾上「Always use this billing account」，以后每月自动入账到这个结算账户。

额度按你领取那天每月发一次，不是按自然月。每笔额度自发放起一年内有效。条件细节和出处见 [cost.md](cost.md)。

## 2. 建项目、挂结算、设预算提醒（本人）

1. 在 console.cloud.google.com 新建一个项目，专门用来渲染，方便看账、也方便以后整体删掉。记下项目 ID。
2. 新建或选择结算账户，挂到这个项目上。建结算账户时 Google 一般会要求填付款方式；额度用完以后的费用会记到这个付款方式上。
3. 在「结算 → 预算和提醒」建一个预算，例如 10 美元，50%、90%、100% 提醒。注意预算只发邮件，不会自动停服务。

预算也可以用命令建（需要先开 billingbudgets API）：

```bash
gcloud billing budgets create --billing-account=<结算账户 ID> \
  --display-name=video-render --budget-amount=10USD \
  --threshold-rule=percent=0.5 --threshold-rule=percent=0.9 --threshold-rule=percent=1.0
```

真正兜底的是部署时的 `--max-instances`：最多 10 台、每台每小时约 0.49 美元，就算出错一直在跑，一小时也就 5 美元上下，单次请求最长 1 小时就被掐掉。

## 3. 装工具、授权

- Google Cloud CLI（gcloud）：cloud.google.com/sdk/docs/install。
- Terraform 1.5 以上：developer.hashicorp.com/terraform/install。
- Node.js 20 以上（用 `npx` 跑 HyperFrames）。
- ffmpeg（下载后合音轨和比对画质用）。

授权会弹浏览器（本人登录）：

```bash
gcloud auth login
gcloud auth application-default login
gcloud config set project $PROJECT
gcloud services enable cloudbuild.googleapis.com artifactregistry.googleapis.com run.googleapis.com \
  workflows.googleapis.com workflowexecutions.googleapis.com storage.googleapis.com
```

## 4. 建镜像并部署

npm 装的 HyperFrames 命令行自己建不了 Cloud Run 镜像（Dockerfile 需要整个源码仓库），所以要拉同版本源码交给 Cloud Build：

```bash
bash scripts/build_image.sh            # 读 PROJECT、REGION、HF_VERSION；加 --dry-run 只打印命令
```

它会建 Artifact Registry 仓库 `hyperframes`、拉 `heygen-com/hyperframes` 的 `v$HF_VERSION`、只排除根目录的大文件夹再上传、用 BuildKit 加 `TARGETARCH=amd64` 构建（不加选不出 ffmpeg 包）、最后执行 deploy。构建约 10 分钟，默认机型每月前 2,500 分钟免费。

deploy 用 Terraform 建这些：Cloud Run 服务 `hyperframes-render`（每台 4 vCPU、16 GiB，最少 0 台、最多 10 台）、Workflows、一个渲染存储桶（文件 7 天自动删）、两个服务账号、两条告警。部署坐标写在 `~/.hyperframes/cloudrun-state.json`，Terraform 状态在 npx 缓存里，建议把 state 文件复制一份留着，拆的时候要用。

以后升级 HyperFrames 版本，改 `HF_VERSION` 重跑这一步就行。

## 5. 渲染和下载

```bash
bash scripts/cloud_render.sh ./my-video                       # 1080p 30fps high 档
bash scripts/cloud_render.sh ./my-video --4k --out final-4k.mp4
bash scripts/cloud_render.sh ./my-video --audio mix.wav --out master.mp4
```

脚本先体检，然后把工程用 `rsync -aL` 拷到临时目录（解开软链接，跳过 node_modules 和 .git），上云渲染、等结果、从存储桶下载。`--json` 的原始输出存在 `<out>.render.json`，里面有帧数和 HyperFrames 算的费用。

想自己敲命令：

```bash
npx -y -p hyperframes@$HF_VERSION -p @hyperframes/gcp-cloud-run@$HF_VERSION hyperframes cloudrun render ./stage \
  --width 1920 --height 1080 --fps 30 --quality high --max-parallel-chunks 10 --render-id my-video-01 --wait --json
gcloud storage cp gs://<渲染桶>/renders/my-video-01/output.mp4 ./my-video.mp4
```

同一个模板批量渲很多份（换文字、换头像），用 `hyperframes cloudrun render-batch` 加 JSONL，见 HyperFrames 文档。

## 6. 拆除

空闲时 Cloud Run 不留实例，不拆每月也只有约 0.15 美元的镜像存储费。真要拆：

```bash
gcloud storage rm -r "gs://<渲染桶>/**"           # Terraform 不删非空桶，先清空（里面只有中间文件和成品）
npx -y -p hyperframes@$HF_VERSION -p @hyperframes/gcp-cloud-run@$HF_VERSION hyperframes cloudrun destroy --project $PROJECT
gcloud artifacts repositories delete hyperframes --location $REGION --project $PROJECT
gcloud storage rm -r gs://${PROJECT}_cloudbuild
```

destroy 要读 npx 缓存里的 terraform.tfstate。缓存被清了的话，`npm pack @hyperframes/gcp-cloud-run@$HF_VERSION` 解开，把留的那份 state 放进它的 terraform 目录、改名 terraform.tfstate 再 destroy。最省事的拆法是直接在控制台关闭整个项目（本人），所有资源一起停止计费。
