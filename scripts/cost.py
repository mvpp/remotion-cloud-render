#!/usr/bin/env python3
"""Cost of one Cloud Run Jobs render execution, from each task's own start/end times.

Usage: cost.py <execution name> [--stats DIR] [--json OUT]
  --stats DIR   the task_*.json files task.mjs wrote (adds render seconds and frames per second per task)
  --json OUT    also save the full breakdown

Billing model (Cloud Run jobs, instance time): every task bills vCPU-seconds and GiB-seconds from its
container start to its exit. Prices are us-central1 list prices, read from the Cloud Billing Catalog API
(service 152E-C115-5142, SKUs "Jobs CPU in us-central1" and "Jobs Memory in us-central1") on 2026-11-23;
override with CPU_PRICE / MEM_PRICE env. Free tier, credits and retried attempts' earlier time are not
subtracted or added: the bill can be lower (free tier) or slightly higher (retries).
Config (project, region, job, task size) comes from ~/.config/remotion-cloud-render/config.env.
"""
import argparse
import json
import os
import subprocess
import urllib.request
from datetime import datetime
from pathlib import Path

CPU_PRICE = float(os.environ.get("CPU_PRICE", "0.000018"))   # $ per vCPU-second
MEM_PRICE = float(os.environ.get("MEM_PRICE", "0.000002"))   # $ per GiB-second


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
            "task": t.get("index", 0), "kind": s.get("kind", "?"), "frames": n, "billed_s": round(seconds, 1),
            "render_s": round(s.get("renderSec", 0), 1), "fps": round(n / s["renderSec"], 2) if n and s.get("renderSec") else None,
            "retried": t.get("retried", 0), "cost_usd": round(seconds * per_second, 5),
        })
    total_s = sum(r["billed_s"] for r in rows)
    wall = (max(ends) - min(starts)).total_seconds() if starts and ends else 0
    frames = sum(r["frames"] or 0 for r in rows)
    summary = {
        "execution": args.execution, "task_size": f"{cpu:g} vCPU / {mem:g} GiB", "price_per_task_hour": round(per_second * 3600, 4),
        "tasks": len(rows), "frames": frames, "task_seconds": round(total_s, 1), "wall_seconds": round(wall, 1),
        "compute_usd": round(total_s * per_second, 4),
        "usd_per_1000_frames": round(total_s * per_second / frames * 1000, 4) if frames else None,
        "rows": rows,
    }
    print(f"{'task':>4} {'kind':>5} {'frames':>6} {'billed s':>8} {'render s':>8} {'fps':>5} {'retry':>5} {'cost $':>8}")
    for r in rows:
        print(f"{r['task']:>4} {r['kind']:>5} {r['frames'] or '-':>6} {r['billed_s']:>8} {r['render_s']:>8} "
              f"{r['fps'] or '-':>5} {r['retried']:>5} {r['cost_usd']:>8.4f}")
    print(f"{summary['tasks']} tasks × {summary['task_size']} · {total_s:.0f} task-seconds · wall {wall:.0f} s · "
          f"compute ${summary['compute_usd']:.4f} (list price, before free tier/credits)"
          + (f" · ${summary['usd_per_1000_frames']:.4f} per 1,000 frames" if frames else ""))
    if args.json:
        Path(args.json).write_text(json.dumps(summary, indent=1))


if __name__ == "__main__":
    main()
