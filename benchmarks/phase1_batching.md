# Dynamic batching

**Date:** 2026-07-14
**Hardware:** Apple M3, 8 cores, 8 GB RAM
**Model:** `distilbert-base-uncased-finetuned-sst-2-english`, CPU, torch 2.12
**Setup:** uvicorn single worker. Dynamic batcher with `MAX_WAIT_MS=10`, varying `MAX_BATCH_SIZE`.
**Workload:** 64 concurrent clients, closed-loop, 1280 requests after 64 warmup, 
rotating through 10 short sample sentences (~6–9 tokens each).

`MAX_BATCH_SIZE=1` is the no-batching control: every request is its own forward pass.

**Correction:** the peak below is capped by the load generator, not the server.
`bench/microbench.py` is a single asyncio process that tops out around 210 req/s at concurrency
64, so the 205 req/s measurement was clipped while the slower batch sizes weren't. The same
server config reached 315 req/s under the 4-process client in `phase2_cache.md`. The real ratio
is probably higher than 3.8x, but "batch size 8 is optimal" compares one truncated point against
four untruncated ones, so the whole sweep needs re-running with a multi-process client.

## Results

| MAX_BATCH_SIZE | Throughput (req/s) | P50 (ms) | P95 (ms) | P99 (ms) |
| --- | --- | --- | --- | --- |
| 1 | 53.3 | 1136 | 1534 | 1672 |
| 4 | 161.0 | 226 | 1243 | 2099 |
| 8 | 205.0 | 112 | 1046 | 2054 |
| 16 | 128.9 | 189 | 1444 | 2198 |
| 32 | 123.8 | 270 | 1446 | 2352 |

Batch size 8 was fastest at 205 req/s, about 3.8x the no-batching case, and P50 dropped from
~1100 ms to ~110 ms at the same load. Bigger batches were slower, settling around 125 req/s at
16 and 32.

The P50 at size 1 looks huge because all 64 clients are waiting in line for one-at-a-time
inference. It's not the same measurement as the 17.6 ms in `baseline.md`, which I ran one
request at a time.

I expected size 32 to be fastest and it wasn't. On CPU a single forward pass already uses all 4
performance cores, so a batch of 32 takes roughly 4x as long to run as a batch of 8. Batching
still helps by paying the fixed per-call overhead once for the whole group, but that saving runs
out once the batch is big enough, and past 8 there's nothing left to gain. A GPU would behave
differently. Since the best size depends on the hardware, I left it as an env var.

These are single runs on a laptop, so they move around by ~15% (size 8 came in anywhere from 171
to 205 req/s). The ordering held across runs.

## Reproduce

These numbers predate the Redis cache (measured at `be91425`; the cache landed in `769544c`).
On the current server every request checks Redis before the batcher, and `microbench.py` rotates
through 10 fixed sentences, so nearly everything is a cache hit and the batcher never runs. To
reproduce what's in the table:

```bash
git checkout be91425

# In one terminal, start the server with a chosen batch size:
MAX_BATCH_SIZE=8 uv run uvicorn serve.app:app --host 127.0.0.1 --port 8765

# In another:
uv run python bench/microbench.py --concurrency 64 --requests 1280
```
