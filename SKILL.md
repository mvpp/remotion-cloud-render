---
name: remotion-cloud-render
description: Render Remotion videos on your own Google Cloud (Cloud Run Jobs) instead of a slow local machine — frame slices render in parallel tasks, audio in its own task, then a lossless local join. One-time setup script (bucket, service account, image via Cloud Build, job), one-command render with frame-count check and a per-render cost table, a pre-flight project check, and a PSNR/SSIM comparison against a local render. Sized for the $10–100/month Google Cloud credit that comes with Google AI Pro/Ultra. Use for "render this Remotion video in the cloud", "my machine is too slow to render", "use my Google Cloud credits to render", Cloud Run rendering, distributed Remotion rendering on GCP.
---

# remotion-cloud-render

A Remotion render is a headless Chrome screenshotting every frame, then an encoder. It is CPU-bound and splits
cleanly by frame range. This skill runs those slices as parallel tasks of one **Cloud Run Job** on your own GCP
project, renders the audio track as one more task, and joins the parts locally with `ffmpeg concat -c copy`, the
same shape as a local `remotion render --frames=a-b --muted` loop. Nothing stays running between renders.

Fork of [garycaogan/gary-hf-cloud-render](https://github.com/garycaogan/gary-hf-cloud-render) (HyperFrames on
Cloud Run). Remotion's own `@remotion/cloudrun` renders on a single instance and is not actively developed
(remotion.dev/docs/cloudrun/status), so this fork uses Remotion's renderer API inside its own job instead.

## When to use

- Long videos, 4K, repeated full re-renders, or a machine that is busy or slow.
- Not worth it for a 5-second check: every execution waits ~75 s for Cloud Run to schedule its tasks, plus the
  bundle upload. Render short previews locally and send the full cut to the cloud.

## Flow

1. Once per project/Remotion version: `PROJECT=<id> bash scripts/setup_gcp.sh --from <remotion project>`
   (APIs, private bucket with 7-day expiry, bucket-only service account, image on Cloud Build, job). Details and
   teardown: [references/setup.md](references/setup.md).
2. Each render: `bash scripts/cloud_render.sh <project dir> <composition> [--props f.json] [--out f.mp4]`.
   It checks the project, bundles, uploads, executes, polls, downloads, joins, verifies the frame count and prints
   the cost table (also `<out>.render.json`).
3. Optional quality check: `bash scripts/compare.sh local.mp4 cloud.mp4`.

## Rules learned the hard way

- **Same Remotion version** in the project and the image; `cloud_render.sh` refuses a mismatch and prints the
  setup command that fixes it.
- **The Node API ignores `remotion.config.ts`.** Tasks pass h264, jpeg quality 90, `gl: swangle` and concurrency
  = vCPUs explicitly. A project that sets `angle` (needs a GPU) still renders the same pixels on `swangle`.
  Per-render overrides: `--env CONCURRENCY=… JPEG_QUALITY=… CRF=… X264_PRESET=… SCALE=2`.
- **Fonts:** the image has Noto (incl. CJK and color emoji) and Liberation. Anything else must be loaded by the
  project (`@remotion/google-fonts`, `staticFile` + FontFace). Google Fonts loads fine at render time.
- **Uneven scenes skew the wall time**: the slowest slice sets it (one heavy lockup slice ran at 1.5 fps vs 8–10
  for the rest). Use `--frames-per-task 150` for long videos with heavy segments.
- **Remotion's bundled ffmpeg is minimal** (no psnr/ssim filters); `compare.sh` uses a full ffmpeg or
  `imageio-ffmpeg`. The join itself works with Remotion's ffmpeg.
- **`npx remotion bundle --help` runs a bundle** into `./build`; don't probe it that way.
- Fresh API enablement can make Cloud Build return `PERMISSION_DENIED … serviceusage.services.use` for a few
  minutes; re-run setup.

## Results and cost

Measured on 2026-11-23 (us-central1, 4 vCPU / 8 GiB tasks), see [references/results.md](references/results.md)
and [references/cost.md](references/cost.md):

- Cloud vs local quality: PSNR 44.2 dB, SSIM 0.993 over 1,274 frames (visually identical).
- $0.019–0.030 per 1,000 1080p frames on UI and chart scenes → $10 of credit ≈ 170–250 minutes of 1080p video.
- One 4-vCPU task renders about as fast as a 4-core desktop; the speed-up is the parallel slices. Every
  execution also waits ~75–115 s for Cloud Run to start its tasks.
- Mux audio with `-t <frames/fps>`, never `-shortest` (it cut 4 frames off a 1,815-frame render).

## Files

- `container/Dockerfile`, `container/task.mjs`, `container/cloudbuild.yaml` — the render task image.
- `scripts/setup_gcp.sh` — create/update everything on GCP; writes `~/.config/remotion-cloud-render/config.env`.
- `scripts/cloud_render.sh` — one-command render; `scripts/probe.mjs` reads the composition length.
- `scripts/cost.py` — per-task cost of an execution.
- `scripts/check_project.py` — pre-flight check; `scripts/compare.sh` — PSNR/SSIM vs a local render.
