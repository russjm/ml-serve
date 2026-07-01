import argparse
import statistics
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


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--url", default="http://127.0.0.1:8765/predict")
    ap.add_argument("--n", type=int, default=50)
    ap.add_argument("--warmup", type=int, default=5)
    args = ap.parse_args()

    with httpx.Client(timeout=10.0) as client:
        for i in range(args.warmup):
            client.post(args.url, json={"text": SAMPLES[i % len(SAMPLES)]})

        latencies_ms = []
        for i in range(args.n):
            text = SAMPLES[i % len(SAMPLES)]
            t0 = time.perf_counter()
            r = client.post(args.url, json={"text": text})
            r.raise_for_status()
            latencies_ms.append((time.perf_counter() - t0) * 1000)

    print(f"n={args.n}  warmup={args.warmup}")
    print(f"P50:  {np.percentile(latencies_ms, 50):7.2f} ms")
    print(f"P95:  {np.percentile(latencies_ms, 95):7.2f} ms")
    print(f"P99:  {np.percentile(latencies_ms, 99):7.2f} ms")
    print(f"mean: {statistics.mean(latencies_ms):7.2f} ms")
    print(f"min:  {min(latencies_ms):7.2f} ms")
    print(f"max:  {max(latencies_ms):7.2f} ms")


if __name__ == "__main__":
    main()
