# Whisper 转写也放到谷歌云上

配音核对、逐字对时、字幕时间轴都要跑 Whisper。本机跑 mlx-whisper large-v3-turbo，一个进程占 3–5 GB，16 GB 的 Mac mini
同时跑两三个就把内存吃光，只能全机排队一次一个。这一套把 Whisper 放到同一个 Google Cloud 项目里一台带 NVIDIA L4 的机器上：
本机只上传音频、拿回结果，结果格式和 mlx-whisper 一模一样，调用的脚本不用改解析。

## 结构

- `whisper/server.py`：faster-whisper（CTranslate2）large-v3-turbo，逐词时间戳，返回 `{text, language, segments: [{start, end,
  text, words: [{word, start, end, probability}]}]}`，和 `mlx_whisper.transcribe(..., word_timestamps=True)` 同格式。默认
  beam 1（贪心解码，和 mlx-whisper 一致）。没有请求超过 `IDLE_EXIT_SECONDS`（默认 300 秒）就自己退出。
- 机器：Compute Engine g2-standard-4（4 核 16 GB）+ 1 块 L4，Spot，Deep Learning 镜像（自带显卡驱动），50 GB 盘。启动脚本
  `whisper/gce-startup.sh` 第一次开机建 Python 环境、下模型（约 2 分钟，留在盘上），以后每次开机直接起服务；服务空闲退出后
  机器自己关机。关机状态只收盘钱。
- 鉴权：机器没有对公网开端口，防火墙只放谷歌 IAP 的网段。客户端用 `gcloud compute start-iap-tunnel` 开隧道，谁能连由 IAM
  决定（项目所有者默认可以）。没有匿名入口，也没有自己管的密码。
- 客户端 `whisper/whisper_cloud.py`：只用 Python 标准库。机器关着就先开机（约 1 分钟），开隧道、等服务就绪、上传、拿结果；
  超过 30 MB 的音频先用 ffmpeg 压成 16 kHz 单声道 FLAC。
- 备用：同一个镜像以纯 CPU 方式部署在 Cloud Run（`whisper-cpu`，8 核 16 GB，请求计费，空闲缩到 0）。只有显卡机器开不了机
  （缺货、配额）时才用，会大声提示，结果的 `meta.fallback` 记下原因。转写本身出错不会换后端。

## 部署

```bash
export PROJECT=<你的项目 ID>
bash whisper/deploy_gce.sh                       # 建服务账号、防火墙、机器，写 ~/.config/whisper-cloud/config.json
python3 whisper/whisper_cloud.py some.wav --language zh --prompt "以下是普通话的句子。"
python3 whisper/whisper_cloud.py --status         # 看机器开没开；--stop 马上关
```

可选的 CPU 备用：

```bash
gcloud artifacts repositories create whisper --repository-format=docker --location=us-central1 --project $PROJECT
cd whisper && gcloud builds submit . --project $PROJECT --region us-central1 --config cloudbuild.yaml \
  --substitutions _IMAGE=us-central1-docker.pkg.dev/$PROJECT/whisper/whisper:v1
gcloud run deploy whisper-cpu --project $PROJECT --region us-central1 --image us-central1-docker.pkg.dev/$PROJECT/whisper/whisper:v1 \
  --cpu 8 --memory 16Gi --min-instances 0 --max-instances 4 --concurrency 1 --timeout 1800 --no-allow-unauthenticated \
  --cpu-boost --set-env-vars IDLE_EXIT_SECONDS=0,WHISPER_DEVICE=cpu,WHISPER_COMPUTE=int8
```

然后在配置里加 `"fallback": {"label": "Cloud Run CPU", "backend": "cloudrun", "url": "<服务地址>", "timeout": 3600}`，
样子见 `whisper/config.example.json`。

## 调用方怎么接

每个要转写的脚本加一个小函数：有 `~/.config/whisper-cloud/config.json` 就走云端，没有就照旧本机。

```python
def cloud_whisper():
    mode = os.environ.get("WHISPER_BACKEND", "").lower()          # local = 强制本机；cloud = 强制云端
    if mode == "local":
        return None
    cfg = Path(os.environ.get("WHISPER_CLOUD_CONFIG") or Path.home() / ".config/whisper-cloud/config.json")
    if not cfg.exists():
        if mode == "cloud":
            raise SystemExit(f"WHISPER_BACKEND=cloud，但没有 {cfg}")
        return None
    spec = importlib.util.spec_from_file_location("whisper_cloud", json.loads(cfg.read_text())["client"])
    mod = importlib.util.module_from_spec(spec); spec.loader.exec_module(mod)
    return mod.transcribe                                          # 参数和返回值都同 mlx_whisper.transcribe

transcribe = cloud_whisper() or mlx_whisper.transcribe
res = transcribe(path, path_or_hf_repo="mlx-community/whisper-large-v3-turbo", language="zh",
                 word_timestamps=True, initial_prompt="以下是普通话的句子。")
```

