import time
from contextlib import asynccontextmanager

from fastapi import FastAPI, Response
from prometheus_client import CONTENT_TYPE_LATEST, generate_latest
from pydantic import BaseModel, Field

from serve import metrics
from serve.batcher import DynamicBatcher
from serve.cache import RedisCache
from serve.model import ModelRunner


class PredictRequest(BaseModel):
    text: str = Field(min_length=1, max_length=4000)


class PredictResponse(BaseModel):
    label: str
    score: float
    latency_ms: float
    cached: bool


class HealthResponse(BaseModel):
    status: str
    model: str


@asynccontextmanager
async def lifespan(app: FastAPI):
    runner = ModelRunner()
    app.state.model_id = getattr(runner.model.config, "_name_or_path", "unknown")
    app.state.batcher = DynamicBatcher(runner)
    app.state.cache = RedisCache()
    app.state.batcher.start()
    yield
    await app.state.batcher.stop()
    await app.state.cache.close()


app = FastAPI(title="ml-serve", version="0.1.0", lifespan=lifespan)


@app.get("/health", response_model=HealthResponse)
async def health() -> HealthResponse:
    return HealthResponse(status="ok", model=app.state.model_id)


@app.get("/metrics")
async def prometheus_metrics() -> Response:
    return Response(generate_latest(), media_type=CONTENT_TYPE_LATEST)


@app.post("/predict", response_model=PredictResponse)
async def predict(req: PredictRequest) -> PredictResponse:
    t0 = time.perf_counter()
    pred = await app.state.cache.get(req.text)
    cached = pred is not None
    if not cached:
        pred = await app.state.batcher.enqueue(req.text)
        await app.state.cache.set(req.text, pred)
    elapsed = time.perf_counter() - t0
    outcome = "hit" if cached else "miss"
    metrics.predict_requests.labels(cache=outcome).inc()
    metrics.predict_latency.labels(cache=outcome).observe(elapsed)
    return PredictResponse(
        label=pred.label, score=pred.score, latency_ms=elapsed * 1000, cached=cached
    )
