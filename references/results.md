# Measured results (2026-11-23)

Setup: project in us-central1, image `remotion-render:4.0.484` (Remotion 4.0.484, Chrome Headless Shell,
`gl: swangle`), tasks 4 vCPU / 8 GiB, jpeg frames at quality 90, h264 at Remotion's default CRF. Local machine
for comparison: Intel i5-6500 (4 cores, 2015), 23 GB RAM, Linux.

## Renders

| Render | Frames | Tasks | Waiting for tasks to start | Task run (wall) | End to end | Compute (list, 1-min minimum) |
|---|---|---|---|---|---|---|
| Test A (animated charts, glow lockup), 42 s | 1,274 | 5 video + audio | 76 s (first run of the image) | 180 s | ~5 min | $0.046 |
| Test B (product UI captures), 60 s, run 1 | 1,815 | 7 video + audio | ~80 s | 59 s | 3 min (join failed, see below) | $0.042 |
| Test B, run 2 | 1,815 | 7 video + audio | ~115 s | 60 s | 210 s | $0.042 |
| Test B, run 3 (copy edits) | 1,815 | 7 video + audio | ~30 s | 61 s | **127 s** | **$0.042** |
| Forced failure (1 muted task, bad timeout, 3 attempts) | – | 1 | ~50 s | 195 s | exit 1 + error printed | $0.017 |

All of these fit well inside the monthly jobs free tier (under 1% each), so the compute bill is $0.
"End to end" runs from the command to a verified local MP4: check, bundle (6 s), upload (17 MB), scheduling,
tasks, download, join, verify.

Per-task speed: 5.2–12 frames/s per 4-vCPU task on the Test B video (heavier text-dense slices are the
slow ones), 7.4–10 frames/s on Test A except its glow lockup slice at 1.5 frames/s, which alone set the
180 s wall. Each task spends ~9–11 s outside rendering (bundle extract 0.5 s, `selectComposition` 4 s, Chrome
start, upload). The audio task (wav, full length) took 41 s and 95 s.

## Local vs cloud speed

The same 260-frame slice (frames 520–779) of the Test B video: **49.6 s locally** (4 cores,
concurrency 4, including a 6 s bundle) vs **44.6 s of rendering in one cloud task**. One 4-vCPU task ≈ this
desktop. The gain is parallelism: 7 slices + audio at once.

- 60-s video: ~6 min locally (estimated from the slice) vs 3.5 min in the cloud, of which ~1.5–2 min is Cloud
  Run scheduling. Short videos gain little.
- 10-min video (a 10-minute explainer, 17,674 frames): 2 h 25 min locally on 2026-11-06. In the cloud, the 10-task cap
  gives ~1,960 frames per slice; at that film's local rate (~2.6 frames/s) that is ~13 min of task time plus
  ~2 min of overhead (estimate, not yet run).

## Quality

| Comparison | Frames | PSNR mean (worst) | SSIM mean (worst) |
|---|---|---|---|
| Test A: local render (gl `angle`) vs cloud (`swangle`) | 1,274 | 44.2 dB (42.5) | 0.993 (0.988) |
| Test B slice 520–779: local vs cloud, both `swangle` | 260 | 48.2 dB (46.1) | 0.996 (0.994) |

Both are visually identical; differences are encoder-level noise and text antialiasing.

## Failures met and fixed

1. **Cloud Build `PERMISSION_DENIED … serviceusage.services.use`** twice, right after enabling the API, with an
   Owner account. A trivial `--no-source` build succeeded ~6 minutes after enablement and the real build then
   went through. Cause: API enablement propagation. Fix: documented; re-run setup.
2. **Frame count "mismatch: 1274 vs 1274"**: ffprobe's csv printed `1274,`. Fix: strip non-digits.
3. **1,811 of 1,815 frames after the audio mux.** Parts summed to 1,815 and the concat had 1,815; the wav was
   16 samples short of 60.5 s, and `-shortest` let the AAC stream's end cut 4 video frames. Fix: `-af apad -t
   <frames/fps>` instead of `-shortest`; run 2 verified 1,815/1,815.
4. **`cost.py` under-counted short tasks**: it billed each task's own run time. Google bills jobs for the
   instance lifetime with a 1-minute minimum (cloud.google.com/run/pricing); the corrected figures are above
   ($0.034 → $0.042 for Test B).
5. **Failure log printed nothing**: task stderr reaches Cloud Logging with no severity, so `severity>=ERROR`
   matched nothing. Fix: select the execution's `run.googleapis.com/stderr` stream. Also lowered the default
   `MAX_RETRIES` to 1: a deterministic error burned 3 billed minutes and ~3 minutes of retry scheduling.
6. **`compare.sh` silent failure**: Remotion's bundled ffmpeg has no psnr/ssim filters. Fix: use a full ffmpeg
   (`FFMPEG`, PATH, or `imageio-ffmpeg`).
