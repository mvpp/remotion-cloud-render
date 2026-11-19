#!/usr/bin/env bash
# 两份视频逐帧比画质：PSNR 和 SSIM 的平均值、最差的 5 帧，再各截一张同一时刻的图方便肉眼看。
# 用法: compare.sh <基准.mp4> <待比.mp4> [输出目录]
# 帧数差 1 很正常（云端按时长向上取整出帧），按短的那份比。
set -euo pipefail
[ $# -ge 2 ] || { sed -n 2,4p "$0"; exit 1; }
A="$1"; B="$2"; DIR="${3:-compare-$(date +%H%M%S)}"
mkdir -p "$DIR"
ffmpeg -v error -nostdin -i "$A" -i "$B" -lavfi \
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
print(f"比了 {len(p)} 帧")
print(f"PSNR 平均 {sum(fin)/max(len(fin),1):.2f} dB，最差 5 帧 {sorted(p, key=lambda x: x[1])[:5]}")
print(f"SSIM 平均 {sum(v for _, v in s)/max(len(s),1):.4f}，最差 5 帧 {sorted(s, key=lambda x: x[1])[:5]}")
print("参考：纯背景 50 dB 上下等于没差别；文字边缘抗锯齿不同会把平均 PSNR 拉到 35–42 dB，要放大截图看字形。")
PY
T="$(ffprobe -v error -show_entries format=duration -of csv=p=0 "$A" | awk '{print $1/2}')"
ffmpeg -v error -nostdin -y -ss "$T" -i "$A" -frames:v 1 -q:v 2 "$DIR/a.jpg"
ffmpeg -v error -nostdin -y -ss "$T" -i "$B" -frames:v 1 -q:v 2 "$DIR/b.jpg"
echo "中间那一帧截图：$DIR/a.jpg、$DIR/b.jpg"
