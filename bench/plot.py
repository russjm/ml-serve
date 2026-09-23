import argparse
import csv
import os

import matplotlib

matplotlib.use("Agg")
import matplotlib.pyplot as plt  # noqa: E402


def read_history(run, results):
    path = os.path.join(results, run, "run_stats_history.csv")
    with open(path) as f:
        rows = [r for r in csv.DictReader(f) if r["Name"] == "Aggregated"]
    
    return [r for r in rows if r["50%"] != "N/A" and float(r["Requests/s"]) > 0]


def read_summary(run, results):
    with open(os.path.join(results, run, "run_stats.csv")) as f:
        return next(r for r in csv.DictReader(f) if r["Name"] == "Aggregated")


def batching_speedup(results, out):
    labels = {
        "no-batching": "no batching",
        "batching": "batch 32",
        "cache": "batch 32\n+ 90% cache hits",
    }
    rps = [float(read_summary(run, results)["Requests/s"]) for run in labels]

    fig, ax = plt.subplots(figsize=(6, 4))
    bars = ax.bar(list(labels.values()), rps, color="#4c72b0", width=0.55)
    ax.bar_label(bars, fmt="%.0f req/s", padding=3)
    ax.set_ylabel("throughput (req/s)")
    ax.set_title("Throughput, one pod, 64 concurrent clients")
    ax.set_ylim(0, max(rps) * 1.18)
    ax.spines[["top", "right"]].set_visible(False)
    fig.tight_layout()
    fig.savefig(os.path.join(out, "batching_speedup.png"), dpi=150)


def autoscaling(results, out):
    hist = read_history("burst", results)
    t0 = float(hist[0]["Timestamp"])
    t = [float(r["Timestamp"]) - t0 for r in hist]
    rps = [float(r["Requests/s"]) for r in hist]
    p95 = [float(r["95%"]) for r in hist]

    with open(os.path.join(results, "burst", "replicas.csv")) as f:
        rows = list(csv.DictReader(f))
    rt = [float(r["timestamp"]) - t0 for r in rows]
    ready = [int(r["ready"]) for r in rows]

    fig, (top, bottom) = plt.subplots(
        2, 1, figsize=(8, 5.5), sharex=True, height_ratios=[2, 1]
    )
    top.plot(t, rps, color="#4c72b0", label="throughput (req/s)")
    top.set_ylabel("throughput (req/s)", color="#4c72b0")
    top.tick_params(axis="y", labelcolor="#4c72b0")
    top.set_ylim(bottom=0)

    lat = top.twinx()
    lat.plot(t, p95, color="#dd8452", label="P95 latency (ms)")
    lat.set_ylabel("P95 latency (ms)", color="#dd8452")
    lat.tick_params(axis="y", labelcolor="#dd8452")
    lat.set_ylim(bottom=0)

    bottom.step(rt, ready, where="post", color="#55a868")
    bottom.set_ylabel("ready\nreplicas")
    bottom.set_ylim(0, max(ready) + 1)
    bottom.set_yticks(range(0, max(ready) + 2))
    bottom.set_xlabel("seconds since load start")

    for ax in (top, lat, bottom):
        ax.spines[["top"]].set_visible(False)
    bottom.spines[["right"]].set_visible(False)

    lines = top.get_lines() + lat.get_lines()
    top.legend(lines, [ln.get_label() for ln in lines], loc="upper left", frameon=False)
    top.set_title("Burst from 25 to 200 users, HPA 2-4 replicas")
    fig.tight_layout()
    fig.savefig(os.path.join(out, "autoscaling.png"), dpi=150)


def latency_percentiles(results, out):
    labels = {
        "no-batching": "no batching",
        "batching": "batch 32",
        "cache": "batch 32\n+ 90% cache hits",
    }
    pcts = ["50%", "95%", "99%"]
    colors = ["#4c72b0", "#dd8452", "#c44e52"]

    fig, ax = plt.subplots(figsize=(6.5, 4))
    width = 0.26
    for i, (p, c) in enumerate(zip(pcts, colors)):
        vals = [float(read_summary(run, results)[p]) for run in labels]
        pos = [x + (i - 1) * width for x in range(len(labels))]
        bars = ax.bar(pos, vals, width=width, color=c, label=f"P{p[:-1]}")
        ax.bar_label(bars, fmt="%.0f", padding=2, fontsize=8)

    ax.set_xticks(range(len(labels)), list(labels.values()))
    ax.set_ylabel("latency (ms)")
    ax.set_title("Latency, one pod, 64 concurrent clients")
    ax.legend(frameon=False)
    ax.spines[["top", "right"]].set_visible(False)
    fig.tight_layout()
    fig.savefig(os.path.join(out, "latency_percentiles.png"), dpi=150)


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--results", default="bench/results")
    ap.add_argument("--out", default="docs")
    args = ap.parse_args()

    os.makedirs(args.out, exist_ok=True)
    batching_speedup(args.results, args.out)
    autoscaling(args.results, args.out)
    latency_percentiles(args.results, args.out)
    print(f"wrote 3 charts to {args.out}/")


if __name__ == "__main__":
    main()
