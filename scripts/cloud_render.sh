#!/usr/bin/env bash
# One command: check → bundle → upload → Cloud Run Job (frame slices + audio in parallel) → download →
# join (ffmpeg concat -c copy) → mux audio → verify frame count → cost.
#
# Usage: cloud_render.sh <remotion project dir> <composition id> [options]
#   --out FILE            output mp4 (default <project>/out/<composition>.cloud.mp4)
#   --props FILE          input props JSON (same as `remotion render --props`)
#   --muted               no audio task, video only
#   --tasks N             number of video slices (default: one per FRAMES_PER_TASK frames, capped by MAX_PARALLEL)
#   --frames-per-task N   default 300
#   --entry FILE          entry point (default src/index.ts or src/index.tsx)
#   --env K=V             extra task env, repeatable: CONCURRENCY, JPEG_QUALITY, CRF, SCALE (2 = 4K from 1080p), X264_PRESET
#   --id NAME             render id (default <composition>-<timestamp>)
#   --skip-check          skip check_project.py
# Needs: setup_gcp.sh run once (~/.config/remotion-cloud-render/config.env), gcloud logged in, Node.
set -euo pipefail

HERE="$(cd "$(dirname "$0")" && pwd)"
CONFIG="${CONFIG:-$HOME/.config/remotion-cloud-render/config.env}"
[ -f "$CONFIG" ] || { echo "no $CONFIG — run scripts/setup_gcp.sh first"; exit 1; }
# shellcheck disable=SC1090
source "$CONFIG"

[ $# -ge 2 ] || { sed -n 2,17p "$0"; exit 1; }
PROJ="$(cd "$1" && pwd)"; COMP="$2"; shift 2
OUT="$PROJ/out/$COMP.cloud.mp4"; PROPS=""; AUDIO=1; TASKS=""; FPT=300; ENTRY=""; EXTRA=""; CHECK=1
RID="$(echo "$COMP-$(date +%Y%m%d-%H%M%S)" | tr 'A-Z_ ' 'a-z--' | tr -cd 'a-z0-9-')"
while [ $# -gt 0 ]; do
  case "$1" in
    --out) OUT="$2"; shift 2;;
    --props) PROPS="$(cd "$(dirname "$2")" && pwd)/$(basename "$2")"; shift 2;;
    --muted) AUDIO=0; shift;;
    --tasks) TASKS="$2"; shift 2;;
    --frames-per-task) FPT="$2"; shift 2;;
    --entry) ENTRY="$2"; shift 2;;
    --env) EXTRA="$EXTRA,$2"; shift 2;;
    --id) RID="$2"; shift 2;;
    --skip-check) CHECK=0; shift;;
    *) echo "unknown argument: $1"; exit 1;;
  esac
done
mkdir -p "$(dirname "$OUT")"; OUT="$(cd "$(dirname "$OUT")" && pwd)/$(basename "$OUT")"
G=(--project "$PROJECT")
T0=$(date +%s)
say() { echo "[$(date +%T)] $*"; }

# Same Remotion version as the image, or the bundle and the renderer disagree.
PV="$(node -p "require('$PROJ/node_modules/remotion/package.json').version")"
[ "$PV" = "$REMOTION_VERSION" ] || {
  echo "project uses remotion $PV but the job image is $REMOTION_VERSION."
  echo "fix: PROJECT=$PROJECT bash $HERE/setup_gcp.sh --from $PROJ   (builds a $PV image and repoints the job)"; exit 1; }
if [ -z "$ENTRY" ]; then
  for e in src/index.ts src/index.tsx src/index.js remotion/index.ts; do [ -f "$PROJ/$e" ] && { ENTRY="$e"; break; }; done
fi
[ -n "$ENTRY" ] || { echo "no entry point found, pass --entry"; exit 1; }
[ "$CHECK" = 1 ] && python3 "$HERE/check_project.py" "$PROJ"

