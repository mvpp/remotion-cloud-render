#!/usr/bin/env bash
# 用 Cloud Build 建 HyperFrames 渲染镜像，然后 cloudrun deploy。
# npm 装的 HyperFrames CLI 自己建不了镜像（Dockerfile 需要整个源码仓库），所以拉同版本源码上传构建。
#
# 用法: PROJECT=<项目ID> [REGION=us-central1] [HF_VERSION=0.9.28] [MAX_INSTANCES=10] bash build_image.sh [--dry-run]
# 构建约 10 分钟，默认机型 e2-standard-2 每月前 2,500 分钟免费。
set -euo pipefail

: "${PROJECT:?先 export PROJECT=<你的项目 ID>}"
REGION="${REGION:-us-central1}"
HF_VERSION="${HF_VERSION:-0.9.28}"
MAX_INSTANCES="${MAX_INSTANCES:-10}"
DRY=0; [ "${1:-}" = "--dry-run" ] && DRY=1
run() { echo "+ $*"; [ "$DRY" = 1 ] || "$@"; }

TAG="$(echo "$HF_VERSION" | tr -d .)-$(date +%Y%m%d%H%M)"
IMAGE="$REGION-docker.pkg.dev/$PROJECT/hyperframes/hyperframes-render:$TAG"
WORK="$(mktemp -d)"
trap 'rm -rf "$WORK"' EXIT

run gcloud services enable cloudbuild.googleapis.com artifactregistry.googleapis.com --project "$PROJECT"
if ! gcloud artifacts repositories describe hyperframes --location "$REGION" --project "$PROJECT" >/dev/null 2>&1; then
  run gcloud artifacts repositories create hyperframes --repository-format=docker --location "$REGION" --project "$PROJECT"
fi

run git clone --depth 1 --branch "v$HF_VERSION" https://github.com/heygen-com/hyperframes.git "$WORK/src"

# 只排除根目录的大文件夹。写成 registry/（不带开头的斜杠）会把 packages/core/src/registry 也排掉，镜像就坏了。
cat > "$WORK/gcloudignore" <<'EOF'
/.git
/docs/
/registry/
/skills/
/releases/
/plans/
/examples/
/updates/
/assets/
/themes/
node_modules/
EOF
# BuildKit 和 TARGETARCH=amd64 都要：不然 Dockerfile 选不出 ffmpeg 包
cat > "$WORK/cloudbuild.yaml" <<EOF
steps:
- name: gcr.io/cloud-builders/docker
  env: ["DOCKER_BUILDKIT=1"]
  args: ["build","--build-arg","TARGETARCH=amd64","-f","packages/gcp-cloud-run/Dockerfile","-t","$IMAGE","."]
images: ["$IMAGE"]
timeout: 3600s
EOF
[ "$DRY" = 1 ] && { echo "--- cloudbuild.yaml"; cat "$WORK/cloudbuild.yaml"; } || cp "$WORK/gcloudignore" "$WORK/src/.gcloudignore"

run gcloud builds submit "$WORK/src" --project "$PROJECT" --region "$REGION" --config "$WORK/cloudbuild.yaml" --timeout 3600s

run npx -y -p "hyperframes@$HF_VERSION" -p "@hyperframes/gcp-cloud-run@$HF_VERSION" hyperframes cloudrun deploy \
  --project "$PROJECT" --region "$REGION" --image "$IMAGE" --max-instances "$MAX_INSTANCES"

echo "镜像 $IMAGE 已部署。部署坐标在 ~/.hyperframes/cloudrun-state.json；建议把 npx 缓存里的 terraform.tfstate 复制一份留着，拆的时候用。"
