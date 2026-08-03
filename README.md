# ml-serve

A small Triton/BentoML-style model server built from scratch to explore production ML infrastructure.

## Setup

Requires [uv](https://docs.astral.sh/uv/) and Python 3.11.

```bash
uv sync
uv run uvicorn serve.app:app --host 127.0.0.1 --port 8765
```

```bash
curl localhost:8765/health
curl -X POST localhost:8765/predict \
  -H 'content-type: application/json' \
  -d '{"text":"this movie was great"}'
```

### Docker

```bash
docker compose up --build
```

Runs four services: the server on 8000, Redis, Prometheus on 9090, and Grafana on 3000.

## Baseline latency

Measured on M3, single worker, no batching or caching. 50 sequential requests, 5 warmup discarded.

| P50 | P95 | P99 |
| --- | --- | --- |
| 17.6 ms | 20.1 ms | 20.7 ms |

Details in `benchmarks/baseline.md`.

## Batching

The server groups concurrent requests into one forward pass. Two env vars control it: `MAX_BATCH_SIZE` and `MAX_WAIT_MS`, whichever comes first triggers a flush.

Batch size 8 was fastest at 205 req/s under 64 concurrent clients, about 3.8x the no-batching case. That 3.8x needs re-measuring: the single-process load generator behind it caps around 210 req/s, so the peak was clipped and the slower batch sizes weren't. Details and the correction in `benchmarks/phase1_batching.md`.

## Caching

Predictions are cached in Redis, keyed by a hash of the input text with a 1 hour TTL. A hit skips the model and returns in a few milliseconds; if Redis is down the server logs a warning and serves every request from the model.

At 90% repeated inputs, throughput was 1980 req/s, 6.3x the all-miss case. Details in `benchmarks/phase2_cache.md`.

## Benchmark methodology

I checked these numbers against Agrawal et al., *On Evaluating Performance of LLM Inference Systems* ([arXiv:2507.09019](https://arxiv.org/abs/2507.09019)), and wrote up which of its eight evaluation anti-patterns apply to a non-autoregressive encoder, plus where my own methodology falls short: [Auditing my own inference-server benchmarks](https://gist.github.com/russjm/a0b6dbbf8dcecbbabe0bd3ea63b74032).

## Observability

The server exposes Prometheus metrics at `/metrics`: request count and end-to-end latency (both split by cache hit or miss), batch size, batcher queue depth, inference time, and Redis errors.

Prometheus scrapes every 5 seconds. Grafana loads its datasource and dashboard from `observability/grafana/`, so the dashboard is checked in rather than set up by hand.

## Model

Uses the pretrained `distilbert-base-uncased-finetuned-sst-2-english` checkpoint from HF. To use fine-tuned weights:

1. Run `train/train_distilbert.ipynb` on Colab
2. Download the model directory to `./model_local/`
3. Start the server with `MODEL_PATH=./model_local`