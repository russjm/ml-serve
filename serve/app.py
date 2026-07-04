import time
from contextlib import asynccontextmanager

from fastapi import FastAPI
from pydantic import BaseModel, Field

from serve.batcher import DynamicBatcher
from serve.model import ModelRunner


class PredictRequest(BaseModel):
    text: str = Field(min_length=1, max_length=4000)


class PredictResponse(BaseModel):
    label: str
    score: float
    latency_ms: float


class HealthResponse(BaseModel):
    status: str
    model: str


@asynccontextmanager
async def lifespan(app: FastAPI):
    runner = ModelRunner()
    app.state.model_id = getattr(runner.model.config, "_name_or_path", "unknown")
    app.state.batcher = DynamicBatcher(runner)
    app.state.batcher.start()
    yield
    await app.state.batcher.stop()


app = FastAPI(title="ml-serve", version="0.1.0", lifespan=lifespan)


@app.get("/health", response_model=HealthResponse)
async def health() -> HealthResponse:
    return HealthResponse(status="ok", model=app.state.model_id)


@app.post("/predict", response_model=PredictResponse)
async def predict(req: PredictRequest) -> PredictResponse:
    t0 = time.perf_counter()
    pred = await app.state.batcher.enqueue(req.text)
    latency_ms = (time.perf_counter() - t0) * 1000
    return PredictResponse(label=pred.label, score=pred.score, latency_ms=latency_ms)
