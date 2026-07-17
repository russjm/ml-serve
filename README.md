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
docker build -t ml-serve .
docker run -p 8000:8000 ml-serve
```

## Baseline latency

Measured on M3, single worker, no batching or caching. 50 sequential requests, 5 warmup discarded.

| P50 | P95 | P99 |
| --- | --- | --- |
| 17.6 ms | 20.1 ms | 20.7 ms |

Details in `benchmarks/baseline.md`.

## Batching

The server groups concurrent requests into one forward pass. Two env vars control it: `MAX_BATCH_SIZE` and `MAX_WAIT_MS`, whichever comes first triggers a flush.

Batch size 8 was fastest at 205 req/s under 64 concurrent clients, about 3.8x the no-batching case.
Details in `benchmarks/phase1_batching.md`.

## Model

Uses the pretrained `distilbert-base-uncased-finetuned-sst-2-english` checkpoint from HF. To use fine-tuned weights:

1. Run `train/train_distilbert.ipynb` on Colab
2. Download the model directory to `./model_local/`
3. Start the server with `MODEL_PATH=./model_local`