规矩：云端失败就停下说原因，不悄悄退回本机（本机那个进程可能正是把机器压垮的那个）；要用本机得显式设
`WHISPER_BACKEND=local`。别人的机器没有这份配置，什么都不用改。

## 实测（2026-11-22，us-central1-a，Spot L4）

| | 本机 Mac mini（M 系列，mlx-whisper） | 云上 L4 | Cloud Run CPU 8 核（备用） |
|---|---|---|---|
| 30 秒配音 | 内存 3–5 GB，要排队 | 0.7–1.2 秒；含 IAP 上传往返 3–4 秒 | 22–45 秒 |
| 10 分钟音频 | — | 18.8 秒；往返 25.5 秒（57 MB wav 先压 FLAC） | 估 10–14 分钟 |
| 冷启动 | — | 机器关着时开机到出结果 61 秒；第一次装环境约 2 分钟 | 30–50 秒 |

准确率：拿一期成片的 8 段配音（克隆音色，共 1,523 字）同一个提示词各转一次，对着口播稿算错字率，再逐字比时间：

| | 错字率 | 和本机一字不差的段 | 逐字时间偏差（中位 / 95% / 最大） |
|---|---|---|---|
| 本机 mlx-whisper | 8.0% | — | — |
| 云上 beam 1（默认） | 8.1% | 6 / 8 | 0 / 13 ms / 400 ms |
| 云上 beam 5 | 8.3% | 3 / 8 | 0 / 20 ms / 400 ms |
| Cloud Run CPU int8 | 8.3% | 2 / 8 | 0 / 20 ms / 420 ms |

错字率里大半是写法差别（稿子写「三」、Whisper 写「3」），不是真听错。beam 1 和本机几乎是同一份结果，剩下的差别是两三个同音字。

## 花费（Google 牌价，us-central1）

- 机器开着：Spot g2-standard-4 + L4 每小时约 0.42 美元（核 4×0.015 + 内存 16×0.00175 + L4 0.335）。按需价约 0.71 美元，但按需
  L4 经常整个区缺货。
- 每次「开机—转一批—空闲 5 分钟关机」约 6–7 分钟，约 0.045 美元；纯转写每分钟音频约 0.0003 美元，可以忽略。
- 盘：50 GB balanced 每月约 5 美元，关机也收。镜像存储（只给 CPU 备用用）约 4 GB，每月约 0.4 美元。
- Cloud Run CPU 备用：每分钟音频约 0.015–0.02 美元，不用不收钱。
- 一天开 5–10 次机，一个月大约 7–14 美元的机器钱，加 5 美元的盘。

## 踩过的坑

- **Cloud Run 的 GPU 配额申请被秒拒。** 新项目 Cloud Run L4 配额是 0，`gcloud beta quotas preferences create` 申请（有没有可用区冗余都试了）
  3 秒自动拒绝；部署报 `You do not have quota for using GPUs`。镜像（`Dockerfile`）是按 Cloud Run 写的，配额批下来可以直接
  `gcloud run deploy --gpu 1 --gpu-type nvidia-l4`，客户端配 `backend: cloudrun` 就行。Compute Engine 的全局显卡配额申请到 1 是秒批的，
  所以现在用的是 Compute Engine。
- **按需 L4 全线缺货。** 那天 us-central1 a/b/c、us-east4、us-east1、us-west1、us-west4 全部 STOCKOUT；Spot 在 us-central1-a 一次就开出来了。
  Spot 会被回收，回收后机器停着，客户端下次调用会重新开机；开不了就走 CPU 备用。
- **Deep Learning 镜像里没有 Docker。** `common-cu129-ubuntu-2204-nvidia-580` 只有驱动和 CUDA，所以启动脚本直接建 venv，包版本和
  Dockerfile 钉的一样（faster-whisper 1.2.1、ctranslate2 4.6.0、cuBLAS 12.4、cuDNN 9.1）。
- **启动脚本出错别马上关机。** 第一版容器没起来就 `poweroff`，一分钟就关了、看不到日志。现在服务异常退出会留 10 分钟再关，日志写串口：
  `gcloud compute instances get-serial-port-output whisper-l4 --zone <区> | grep whisper-run`。
- **IAP 隧道要等服务真的在听。** 服务没起来时开的隧道会一直坏着，客户端每次健康检查失败就重开隧道。
- **改 server.py 要等下次开机。** 它放在机器元数据 `whisper-server` 里，开机时读：`gcloud compute instances add-metadata <机器> --metadata-from-file whisper-server=whisper/server.py`，
  再 `whisper_cloud.py --stop`，下次调用就用新的。
