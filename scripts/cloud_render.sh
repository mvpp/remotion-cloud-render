#!/usr/bin/env bash
# 一条命令：体检 → 打包（解开软链接）→ Cloud Run 渲染 → 下载 →（可选）合音轨。
#
# 用法:
#   cloud_render.sh <工程目录> [选项]
#     --out FILE         成品路径，默认 <工程目录名>.mp4
#     --id NAME          render-id，默认 <工程目录名>-<时间>
#     --width W --height H   画布尺寸，默认 1920x1080（要和工程排版一致）
#     --fps N            24 / 30 / 60，默认 30
#     --quality Q        draft / standard / high，默认 high（CRF 15）
#     --4k               超采样输出 4K（排版不用改）
#     --audio FILE       下载后把这条音轨合进去（视频直接拷贝，音频转 AAC，按短的那条截齐）
#     --skip-check       跳过体检
#
# 环境变量: HF_VERSION（默认 0.9.28，要和部署的镜像同版本）、MAX_PARALLEL（默认 10，不能超过部署的 --max-instances）
# 前提: 已按 references/setup.md 部署，~/.hyperframes/cloudrun-state.json 存在，gcloud 已登录。
set -euo pipefail

HF_VERSION="${HF_VERSION:-0.9.28}"
MAX_PARALLEL="${MAX_PARALLEL:-10}"
HERE="$(cd "$(dirname "$0")" && pwd)"

[ $# -ge 1 ] || { sed -n 2,17p "$0"; exit 1; }
SRC="$(cd "$1" && pwd)"; shift
NAME="$(basename "$SRC")"
OUT="$PWD/$NAME.mp4"; RID="$NAME-$(date +%Y%m%d%H%M%S)"
W=1920; H=1080; FPS=30; Q=high; EXTRA=(); AUDIO=""; CHECK=1
while [ $# -gt 0 ]; do
  case "$1" in
    --out) OUT="$2"; shift 2;;
    --id) RID="$2"; shift 2;;
    --width) W="$2"; shift 2;;
    --height) H="$2"; shift 2;;
    --fps) FPS="$2"; shift 2;;
    --quality) Q="$2"; shift 2;;
    --4k) EXTRA+=(--output-resolution 4k); shift;;
    --audio) AUDIO="$2"; shift 2;;
    --skip-check) CHECK=0; shift;;
    *) echo "不认识的参数: $1"; exit 1;;
  esac
done
mkdir -p "$(dirname "$OUT")"; OUT="$(cd "$(dirname "$OUT")" && pwd)/$(basename "$OUT")"
RID="$(echo "$RID" | tr 'A-Z_ ' 'a-z--' | tr -cd 'a-z0-9-')"

STATE="$HOME/.hyperframes/cloudrun-state.json"
[ -f "$STATE" ] || { echo "没找到 $STATE，先按 references/setup.md 部署"; exit 1; }
BUCKET="$(python3 -c 'import json,sys;print(json.load(open(sys.argv[1]))["bucketName"])' "$STATE")"

if [ "$CHECK" = 1 ]; then python3 "$HERE/check_project.py" "$SRC"; fi

# 云端只认真文件：拷一份解开软链接的工程，跳过不需要上传的目录
STAGE="$(mktemp -d)/$NAME"
trap 'rm -rf "$(dirname "$STAGE")"' EXIT
rsync -aL --exclude node_modules --exclude .git --exclude .hyperframes --exclude out --exclude renders "$SRC/" "$STAGE/"

echo "上云渲染 $RID（${W}x${H} ${FPS}fps $Q ${EXTRA[*]:-}）…"
t0=$(date +%s)
JSON="$OUT.render.json"
npx -y -p "hyperframes@$HF_VERSION" -p "@hyperframes/gcp-cloud-run@$HF_VERSION" hyperframes cloudrun render "$STAGE" \
  --width "$W" --height "$H" --fps "$FPS" --quality "$Q" ${EXTRA[@]+"${EXTRA[@]}"} \
  --max-parallel-chunks "$MAX_PARALLEL" --render-id "$RID" --wait --json > "$JSON"
python3 - "$JSON" <<'PY'
import json, sys
d = json.load(open(sys.argv[1]))
c = d.get("costs", {})
print(f'{d["status"]}：{d.get("framesRendered")} 帧，按牌价约 {c.get("displayCost")}（不含存储和下载流量），{d.get("startedAt")} → {d.get("endedAt")}')
if d["status"] != "succeeded":
    print(json.dumps(d.get("errors"), ensure_ascii=False, indent=1)[:3000])
    sys.exit(1)
PY

URI="$(python3 -c 'import json,sys;d=json.load(open(sys.argv[1]));print((d.get("outputFile") or {}).get("gcsUri") or "")' "$JSON")"
URI="${URI:-gs://$BUCKET/renders/$RID/output.mp4}"
if [ -n "$AUDIO" ]; then
  VID="$OUT.video.mp4"
  gcloud storage cp "$URI" "$VID"
  ffmpeg -v error -nostdin -y -i "$VID" -i "$AUDIO" -map 0:v -map 1:a -c:v copy -c:a aac -b:a 192k -ar 48000 \
    -shortest -movflags +faststart "$OUT"
  rm -f "$VID"
else
  gcloud storage cp "$URI" "$OUT"
fi
echo "完成：$OUT，共用时 $(( $(date +%s) - t0 )) 秒。云上那份 7 天后自动删。"
