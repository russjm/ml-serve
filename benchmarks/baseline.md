# Baseline

**Date:** 2026-06-24
**Hardware:** Apple M3, 8 cores, 8 GB RAM
**Model:** `distilbert-base-uncased-finetuned-sst-2-english`
**Setup:** uvicorn 0.49, single worker, CPU only, no batching, no cache. Sequential `httpx` client, one request at a time.
**Workload:** 50 requests after 5 warmup, rotating through 10 short sample sentences (~6–9 tokens each).

## Results

| Metric | Value (ms) |
| --- | --- |
| P50 | 17.56 |
| P95 | 20.11 |
| P99 | 20.74 |
| mean | 17.64 |
| min | 13.48 |
| max | 21.26 |

First request after server start was ~263 ms (cold-start overhead). Excluded using warmup.

## Reproduce

```bash
# In one terminal:
uv run uvicorn serve.app:app --host 127.0.0.1 --port 8765

# In another:
uv run python bench/baseline.py
```
