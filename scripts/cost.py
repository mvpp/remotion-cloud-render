#!/usr/bin/env python3
"""Cost of one Cloud Run Jobs render execution, from each task's own start/end times.

Usage: cost.py <execution name> [--stats DIR] [--json OUT]
  --stats DIR   the task_*.json files task.mjs wrote (adds render seconds and frames per second per task)
  --json OUT    also save the full breakdown

Billing model, from cloud.google.com/run/pricing (read 2026-11-23): "Cloud Run jobs are billed at the
Instance-based billing rate, for the entire lifetime of any instance started, with a minimum of 1 minute",
usage "rounded up to the nearest 100 millisecond". So each task bills max(60 s, its lifetime). The task's
start→completion time from the v2 API stands in for the instance lifetime (container start-up before the task
clock is not visible). Prices: us-central1 list, $0.000018 per vCPU-second and $0.000002 per GiB-second (same
page and Cloud Billing Catalog SKUs "Jobs CPU/Memory in us-central1"); override with CPU_PRICE / MEM_PRICE.
Jobs free tier: first 240,000 vCPU-seconds and 450,000 GiB-seconds per month, pooled per billing account across
all its projects — shown as usage against it, not subtracted. Credits are not subtracted either.
Config (project, region, job, task size) comes from ~/.config/remotion-cloud-render/config.env.
"""
import argparse
import json
import math
import os
import subprocess
import urllib.request
from datetime import datetime
from pathlib import Path

CPU_PRICE = float(os.environ.get("CPU_PRICE", "0.000018"))   # $ per vCPU-second
MEM_PRICE = float(os.environ.get("MEM_PRICE", "0.000002"))   # $ per GiB-second
MIN_BILLED_S = 60.0                                           # per instance
FREE_VCPU_S, FREE_GIB_S = 240_000, 450_000                    # jobs free tier per month, per billing account


def billed(seconds):
    """Instance lifetime → billed seconds: rounded up to 0.1 s, at least one minute."""
    return max(MIN_BILLED_S, math.ceil(seconds * 10) / 10)


def load_config():
    path = Path(os.environ.get("CONFIG", Path.home() / ".config/remotion-cloud-render/config.env"))
    pairs = (line.split("=", 1) for line in path.read_text().splitlines() if "=" in line)
    return {k.strip(): v.strip() for k, v in pairs}


def gib(memory):
    """'8Gi' → 8.0, '512Mi' → 0.5."""
    units = {"Gi": 1.0, "Mi": 1 / 1024, "G": 1e9 / 2**30, "M": 1e6 / 2**30}
    for suffix, factor in units.items():
        if memory.endswith(suffix):
            return float(memory[: -len(suffix)]) * factor
    return float(memory) / 2**30


def ts(value):
    return datetime.fromisoformat(value.replace("Z", "+00:00")) if value else None


def list_tasks(cfg, execution):
    token = subprocess.run(["gcloud", "auth", "print-access-token"], capture_output=True, text=True, check=True).stdout.strip()
    url = (f"https://run.googleapis.com/v2/projects/{cfg['PROJECT']}/locations/{cfg['REGION']}/jobs/{cfg['JOB']}"
           f"/executions/{execution}/tasks?pageSize=1000")
    req = urllib.request.Request(url, headers={"Authorization": f"Bearer {token}"})
    return json.load(urllib.request.urlopen(req)).get("tasks", [])


def load_stats(directory):
    out = {}
    for f in sorted(Path(directory).glob("task_*.json")) if directory else []:
        s = json.loads(f.read_text())
        out[s["task"]] = s
    return out


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("execution")
    ap.add_argument("--stats")
    ap.add_argument("--json")
    args = ap.parse_args()
    cfg = load_config()
    cpu, mem = float(cfg.get("TASK_CPU", 4)), gib(cfg.get("TASK_MEMORY", "8Gi"))
    per_second = cpu * CPU_PRICE + mem * MEM_PRICE
    stats = load_stats(args.stats)

    rows, starts, ends = [], [], []
    for t in sorted(list_tasks(cfg, args.execution), key=lambda t: t.get("index", 0)):
        start, end = ts(t.get("startTime")), ts(t.get("completionTime"))
        seconds = (end - start).total_seconds() if start and end else 0.0
        starts += [start] if start else []
        ends += [end] if end else []
        s = stats.get(t.get("index", 0), {})
        frames = s.get("frames")
        n = frames[1] - frames[0] + 1 if frames else None
        rows.append({
            "task": t.get("index", 0), "kind": s.get("kind", "?"), "frames": n, "ran_s": round(seconds, 1),
            "billed_s": billed(seconds), "render_s": round(s.get("renderSec", 0), 1),
            "fps": round(n / s["renderSec"], 2) if n and s.get("renderSec") else None,
            "retried": t.get("retried", 0), "cost_usd": round(billed(seconds) * per_second, 5),
        })
    total_s = sum(r["billed_s"] for r in rows)
    wall = (max(ends) - min(starts)).total_seconds() if starts and ends else 0
    frames = sum(r["frames"] or 0 for r in rows)
    summary = {
        "execution": args.execution, "task_size": f"{cpu:g} vCPU / {mem:g} GiB", "price_per_task_hour": round(per_second * 3600, 4),
        "tasks": len(rows), "frames": frames, "task_seconds_billed": round(total_s, 1), "wall_seconds": round(wall, 1),
        "compute_usd_list": round(total_s * per_second, 4),
        "usd_per_1000_frames": round(total_s * per_second / frames * 1000, 4) if frames else None,
        "free_tier_share": {"vcpu_s": round(total_s * cpu), "of_vcpu_s": FREE_VCPU_S, "gib_s": round(total_s * mem), "of_gib_s": FREE_GIB_S},
        "rows": rows,
    }
    print(f"{'task':>4} {'kind':>5} {'frames':>6} {'ran s':>7} {'billed s':>8} {'render s':>8} {'fps':>5} {'retry':>5} {'cost $':>8}")
    for r in rows:
        print(f"{r['task']:>4} {r['kind']:>5} {r['frames'] or '-':>6} {r['ran_s']:>7} {r['billed_s']:>8} {r['render_s']:>8} "
              f"{r['fps'] or '-':>5} {r['retried']:>5} {r['cost_usd']:>8.4f}")
    print(f"{summary['tasks']} tasks × {summary['task_size']} · {total_s:.0f} billed task-seconds (1-min minimum each) · "
          f"wall {wall:.0f} s · ${summary['compute_usd_list']:.4f} at list price"
          + (f" · ${summary['usd_per_1000_frames']:.4f} per 1,000 frames" if frames else ""))
    print(f"jobs free tier this uses: {total_s * cpu:,.0f} of {FREE_VCPU_S:,} vCPU-s and {total_s * mem:,.0f} of "
          f"{FREE_GIB_S:,} GiB-s a month (pooled per billing account); inside it the bill is $0")
    if args.json:
        Path(args.json).write_text(json.dumps(summary, indent=1))


if __name__ == "__main__":
    main()
