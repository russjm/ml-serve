# Redis caching

**Date:** 2026-07-24
**Hardware:** Apple M3, 8 cores, 8 GB RAM
**Model:** `distilbert-base-uncased-finetuned-sst-2-english`, CPU, torch 2.12
**Setup:** uvicorn single worker (native, not in Docker), `MAX_BATCH_SIZE=8`, `MAX_WAIT_MS=10`.
Redis 7 (`redis:7-alpine` in Docker). Cache TTL 1 hour, flushed before each run.
**Workload:** 64 concurrent clients, closed-loop, 2560 requests after warmup. Each request picks
from a hot pool of 10 sentences with probability p (the repeat rate), otherwise sends a
never-seen-before text. Client load split across 4 processes, 16 connections each.

## Results

| Repeat rate | Hit rate | Throughput (req/s) | P50 (ms) | P95 (ms) | P99 (ms) |
| --- | --- | --- | --- | --- | --- |
| 0% | 0% | 315 | 187 | 305 | 366 |
| 50% | 49% | 666 | 49 | 196 | 242 |
| 90% | 88% | 1980 | 3.8 | 179 | 214 |
| 0%, Redis down | 0% | 242 | 252 | 424 | 505 |

At 90% repeats, throughput is 6.3x the all-miss case and P50 drops from 187 ms to 3.8 ms. The
latency splits in two: the median request is a cache hit at a few ms, while the P95 and P99 are
the misses still going through the model. Hit rate comes in a bit under the repeat rate because
the first request for each hot sentence is a miss.

A single cached request measured in isolation returns in 0.4-0.7 ms.

The last row is the fail-open path: Redis stopped entirely, every request pays a failed
connection attempt plus a warning log, then runs the model. The server keeps serving, about 23%
slower than the all-miss case.

## Note: the load generator was the first bottleneck

My first runs showed 90% repeats topping out at 201 req/s, barely above the all-miss case, with
165 ms P50 even for hits. The server wasn't the limit: a single-process asyncio client capped
out around 210-330 req/s regardless of what the server did. A pure-hit run made it obvious: 209
req/s at concurrency 64, but 998 req/s at concurrency 8, which only happens if the client is the
constraint. Two client processes at half the concurrency nearly doubled throughput, confirming
it. All numbers above use 4 client processes; throughput is summed and latencies are merged
across them.

This also means the phase 1 numbers are understated: the same single-process client measured
batch size 8 at 205 req/s, right at the client's own ceiling. With the 4-process client the
same server config sustains ~315 req/s on an all-miss workload. Worth re-measuring the batching
sweep with a multi-process load generator.

## Reproduce

```bash
docker run --rm -d -p 6379:6379 --name bench-redis redis:7-alpine

# in one terminal
MAX_BATCH_SIZE=8 uv run uvicorn serve.app:app --host 127.0.0.1 --port 8765

# in another, per repeat rate
docker exec bench-redis redis-cli flushall
for s in 1 2 3 4; do
  uv run python bench/cache_bench.py --repeats 0.9 --concurrency 16 \
    --requests 640 --seed $s --out /tmp/r90_$s.csv &
done; wait
```

Sum the reported throughputs; merge the `--out` CSVs (`latency_ms,cached` per line) for combined
percentiles and hit rate.
