#!/usr/bin/env bash
# Frame-by-frame quality check of two renders: mean PSNR and SSIM, the 5 worst frames, and one still from
# the middle of each for a visual check.
# Usage: compare.sh <reference.mp4> <candidate.mp4> [output dir]
# Needs a full ffmpeg (psnr/ssim filters): $FFMPEG, else `ffmpeg` on PATH, else the static build of the
# Python package imageio-ffmpeg (PYTHON, default python3). Remotion's bundled ffmpeg lacks these filters.
set -euo pipefail
[ $# -ge 2 ] || { sed -n 2,6p "$0"; exit 1; }
A="$1"; B="$2"; DIR="${3:-compare-$(date +%H%M%S)}"
mkdir -p "$DIR"
FF="${FFMPEG:-$(command -v ffmpeg || "${PYTHON:-python3}" -c 'import imageio_ffmpeg; print(imageio_ffmpeg.get_ffmpeg_exe())' 2>/dev/null || true)}"
[ -n "$FF" ] || { echo "need a full ffmpeg: install one, set FFMPEG=…, or pip install imageio-ffmpeg"; exit 1; }
"$FF" -v error -nostdin -i "$A" -i "$B" -lavfi \
  "[0:v]split[a1][a2];[1:v]split[b1][b2];[a1][b1]psnr=stats_file=$DIR/psnr.log;[a2][b2]ssim=stats_file=$DIR/ssim.log" \
  -shortest -f null - 2>/dev/null || true
python3 - "$DIR" <<'PY'
import re, sys
d = sys.argv[1]
def load(name, key):
    rows = []
    for line in open(f"{d}/{name}"):
        n = re.search(r"n:(\d+)", line); v = re.search(key + r":([\d.]+|inf)", line)
        if n and v:
            rows.append((int(n.group(1)), float(v.group(1))))
    return rows
p = load("psnr.log", "psnr_avg"); s = load("ssim.log", "All")
fin = [v for _, v in p if v != float("inf")]
print(f"compared {len(p)} frames")
print(f"PSNR mean {sum(fin)/max(len(fin),1):.2f} dB, worst 5 {sorted(p, key=lambda x: x[1])[:5]}")
print(f"SSIM mean {sum(v for _, v in s)/max(len(s),1):.4f}, worst 5 {sorted(s, key=lambda x: x[1])[:5]}")
print("guide: ≥ 40 dB / SSIM ≥ 0.98 is visually identical; text-edge antialiasing alone can pull the mean to 35-42 dB")
PY
T="$("$FF" -hide_banner -i "$A" 2>&1 | sed -n 's/.*Duration: \([0-9:.]*\).*/\1/p' | awk -F: '{print ($1*3600+$2*60+$3)/2}')"
"$FF" -v error -nostdin -y -ss "$T" -i "$A" -frames:v 1 -q:v 2 "$DIR/a.jpg"
"$FF" -v error -nostdin -y -ss "$T" -i "$B" -frames:v 1 -q:v 2 "$DIR/b.jpg"
echo "middle stills: $DIR/a.jpg, $DIR/b.jpg"
