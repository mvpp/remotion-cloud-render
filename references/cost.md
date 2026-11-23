# What a render costs, and what $10 a month buys

Prices are us-central1 list prices read from the Cloud Billing Catalog API on 2026-11-23 (Google changes them;
re-check with the SKU names below). Measured numbers come from [results.md](results.md).

## Unit prices

| Item | SKU (Billing Catalog) | Price | Free each month |
|---|---|---|---|
| Job task CPU | Cloud Run · "Jobs CPU in us-central1" | $0.000018 per vCPU-second | see note |
| Job task memory | Cloud Run · "Jobs Memory in us-central1" | $0.000002 per GiB-second | see note |
| Image build | Cloud Build · "Build time e2-standard-2" | $0.006 per minute | first 2,500 minutes |
| Image storage | Artifact Registry · "Artifact Registry Storage" | $0.10 per GiB-month | first 0.5 GiB |
| Bucket storage | Cloud Storage, Standard, us-central1 | ~$0.02 per GiB-month | — |
| Download to your machine | Internet egress | ~$0.12 per GiB (North America) | — |

One task (4 vCPU / 8 GiB) costs 4 × 0.000018 + 8 × 0.000002 = **$0.000088 per second = $0.32 per hour**.
Cloud Run's monthly free tier is not subtracted anywhere here, so real bills can be lower. Note: the catalog also
lists cheaper "Delayed Jobs" SKUs ($0.0000126 / $0.0000014); this skill does not use them.

## Fixed costs

- Image: `remotion-render:4.0.484` is 0.34 GB compressed, under the 0.5 GiB free tier → **$0**. A second Remotion
  version adds another ~0.34 GB; delete old tags to stay free.
- Build: ~1.5 minutes per image, inside the free 2,500 minutes → **$0**.
- Bucket: renders delete after 7 days; a 1-minute 1080p render is ~30 MB → fractions of a cent.
- Idle job: $0. There is no service or instance kept warm.

## Per render (measured, see results.md)

| Render | Frames | Task-seconds | Compute | Per 1,000 frames |
|---|---|---|---|---|
| Test A, 1080p30, 42 s (5 slices + audio) | 1,274 | 440 | $0.039 | $0.030 |
| Test B, 1080p30, 60 s (7 slices + audio), run 1 | 1,815 | 391 | $0.034 | $0.019 |
| Test B, run 2 | 1,815 | 387 | $0.034 | $0.019 |

Download adds ~$0.002–0.005 per minute of 1080p video (25–40 MB at ~$0.12 per GiB).

## What $10 a month buys (AI Pro credit)

At the measured $0.019–0.030 per 1,000 frames (1080p30, UI and chart scenes), one minute of video
(1,800 frames) costs about **$0.04–0.06** including download. $10 covers roughly **170–250 minutes** of finished
1080p video a month, or 15–25 full re-renders of a 10-minute piece. 4K (`--env SCALE=2`) draws 4× the pixels;
expect roughly 3–4× the cost. Heavy scenes (blur, particles, WebGL on the software renderer) can cost several
times more per frame: render a 10-second slice first and read its cost table.

The same credit pays for Vertex/Gemini and anything else on that billing account, so share it accordingly.

## How the cost is measured

`scripts/cost.py <execution>` lists every task's start and completion time from the Cloud Run v2 API and
multiplies by the task size and the prices above. It does not subtract the free tier or credits, and it cannot
see time spent in retried attempts (none occurred in our runs). The Billing console shows the authoritative
number about a day later.
