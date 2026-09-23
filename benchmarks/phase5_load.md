# Load testing under one harness

**Date:** 2026-09-03
**Hardware:** Apple M3, 8 cores (4 performance, 4 efficiency), 8 GB RAM. Docker Desktop VM: 6 CPU,
3.8 GB. Phase 4 ran on an 8-CPU VM, so its numbers aren't directly comparable to these.
**Model:** `distilbert-base-uncased-finetuned-sst-2-english`, CPU, torch 2.13.0+cpu, transformers
5.12.1, Python 3.11 in the image.
**Cluster:** kind 0.32.0, node image v1.36.1, single node.
**Setup:** `MAX_WAIT_MS=10`, `TORCH_THREADS=1`, `MAX_BATCH_SIZE` per row below. Per pod: requests
500m CPU / 512Mi, limits 1 CPU / 1Gi. Redis, Prometheus and Grafana in-cluster. HPA min 2, max 4,
target 60% CPU.
**Client:** Locust 2.46.4, 4 worker processes, closed loop with no think time, on the host. Redis
flushed before every run.

Every earlier benchmark here used a different load generator, a different environment and a
different batch size, so the numbers couldn't be compared to each other. This run puts all five
scenarios on the same cluster with the same client.

## Results

The three single-pod rows are pinned to 1 replica with the HPA deleted, so the client connects
after the pod count has settled. Cache is on in every row: the 0% rows send 100% unique text, so
every request misses and still pays a Redis GET and SETEX.

| Scenario | Batch | Replicas | Hit rate | Throughput | P50 | P95 | P99 | Requests |
| --- | --- | --- | --- | --- | --- | --- | --- | --- |
| No batching | 1 | 1 | 0.0% | 26.2 req/s | 2300 ms | 3400 ms | 4700 ms | 4715 |
| Batching | 32 | 1 | 0.0% | 47.9 req/s | 1300 ms | 1900 ms | 2200 ms | 8624 |
| Batching + cache | 32 | 1 | 89.9% | 359.5 req/s | 6 ms | 1400 ms | 2600 ms | 64577 |
| Autoscaled, 64 users | 32 | 2→4 | 49.6% | 54.7 req/s | 920 ms | 3800 ms | 7200 ms | 16381 |
| Autoscaled, 25→200 users | 32 | 2→4 | 49.9% | 114.2 req/s | 280 ms | 4800 ms | 9600 ms | 34158 |

No request failed in any run. Locust rounds percentiles above a second to the nearest 100 ms, so
these have coarser precision than the phase 1 and 2 numbers, which came from raw latency arrays.

## Batching and the cache

I ran the three single-pod scenarios three times. Throughput moves a lot between runs:

| Run | No batching | Batching | Speedup |
| --- | --- | --- | --- |
| 1 | 31.1 req/s | 56.1 req/s | 1.80x |
| 2 | 22.6 req/s | 53.0 req/s | 2.35x |
| 3 (table above) | 26.2 req/s | 47.9 req/s | 1.83x |

Median 1.83x. The README used to claim 3.8x, measured in phase 1 with a single-process client that
capped near 210 req/s. That number was wrong and this replaces it.

Batching wins less here than it did natively because these pods run one torch thread under a 1-CPU
limit. Batching amortizes per-request Python and tokenizer work, but there's no intra-op
parallelism to exploit, which is where the rest of the native speedup came from.

The latency numbers are steadier than the throughput ratios and say the same thing more clearly:
P50 goes from 2300 ms to 1300 ms, P99 from 4700 ms to 2200 ms.

The cache row has a P50 of 6 ms and a P99 of 2600 ms in the same run. Nine of ten requests never
reach the model and the tenth queues behind a forward pass, so the 177 ms mean sits in a gap where
almost no request actually landed.

Cache throughput across the three runs: 281.7, 449.4, 359.5 req/s. P50 was 5-6 ms every time.
Hits don't care what else the box is doing.

## Autoscaling

Both autoscaled runs start at 2 replicas with CPU idle, and the HPA scales to its ceiling of 4
during the measured window.

| Scenario | HPA raises desired to 4 | 4 pods Ready |
| --- | --- | --- |
| 64 users | t=33 s | t=65 s |
| 25→200 users | t=32 s | t=57 s |

About half of that is the HPA deciding and half is the pod loading the model and passing its
startup probe. Phase 4 measured 31 s and 52 s end to end on a faster VM.

**Scaling out only helps if the client opens new connections.** Four replicas with a 50% hit rate
served 54.7 req/s under a fixed pool of 64 connections. One replica with no cache served 47.9. The
extra pods and the free cache hits bought about 14%.

kube-proxy balances connections, not requests. All 64 users spawn at once, their connections pin to
the two pods alive at t=0, and the two pods that arrive at t=65 s get almost nothing. Phase 4 found
this with a different client library; it reproduces exactly.

The ramping run is the control. Users arriving after the scale-out open fresh connections, and it
peaked at 240 req/s against the fixed pool's 54.7 with the same replica count and hit rate. The two
aren't a clean pair, since the ramp also reaches 200 users against 64, but the mechanism matches
the socket counts phase 4 measured per pod.

## The ramping run collapsed

Throughput peaked at 240 req/s and dropped to 35 req/s with the user count held flat at 200. P95
went from 2000 ms to 11000 ms. Sampling the per-second history every 40 s:

| t | Users | Throughput | P95 |
| --- | --- | --- | --- |
| 121 s | 200 | 186.9 req/s | 2200 ms |
| 161 s | 200 | 231.1 req/s | 2000 ms |
| 202 s | 200 | 101.3 req/s | 4600 ms |
| 242 s | 200 | 38.3 req/s | 11000 ms |
| 282 s | 200 | 78.4 req/s | 6200 ms |

What I ruled out: all four pods stayed Ready throughout, no restarts, no evictions, no OOM kills,
no failed requests, and Locust logged no CPU warnings about itself. The server didn't error, it got
slower.

My guess is the host thermally throttling, 50 minutes into a sweep that keeps every core busy, but I
didn't measure that and I'm leaving it open. Either way the 114.2 req/s average for that row covers
two different regimes, so the numbers worth quoting from it are the 240 req/s peak and the
scale-out timing.

## Limitations

Closed loop. Each user waits for a response before sending again, so offered load falls
automatically when the server slows down. A real client wouldn't wait, queues would grow, and the
tail would be worse than what's here. These aren't open-loop numbers.

The client shares 8 cores with the Docker VM, which is why the same scenario varies 20-30% between
runs. Single node, single machine, CPU only.

## Reproduce

```bash
make cluster-up
make bench-all     # about 40 minutes
make plots
```

`bench/run_all.sh` patches `MAX_BATCH_SIZE`, pins or releases replicas, flushes Redis, warms up and
runs each scenario into `bench/results/<name>/`, then restores the shipped configmap and HPA.

Two ordering details in that script matter. The replica count is reset after the warmup, not
before, because the warmup drives enough CPU to trip the HPA and a run that starts already scaled
out measures nothing. And the HPA is deleted rather than scaled down, because a plain scale-down
gets reverted inside its 5-minute stabilization window.

Locust's CSVs don't record cache hits, so `bench/locustfile.py` counts the `cached` field itself and
prints a hit rate per worker at shutdown. The rates in the table are those, summed across workers.
