# Setup from zero

Steps marked **(you)** happen in a browser: they involve payment methods, subscriptions, terms or sign-in, and
neither a script nor an agent should do them for you. Everything else can run from the command line.

## 1. Monthly Cloud credit (you)

Google AI Pro / Ultra subscriptions include a monthly Google Cloud credit through the Google Developer Program:
AI Pro $10, AI Ultra 5x $40, AI Ultra 20x $100 (as of November 2026; check
https://developers.google.com/profile/help/benefits).

1. Use the same Google account for the subscription and the Developer Program profile.
2. On the benefits page (me.developers.google.com/benefits), send the Cloud credit to a billing account and tick
   "always use this billing account".
3. Each grant lasts 12 months from issue, so unused credit carries forward within that year.

## 2. Project and billing (you)

- Use a project linked to that billing account. A dedicated project keeps the bill readable and is easy to delete.
- Optional: a budget alert (Billing → Budgets & alerts). Budgets only send email; the real guards are the job's
  parallelism cap and task timeout.

## 3. Tools

- Google Cloud CLI (`gcloud`), logged in: `gcloud auth login`.
- Node.js 18+ and the Remotion project's own `node_modules` (the scripts use its CLI, renderer and ffmpeg).
- Python 3. For `compare.sh` only: a full ffmpeg, or `pip install imageio-ffmpeg`.
- No Docker, Terraform or local ffmpeg needed: the image builds on Cloud Build.

## 4. Build and deploy (once per Remotion version)

```bash
PROJECT=<project id> bash scripts/setup_gcp.sh --from ./my-video      # reads the Remotion version from the project
PROJECT=<project id> REMOTION_VERSION=4.0.484 bash scripts/setup_gcp.sh --dry-run   # print the commands only
```

It enables Run, Artifact Registry, Cloud Build, Storage and Logging; creates the bucket
`<project>-remotion-render` (private, files deleted after 7 days), the service account `remotion-render` (bucket
access only) and the registry `remotion`; builds `remotion-render:<version>-<hash>` on Cloud Build (~1.5 min);
and creates or updates the Cloud Run Job `remotion-render` (4 vCPU / 8 GiB per task, up to 10 tasks at once,
1-hour task timeout, 2 retries, bucket mounted at `/mnt/render`). Settings go to
`~/.config/remotion-cloud-render/config.env`.

Env overrides: `REGION`, `BUCKET`, `JOB`, `TASK_CPU`, `TASK_MEMORY`, `MAX_PARALLEL`, `TASK_TIMEOUT`, `MAX_RETRIES`.
Re-run after editing `container/` (the image tag carries a hash of it) or when the project's Remotion version
changes; `cloud_render.sh` refuses a project whose version differs from the job's image.

If Cloud Build answers `PERMISSION_DENIED … serviceusage.services.use` right after the APIs were enabled, wait a
few minutes and re-run: the new API is still propagating (seen twice on 2026-11-23, gone on the third try).

## 5. Render

```bash
bash scripts/cloud_render.sh ./my-video MyComposition                       # → my-video/out/MyComposition.cloud.mp4
bash scripts/cloud_render.sh ./my-video MyComposition --props props.json --out final.mp4
bash scripts/cloud_render.sh ./my-video MyComposition --env SCALE=2         # 4K from a 1080p composition
bash scripts/cloud_render.sh ./my-video MyComposition --frames-per-task 150 # smaller slices: better balance on uneven scenes
bash scripts/compare.sh local.mp4 my-video/out/MyComposition.cloud.mp4      # PSNR / SSIM against a local render
```

What happens: pre-flight check → `npx remotion bundle` (applies the project's webpack overrides; `public/` goes
inside) → upload one tarball → one job execution with N video slices + 1 audio task → download → `ffmpeg concat
-c copy` → AAC audio → frame count verified → cost table (also saved as `<out>.render.json`).

Render settings the tasks use (the Node API ignores `remotion.config.ts`): h264, jpeg frames at quality 90,
`gl: swangle`, concurrency = task vCPUs. Change them per render with `--env CONCURRENCY=… JPEG_QUALITY=… CRF=…
X264_PRESET=… SCALE=…`.

## 6. Tear down

```bash
gcloud run jobs delete remotion-render --region us-central1 --project $PROJECT
gcloud artifacts repositories delete remotion --location us-central1 --project $PROJECT
gcloud storage rm -r gs://$PROJECT-remotion-render --project $PROJECT
gcloud iam service-accounts delete remotion-render@$PROJECT.iam.gserviceaccount.com --project $PROJECT
rm ~/.config/remotion-cloud-render/config.env
```

Left in place, the idle cost is the image storage in Artifact Registry (see cost.md); the job itself costs
nothing while no execution runs.
