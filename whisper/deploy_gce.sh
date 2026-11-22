#!/bin/bash
# Create the Whisper GPU VM (one NVIDIA L4) in your project and write the client config.
#
#   PROJECT=<project id> bash whisper/deploy_gce.sh                # tries the zones below in order, Spot first
#   PROJECT=<id> PROVISIONING=STANDARD bash whisper/deploy_gce.sh   # on-demand (often out of stock, ~1.7x the price)
#   PROJECT=<id> bash whisper/deploy_gce.sh us-central1-a us-east4-c
#
# What it sets up: Compute Engine + IAP APIs, a service account that may only write logs, a firewall rule that admits
# only Google's IAP range (35.235.240.0/20) on 8080 and 22 (no public port), and the VM: g2-standard-4 + L4,
# Deep Learning image with the NVIDIA driver, 50 GB balanced disk, startup script gce-startup.sh, server.py in metadata.
# The first boot builds the Python environment and downloads the model (~2 minutes); the VM then powers itself off
# after IDLE seconds without a request. A stopped VM only costs its disk (~5 USD a month for 50 GB).
#
# Needs: gcloud logged in as a project owner, and a GPU quota of at least 1:
#   gcloud beta quotas preferences create --service=compute.googleapis.com --project=$PROJECT \
#     --billing-project=$PROJECT --quota-id=GPUS-ALL-REGIONS-per-project --preferred-value=1 --preference-id=gpus-all-1
set -euo pipefail
: "${PROJECT:?set PROJECT=<your project id>}"
NAME=${NAME:-whisper-l4}
IDLE=${IDLE:-300}
PROVISIONING=${PROVISIONING:-SPOT}
HERE=$(cd "$(dirname "$0")" && pwd)
if [ $# -gt 0 ]; then ZONES=("$@"); else
  ZONES=(us-central1-a us-central1-b us-central1-c us-east4-a us-east4-c us-east1-c us-east1-d us-west1-a us-west1-b us-west4-a us-west4-c)
fi

gcloud services enable compute.googleapis.com iap.googleapis.com --project "$PROJECT"
SA="whisper-vm@$PROJECT.iam.gserviceaccount.com"
gcloud iam service-accounts describe "$SA" --project "$PROJECT" >/dev/null 2>&1 \
  || gcloud iam service-accounts create whisper-vm --project "$PROJECT" --display-name "Whisper GPU VM"
gcloud projects add-iam-policy-binding "$PROJECT" --member "serviceAccount:$SA" --role roles/logging.logWriter \
  --condition=None >/dev/null
gcloud compute firewall-rules describe whisper-iap-8080 --project "$PROJECT" >/dev/null 2>&1 \
  || gcloud compute firewall-rules create whisper-iap-8080 --project "$PROJECT" --network default --direction INGRESS \
       --source-ranges 35.235.240.0/20 --allow tcp:8080,tcp:22 --target-tags whisper

extra=()
[ "$PROVISIONING" = SPOT ] && extra=(--provisioning-model SPOT --instance-termination-action STOP)
for z in "${ZONES[@]}"; do
  echo "== $z ($PROVISIONING)"
  if gcloud compute instances create "$NAME" --project "$PROJECT" --zone "$z" --machine-type g2-standard-4 \
      --accelerator type=nvidia-l4,count=1 --maintenance-policy TERMINATE "${extra[@]}" \
      --image-family common-cu129-ubuntu-2204-nvidia-580 --image-project deeplearning-platform-release \
      --boot-disk-size 50GB --boot-disk-type pd-balanced --service-account "$SA" --scopes cloud-platform --tags whisper \
      --metadata "whisper-idle=$IDLE" --metadata-from-file "startup-script=$HERE/gce-startup.sh,whisper-server=$HERE/server.py" \
      --labels purpose=whisper; then
    CFG=${WHISPER_CLOUD_CONFIG:-$HOME/.config/whisper-cloud/config.json}
    mkdir -p "$(dirname "$CFG")"
    if [ -e "$CFG" ]; then echo "已有 $CFG，没覆盖；新机器在 $z"; else
      cat > "$CFG" <<EOF
{"backend": "gce", "project": "$PROJECT", "zone": "$z", "instance": "$NAME", "port": 8080,
 "gcloud": "$(command -v gcloud)", "timeout": 1800, "client": "$HERE/whisper_cloud.py"}
EOF
      chmod 600 "$CFG"; echo "写好 $CFG"
    fi
    echo "第一次开机要装环境、下模型，约 2 分钟；之后试一条：python3 $HERE/whisper_cloud.py some.wav --language zh"
    exit 0
  fi
done
echo "所有区都没开成（多半是缺货）。过一会儿再试，或者换 PROVISIONING / 区。" >&2
exit 1