STAGE="$(mktemp -d)"; trap 'rm -rf "$STAGE"' EXIT
say "bundling $ENTRY"
(cd "$PROJ" && npx remotion bundle "$ENTRY" --out-dir "$STAGE/bundle" --log=error >/dev/null)
tar -czf "$STAGE/bundle.tgz" -C "$STAGE/bundle" .
INFO="$(node "$HERE/probe.mjs" "$PROJ" "$STAGE/bundle" "$COMP" ${PROPS:+"$PROPS"})"
FRAMES="$(echo "$INFO" | node -pe 'JSON.parse(require("fs").readFileSync(0)).durationInFrames')"
# Exact video length. The audio is cut/padded to it: `-shortest` let the AAC encoder's frame boundary trim the
# last video frames (1811 of 1815 on 2026-11-23, audio 16 samples short).
DUR="$(echo "$INFO" | node -pe 'const c = JSON.parse(require("fs").readFileSync(0)); (c.durationInFrames / c.fps).toFixed(6)')"
if [ -z "$TASKS" ]; then
  TASKS=$(( (FRAMES + FPT - 1) / FPT )); CAP=$(( MAX_PARALLEL - AUDIO ))
  [ "$TASKS" -gt "$CAP" ] && TASKS=$CAP; [ "$TASKS" -lt 1 ] && TASKS=1
fi
say "$INFO → $TASKS video slices$([ "$AUDIO" = 1 ] && echo ' + 1 audio task'), bundle $(du -h "$STAGE/bundle.tgz" | cut -f1)"

REMOTE="gs://$BUCKET/renders/$RID"
gcloud storage cp "$STAGE/bundle.tgz" "$REMOTE/bundle.tgz" "${G[@]}" --quiet
[ -n "$PROPS" ] && gcloud storage cp "$PROPS" "$REMOTE/props.json" "${G[@]}" --quiet

EXEC="$(gcloud run jobs execute "$JOB" --region "$REGION" "${G[@]}" --async --tasks $(( TASKS + AUDIO )) \
  --update-env-vars "RENDER_ID=$RID,COMPOSITION=$COMP,VIDEO_TASKS=$TASKS,AUDIO=$AUDIO$EXTRA" --format 'value(metadata.name)')"
say "execution $EXEC started"
while true; do
  STATE="$(gcloud run jobs executions describe "$EXEC" --region "$REGION" "${G[@]}" --format json)"
  read -r DONE OK FAIL RUN <<<"$(echo "$STATE" | python3 -c 'import json,sys
s=json.load(sys.stdin).get("status",{})
print(s.get("completionTime","-"), s.get("succeededCount",0), s.get("failedCount",0), s.get("runningCount",0))')"
  say "  succeeded $OK · running $RUN · failed $FAIL / $(( TASKS + AUDIO ))"
  [ "$DONE" != "-" ] && break
  sleep 15
done
if [ "$FAIL" != "0" ]; then
  echo "render failed; task errors:"
  gcloud logging read "resource.type=cloud_run_job AND labels.\"run.googleapis.com/execution_name\"=\"$EXEC\" AND severity>=ERROR" \
    "${G[@]}" --limit 40 --format 'value(textPayload)' | head -80
  exit 1
fi

mkdir -p "$STAGE/parts" "$STAGE/stats"
gcloud storage cp "$REMOTE/parts/*" "$STAGE/parts/" "${G[@]}" --quiet
gcloud storage cp "$REMOTE/stats/*" "$STAGE/stats/" "${G[@]}" --quiet
ls "$STAGE"/parts/v_*.mp4 | sort | sed "s/.*/file '&'/" > "$STAGE/list.txt"
FF() { (cd "$PROJ" && npx remotion ffmpeg -hide_banner -loglevel error -nostdin -y "$@"); }
FF -f concat -safe 0 -i "$STAGE/list.txt" -c copy "$STAGE/video.mp4"
if [ "$AUDIO" = 1 ]; then
  FF -i "$STAGE/video.mp4" -i "$STAGE/parts/audio.wav" -map 0:v -map 1:a -c:v copy -af apad -c:a aac -b:a 320k \
    -ar 48000 -t "$DUR" -movflags +faststart "$OUT"
else
  FF -i "$STAGE/video.mp4" -c copy -movflags +faststart "$OUT"
fi
GOT="$(cd "$PROJ" && npx remotion ffprobe -v error -select_streams v:0 -count_packets -show_entries stream=nb_read_packets -of csv=p=0 "$OUT" | tr -cd '0-9')"
[ "$GOT" = "$FRAMES" ] && say "verified $GOT/$FRAMES frames" || { say "FRAME COUNT MISMATCH: $GOT vs $FRAMES"; exit 1; }

python3 "$HERE/cost.py" "$EXEC" --stats "$STAGE/stats" --json "$OUT.render.json"
say "done: $OUT ($(du -h "$OUT" | cut -f1)), $(( $(date +%s) - T0 )) s end to end. Cloud copy is deleted after 7 days."
