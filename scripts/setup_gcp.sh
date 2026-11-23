#!/usr/bin/env bash
# One-time (and re-runnable) GCP setup for Remotion renders on Cloud Run Jobs.
# Creates/updates: APIs, a bucket whose files delete after 7 days, a service account that can only use
# that bucket, an Artifact Registry repo, the render image (Cloud Build), and the Cloud Run Job.
# Writes the coordinates to ~/.config/remotion-cloud-render/config.env for cloud_render.sh.
#
# Usage: PROJECT=<id> REMOTION_VERSION=<x.y.z> bash setup_gcp.sh [--dry-run]
#   or : PROJECT=<id> bash setup_gcp.sh --from <remotion project dir>   (reads the version from its package.json)
# Optional env: REGION (us-central1)  BUCKET (<project>-remotion-render)  JOB (remotion-render)
#               TASK_CPU (4)  TASK_MEMORY (8Gi)  MAX_PARALLEL (10)  TASK_TIMEOUT (3600)  MAX_RETRIES (1)
# Re-run after changing container/ (new image tag = version + hash of container/) or the Remotion version.
set -euo pipefail

HERE="$(cd "$(dirname "$0")/.." && pwd)"
DRY=0; FROM=""
while [ $# -gt 0 ]; do
  case "$1" in
    --dry-run) DRY=1; shift;;
    --from) FROM="$2"; shift 2;;
    *) echo "unknown argument: $1"; exit 1;;
  esac
done
: "${PROJECT:?export PROJECT=<your GCP project id>}"
if [ -z "${REMOTION_VERSION:-}" ] && [ -n "$FROM" ]; then
  REMOTION_VERSION="$(node -p "require('$(cd "$FROM" && pwd)/node_modules/remotion/package.json').version")"
fi
: "${REMOTION_VERSION:?set REMOTION_VERSION=<x.y.z> or pass --from <project dir>}"
REGION="${REGION:-us-central1}"
BUCKET="${BUCKET:-$PROJECT-remotion-render}"
JOB="${JOB:-remotion-render}"
SA="remotion-render@$PROJECT.iam.gserviceaccount.com"
TASK_CPU="${TASK_CPU:-4}"; TASK_MEMORY="${TASK_MEMORY:-8Gi}"
MAX_PARALLEL="${MAX_PARALLEL:-10}"; TASK_TIMEOUT="${TASK_TIMEOUT:-3600}"; MAX_RETRIES="${MAX_RETRIES:-1}"
HASH="$(cat "$HERE/container/Dockerfile" "$HERE/container/task.mjs" | sha256sum | cut -c1-8)"
IMAGE="$REGION-docker.pkg.dev/$PROJECT/remotion/remotion-render:$REMOTION_VERSION-$HASH"
G=(--project "$PROJECT")

run() { echo "+ $*"; [ "$DRY" = 1 ] || "$@"; }
exists() { [ "$DRY" = 1 ] && return 1; "$@" >/dev/null 2>&1; }

run gcloud services enable run.googleapis.com artifactregistry.googleapis.com cloudbuild.googleapis.com \
  storage.googleapis.com logging.googleapis.com "${G[@]}"

if ! exists gcloud storage buckets describe "gs://$BUCKET" "${G[@]}"; then
  run gcloud storage buckets create "gs://$BUCKET" --location "$REGION" --uniform-bucket-level-access \
    --public-access-prevention "${G[@]}"
fi
LIFE="$(mktemp)"; trap 'rm -f "$LIFE"' EXIT
echo '{"rule":[{"action":{"type":"Delete"},"condition":{"age":7}}]}' > "$LIFE"
run gcloud storage buckets update "gs://$BUCKET" --lifecycle-file "$LIFE" "${G[@]}"

if ! exists gcloud iam service-accounts describe "$SA" "${G[@]}"; then
  run gcloud iam service-accounts create remotion-render --display-name "Remotion render tasks" "${G[@]}"
fi
run gcloud storage buckets add-iam-policy-binding "gs://$BUCKET" --member "serviceAccount:$SA" \
  --role roles/storage.objectUser "${G[@]}" --format none

if ! exists gcloud artifacts repositories describe remotion --location "$REGION" "${G[@]}"; then
  run gcloud artifacts repositories create remotion --repository-format docker --location "$REGION" "${G[@]}"
fi

if exists gcloud artifacts docker images describe "$IMAGE" "${G[@]}"; then
  echo "image $IMAGE already built"
else
  run gcloud builds submit "$HERE/container" --config "$HERE/container/cloudbuild.yaml" \
    --substitutions "_IMAGE=$IMAGE,_REMOTION_VERSION=$REMOTION_VERSION" "${G[@]}"
fi

VOL=(--add-volume "name=render,type=cloud-storage,bucket=$BUCKET" --add-volume-mount "volume=render,mount-path=/mnt/render")
exists gcloud run jobs describe "$JOB" --region "$REGION" "${G[@]}" && VOL=(--clear-volumes --clear-volume-mounts "${VOL[@]}")
run gcloud run jobs deploy "$JOB" --image "$IMAGE" --region "$REGION" "${G[@]}" \
  --cpu "$TASK_CPU" --memory "$TASK_MEMORY" --tasks 1 --parallelism "$MAX_PARALLEL" \
  --task-timeout "$TASK_TIMEOUT" --max-retries "$MAX_RETRIES" --service-account "$SA" \
  --set-env-vars "TASK_CPU=$TASK_CPU,MOUNT=/mnt/render" "${VOL[@]}"

CONF="$HOME/.config/remotion-cloud-render/config.env"
if [ "$DRY" = 0 ]; then
  mkdir -p "$(dirname "$CONF")"
  cat > "$CONF" <<EOF
PROJECT=$PROJECT
REGION=$REGION
BUCKET=$BUCKET
JOB=$JOB
IMAGE=$IMAGE
REMOTION_VERSION=$REMOTION_VERSION
TASK_CPU=$TASK_CPU
TASK_MEMORY=$TASK_MEMORY
MAX_PARALLEL=$MAX_PARALLEL
EOF
  echo "ready: job $JOB in $REGION runs $IMAGE; settings in $CONF"
fi
