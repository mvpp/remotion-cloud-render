# remotion-cloud-render

Render [Remotion](https://www.remotion.dev) videos on your own Google Cloud project. Your machine only bundles,
uploads and joins; the frames render in parallel **Cloud Run Job** tasks (4 vCPU / 8 GiB each, up to 10 at a
time), and nothing runs or bills between renders.

It is a skill: an instruction file for coding agents (Claude Code, Codex, …) plus scripts a person can run
directly. Forked from [garycaogan/gary-hf-cloud-render](https://github.com/garycaogan/gary-hf-cloud-render), which
does the same for HyperFrames; the render engine, setup and cost model here are Remotion-specific.

## Why

A 10-minute 1080p Remotion video took 2 h 25 min on a 4-core desktop (Nov 2026, chunked local render).
Split across cloud tasks, the wall time is the slowest slice plus ~1.5 minutes of scheduling and upload, and the
compute bill is a few cents per minute of video (list price; jobs bill at least one minute per task). Cloud
Run's jobs free tier (~15.6 task-hours a month) plus the $10 Cloud credit in Google AI Pro cover roughly six
hours of 1080p UI-style video a month ([references/cost.md](references/cost.md)).

| Measured 2026-11-23 | Frames | Wall (execution) | Compute (list price) |
|---|---|---|---|
| Test A, 42 s, 1080p30 | 1,274 | 3.0 min (6 tasks) | $0.046 |
| Test B, 60 s, 1080p30 | 1,815 | 1.0 min (8 tasks); 3.5 min end to end | $0.042 |

Quality vs a local render of the same project: PSNR 44.2–48.2 dB, SSIM 0.993–0.996 (visually identical).
Details: [references/results.md](references/results.md).

## How it works

```
local                                   Google Cloud (your project)
─────                                   ───────────────────────────
check_project.py
npx remotion bundle ──► bundle.tgz ───► gs://<project>-remotion-render/renders/<id>/   (7-day expiry)
gcloud run jobs execute --tasks N+1 ──► task 0..N-1: renderMedia(frameRange slice, muted h264)
                                         task N:      renderMedia(codec wav)            ──► parts/
download parts ◄────────────────────────
ffmpeg concat -c copy + AAC mux → verify frame count → cost.py
```

The image (`container/`) holds Chrome Headless Shell, Remotion's renderer and compositor at your project's exact
version, plus Noto/CJK/emoji fonts. It never contains your project: each render uploads its own bundle, which
the tasks read through a Cloud Storage volume mount.

## Use

```bash
git clone https://github.com/mvpp/remotion-cloud-render ~/.claude/skills/remotion-cloud-render
export PROJECT=<your GCP project id>          # billing enabled; credits land on its billing account
bash scripts/setup_gcp.sh --from ./my-video   # once per Remotion version (~3 min)

bash scripts/cloud_render.sh ./my-video MyComposition                  # → my-video/out/MyComposition.cloud.mp4
bash scripts/cloud_render.sh ./my-video MyComposition --props p.json --out final.mp4
bash scripts/compare.sh local.mp4 my-video/out/MyComposition.cloud.mp4  # optional quality check
```

Needs `gcloud` (logged in), Node.js and the project's own `node_modules`, Python 3. No Docker, Terraform or
system ffmpeg. Full setup, options and teardown: [references/setup.md](references/setup.md).

## Files

- `SKILL.md` — entry point for agents.
- `container/` — Dockerfile, task entry (`task.mjs`), Cloud Build config.
- `scripts/setup_gcp.sh` — create/update bucket, service account, registry, image, job.
- `scripts/cloud_render.sh` — one-command render; `scripts/probe.mjs` — composition length.
- `scripts/cost.py` — per-task cost of an execution; `scripts/check_project.py` — pre-flight check.
- `scripts/compare.sh` — PSNR/SSIM against a local render.
- `references/` — setup, cost, measured results. `SECURITY.md` — what the setup grants.

## License

MIT (see [LICENSE](LICENSE)), as the original. Remotion has its own license: free for individuals and companies
with up to 3 employees, a company license otherwise (remotion.dev/license).
