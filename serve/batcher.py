import asyncio
import os
import time

from serve import metrics
from serve.model import Prediction

MAX_BATCH_SIZE = int(os.environ.get("MAX_BATCH_SIZE", "32"))
MAX_WAIT_MS = int(os.environ.get("MAX_WAIT_MS", "10"))


class DynamicBatcher:
    def __init__(self, runner, max_batch_size=MAX_BATCH_SIZE, max_wait_ms=MAX_WAIT_MS):
        self.runner = runner
        self.max_batch_size = max_batch_size
        self.max_wait_ms = max_wait_ms
        self.queue = asyncio.Queue()
        self._task = None

    def start(self):
        self._task = asyncio.create_task(self._run())

    async def stop(self):
        if self._task:
            self._task.cancel()
            try:
                await self._task
            except asyncio.CancelledError:
                pass

    async def enqueue(self, text: str) -> Prediction:
        future = asyncio.get_running_loop().create_future()
        self.queue.put_nowait((text, future))
        metrics.batch_queue_depth.set(self.queue.qsize())
        return await future

    async def _run(self):
        while True:
            batch = [await self.queue.get()]
            # keep pulling until the batch is full or the wait window elapses
            try:
                async with asyncio.timeout(self.max_wait_ms / 1000):
                    while len(batch) < self.max_batch_size:
                        batch.append(await self.queue.get())
            except TimeoutError:
                pass
            metrics.batch_queue_depth.set(self.queue.qsize())
            await self._run_batch(batch)

    async def _run_batch(self, batch):
        texts = [text for text, _ in batch]
        metrics.batch_size.observe(len(batch))
        t0 = time.perf_counter()
        try:
            # forward is blocking/CPU-bound - run it off the event loop
            preds = await asyncio.to_thread(self.runner.forward, texts)
        except Exception as e:
            for _, fut in batch:
                if not fut.done():
                    fut.set_exception(e)
            return
        metrics.inference_duration.observe(time.perf_counter() - t0)
        for (_, fut), pred in zip(batch, preds):
            if not fut.done():
                fut.set_result(pred)
