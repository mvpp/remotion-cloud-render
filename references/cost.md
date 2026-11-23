# What a render costs, and what $10 a month buys

Prices and billing rules are us-central1 list values read on 2026-11-23 from cloud.google.com/run/pricing and
the Cloud Billing Catalog API (Google changes them; re-check). Measured numbers come from
[results.md](results.md).

## Billing rules that matter

- "Cloud Run jobs are billed at the Instance-based billing rate, for the entire lifetime of any instance
  started, **with a minimum of 1 minute**", rounded up to 100 ms. A task that renders for 30 s still bills 60 s,
  so slices should carry at least ~45 s of rendering (the default 300 frames does for 1080p UI scenes).
- **Jobs free tier:** first 240,000 vCPU-seconds and 450,000 GiB-seconds per month, pooled per billing account
  across all its projects. A 4 vCPU / 8 GiB task runs out of memory-seconds first: 56,250 task-seconds ≈
  **15.6 task-hours a month free**.
- The free tier applies before credits; the AI Pro credit covers what is left.

## Unit prices

| Item | Source | Price | Free each month |
|---|---|---|---|
| Job task CPU | run/pricing; SKU "Jobs CPU in us-central1" | $0.000018 per vCPU-second | 240,000 vCPU-s |
| Job task memory | run/pricing; SKU "Jobs Memory in us-central1" | $0.000002 per GiB-second | 450,000 GiB-s |
| Image build | SKU "Build time e2-standard-2" | $0.006 per minute | first 2,500 minutes |
| Image storage | SKU "Artifact Registry Storage" | $0.10 per GiB-month | first 0.5 GiB |
| Bucket storage | Cloud Storage Standard, us-central1 | ~$0.02 per GiB-month | — |
| Download to your machine | internet egress | ~$0.12 per GiB (North America) | — |

One task (4 vCPU / 8 GiB) = 4 × 0.000018 + 8 × 0.000002 = **$0.000088 per second = $0.32 per hour**, minimum
$0.0053 per task. The catalog also lists cheaper "Delayed Jobs" SKUs ($0.0000126 / $0.0000014, dynamic prices);
this skill does not use them.

## Fixed costs

- Image: `remotion-render:4.0.484` is 0.34 GB compressed, under the 0.5 GiB free tier → **$0**. A second Remotion
  version adds ~0.34 GB; delete old tags to stay free.
- Build: ~1.5 minutes per image, inside the free 2,500 minutes → **$0**.
- Bucket: renders delete after 7 days; a 1-minute 1080p render is ~30 MB → fractions of a cent.
- Idle job: $0. Nothing is kept warm.

## Per render (measured, list price before free tier)

| Render | Frames | Billed task-seconds | Compute | Per 1,000 frames |
|---|---|---|---|---|
| Test A, 1080p30, 42 s (5 slices + audio) | 1,274 | 526 | $0.046 | $0.036 |
| Test B, 1080p30, 60 s (7 slices + audio), run 1 | 1,815 | 480 | $0.042 | $0.023 |
| Test B, run 2 | 1,815 | 480 | $0.042 | $0.023 |

Each used under 1% of the monthly free tier, so their compute bill is $0. Download adds ~$0.003–0.005 per
minute of 1080p video (25–40 MB at ~$0.12 per GiB).

## What a month buys (AI Pro: $10 credit)

At Test B's rate (480 billed task-seconds per 1,815 frames, ≈ 3.8 frames per billed task-second):

| Budget | Task-hours | 1080p30 video (UI/chart scenes) |
|---|---|---|
| Free tier | 15.6 | ~118 minutes |
| $10 credit at $0.32/task-hour | 31 | ~240 minutes |
| Both | ~47 | **~6 hours a month** |

Heavier scenes cost more per frame: a 10-minute film that renders at ~2.6 frames/s per task needs ~1.9 billed
task-hours (~$0.60 at list price) per full render, so the same month covers ~25 full renders of it. 4K
(`--env SCALE=2`) draws 4× the pixels; expect 3–4× the cost. The free tier and the credit are shared with
everything else on the billing account (other projects' Cloud Run, Vertex/Gemini), so subtract that use.

## How the cost is measured

`scripts/cost.py <execution>` lists every task's start and completion time from the Cloud Run v2 API, applies
the 1-minute minimum and 100 ms rounding, and multiplies by the task size and prices above. It reports usage
against the free tier but does not subtract it. Container start-up before the task clock, and time spent in
retried attempts, are not visible to it. The Billing console shows the authoritative figure about a day later.
