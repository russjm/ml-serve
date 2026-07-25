import argparse
import asyncio
import itertools
import random
import time

import httpx
import numpy as np

HOT = [
    "this movie was absolutely fantastic",
    "best dinner i've had all year",
    "i love this song so much",
    "what a waste of two hours",
    "the service was terrible and rude",
    "an underwhelming sequel to a great original",
    "delightful from start to finish",
    "would not recommend to anyone",
    "surprisingly enjoyable performance",
    "boring, predictable, and far too long",
]

counter = itertools.count()


def pick_text(rng, repeats, tag):
    if rng.random() < repeats:
        return rng.choice(HOT)
    # tag keeps parallel client processes from colliding on the same "unique" text
    return f"{rng.choice(HOT)} take {tag}-{next(counter)}"


async def worker(client, url, n, rng, repeats, tag, results):
    for _ in range(n):
        text = pick_text(rng, repeats, tag)
        t0 = time.perf_counter()
        r = await client.post(url, json={"text": text})
        r.raise_for_status()
        results.append(((time.perf_counter() - t0) * 1000, r.json()["cached"]))


async def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--url", default="http://127.0.0.1:8765/predict")
    ap.add_argument("--concurrency", type=int, default=64)
    ap.add_argument("--requests", type=int, default=1280)
    ap.add_argument("--warmup", type=int, default=64)
    ap.add_argument("--repeats", type=float, default=0.0)
    ap.add_argument("--seed", type=int, default=42)
    ap.add_argument("--out", default=None)
    args = ap.parse_args()

    rng = random.Random(args.seed)
    limits = httpx.Limits(max_connections=args.concurrency)
    async with httpx.AsyncClient(timeout=30.0, limits=limits) as client:
        # unique warmup texts warm the model without pre-caching the hot pool
        await asyncio.gather(*[
            client.post(args.url, json={"text": f"warmup request {args.seed}-{i}"})
            for i in range(args.warmup)
        ])

        per_worker = args.requests // args.concurrency
        results = []
        t0 = time.perf_counter()
        await asyncio.gather(*[
            worker(client, args.url, per_worker, rng, args.repeats, args.seed, results)
            for _ in range(args.concurrency)
        ])
        elapsed = time.perf_counter() - t0

    total = per_worker * args.concurrency
    latencies_ms = [lat for lat, _ in results]
    hits = sum(1 for _, cached in results if cached)
    print(f"concurrency={args.concurrency}  requests={total}  repeats={args.repeats}")
    print(f"throughput: {total / elapsed:7.1f} req/s")
    print(f"hit rate:   {hits / total:7.1%}")
    print(f"P50:  {np.percentile(latencies_ms, 50):7.2f} ms")
    print(f"P95:  {np.percentile(latencies_ms, 95):7.2f} ms")
    print(f"P99:  {np.percentile(latencies_ms, 99):7.2f} ms")
    if args.out:
        with open(args.out, "w") as f:
            f.writelines(f"{lat:.3f},{int(cached)}\n" for lat, cached in results)


if __name__ == "__main__":
    asyncio.run(main())
