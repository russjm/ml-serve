# ml-serve

A small Triton/BentoML-style model server built from scratch to explore production ML infrastructure. Serves a DistilBERT sentiment classifier on CPU.

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

```json
{"label": "POSITIVE", "score": 0.9999, "latency_ms": 32.7, "cached": false}
```

### Docker

```bash
docker compose up --build
```

Runs four services: the server on 8000, Redis, Prometheus on 9090, and Grafana on 3000.

### Tests

```bash
uv run pytest
```

## How it works

Concurrent requests are grouped into one forward pass, flushed when `MAX_BATCH_SIZE` requests are queued or `MAX_WAIT_MS` elapses, whichever comes first.

Predictions are cached in Redis, keyed by a hash of the input text. A hit skips the model entirely. If Redis is down the server logs a warning and serves every request from the model.

## Configuration

| Variable | Default | What it does |
| --- | --- | --- |
| `MAX_BATCH_SIZE` | `32` | Requests per forward pass |
| `MAX_WAIT_MS` | `10` | How long the batcher waits before flushing a partial batch |
| `REDIS_URL` | `redis://localhost:6379/0` | Cache location |
| `CACHE_TTL_S` | `3600` | Prediction TTL |
| `MODEL_PATH` | HF checkpoint | Local model directory to load instead |

## Benchmarks

All on an M3, single uvicorn worker, CPU.

| Config | Load generator | Throughput | P50 | P99 |
| --- | --- | --- | --- | --- |
| No batching or cache | sequential | — | 17.6 ms | 20.7 ms |
| No batching (size 1), 64 clients | 1 process | 53.3 req/s | 1136 ms | 1672 ms |
| Batching (size 8), 64 clients | 1 process | 205 req/s | 112 ms | 2054 ms |
| Cache all-miss, 64 clients | 4 processes | 315 req/s | 187 ms | 366 ms |
| Cache at 90% repeats, 64 clients | 4 processes | 1980 req/s | 3.8 ms | 214 ms |

Batching was about 3.8x the no-batching case, and the cache about 6.3x the all-miss case. Throughput isn't comparable across the load generator column: the single-process client caps around 210 req/s, which clipped the batching peak but not the slower batch sizes, so that 3.8x needs re-measuring. Details and the correction in `benchmarks/`.

I also checked these numbers against Agrawal et al., *On Evaluating Performance of LLM Inference Systems* ([arXiv:2507.09019](https://arxiv.org/abs/2507.09019)): [Auditing my own inference-server benchmarks](https://gist.github.com/russjm/ce38dde600b1aae380a2c9949bfd8093).

## Observability

The server exposes Prometheus metrics at `/metrics`: request count and end-to-end latency (both split by cache hit or miss), batch size, batcher queue depth, inference time, and Redis errors.

Prometheus scrapes every 5 seconds. Grafana loads its datasource and dashboard from `observability/grafana/`, so the dashboard is checked in rather than set up by hand.

## Model

Uses the pretrained `distilbert-base-uncased-finetuned-sst-2-english` checkpoint from HF. To use fine-tuned weights:

1. Run `train/train_distilbert.ipynb` on Colab
2. Download the model directory to `./model_local/`
3. Start the server with `MODEL_PATH=./model_local`

## License

MIT
