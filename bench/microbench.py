import argparse
import asyncio
import time

import httpx
import numpy as np

SAMPLES = [
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


async def worker(client, url, n, latencies_ms):
    for i in range(n):
        t0 = time.perf_counter()
        r = await client.post(url, json={"text": SAMPLES[i % len(SAMPLES)]})
        r.raise_for_status()
        latencies_ms.append((time.perf_counter() - t0) * 1000)


async def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--url", default="http://127.0.0.1:8765/predict")
    ap.add_argument("--concurrency", type=int, default=64)
    ap.add_argument("--requests", type=int, default=1280)
    ap.add_argument("--warmup", type=int, default=64)
    args = ap.parse_args()

    limits = httpx.Limits(max_connections=args.concurrency)
    async with httpx.AsyncClient(timeout=30.0, limits=limits) as client:
        # warmup burst, discarded
        await asyncio.gather(*[
            client.post(args.url, json={"text": SAMPLES[i % len(SAMPLES)]})
            for i in range(args.warmup)
        ])

        per_worker = args.requests // args.concurrency
        latencies_ms = []
        t0 = time.perf_counter()
        await asyncio.gather(*[
            worker(client, args.url, per_worker, latencies_ms)
            for _ in range(args.concurrency)
        ])
        elapsed = time.perf_counter() - t0

    total = per_worker * args.concurrency
    print(f"concurrency={args.concurrency}  requests={total}")
    print(f"throughput: {total / elapsed:7.1f} req/s")
    print(f"P50:  {np.percentile(latencies_ms, 50):7.2f} ms")
    print(f"P95:  {np.percentile(latencies_ms, 95):7.2f} ms")
    print(f"P99:  {np.percentile(latencies_ms, 99):7.2f} ms")
    print(f"mean: {np.mean(latencies_ms):7.2f} ms")


if __name__ == "__main__":
    asyncio.run(main())
