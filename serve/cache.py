import hashlib
import json
import logging
import os

import redis.asyncio as redis

from serve import metrics
from serve.model import Prediction

REDIS_URL = os.environ.get("REDIS_URL", "redis://localhost:6379/0")
CACHE_TTL_S = int(os.environ.get("CACHE_TTL_S", "3600"))

log = logging.getLogger(__name__)


class RedisCache:
    def __init__(self):
        self.client = redis.from_url(REDIS_URL, decode_responses=True)
        self.ttl_s = CACHE_TTL_S

    # hashed so keys stay fixed-size and raw user text never lands in redis logs
    def key(self, text: str) -> str:
        return "sent:" + hashlib.sha256(text.encode()).hexdigest()

    async def get(self, text: str) -> Prediction | None:
        try:
            hit = await self.client.get(self.key(text))
        except Exception:
            metrics.cache_errors.labels(op="get").inc()
            log.warning("redis get failed, treating as miss", exc_info=True)
            return None
        if hit is None:
            return None
        data = json.loads(hit)
        return Prediction(label=data["label"], score=data["score"])

    async def set(self, text: str, pred: Prediction):
        try:
            await self.client.setex(
                self.key(text),
                self.ttl_s,
                json.dumps({"label": pred.label, "score": pred.score}),
            )
        except Exception:
            metrics.cache_errors.labels(op="set").inc()
            log.warning("redis set failed, skipping", exc_info=True)

    async def close(self):
        await self.client.aclose()
