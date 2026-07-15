import asyncio

from serve.batcher import DynamicBatcher
from serve.model import Prediction


class FakeRunner:
    def __init__(self):
        self.batches = []

    def forward(self, texts):
        self.batches.append(list(texts))
        return [Prediction(label="POSITIVE", score=1.0) for _ in texts]


# raises on the first call, then succeeds
class FlakyRunner:
    def __init__(self):
        self.calls = 0

    def forward(self, texts):
        self.calls += 1
        if self.calls == 1:
            raise RuntimeError("boom")
        return [Prediction(label="POSITIVE", score=1.0) for _ in texts]


async def test_flushes_on_max_size():
    runner = FakeRunner()
    # long wait window so the only thing that can trigger a flush is the size cap
    batcher = DynamicBatcher(runner, max_batch_size=4, max_wait_ms=1000)
    batcher.start()
    results = await asyncio.gather(*[batcher.enqueue(f"t{i}") for i in range(4)])
    await batcher.stop()

    assert len(results) == 4
    assert runner.batches == [["t0", "t1", "t2", "t3"]]


async def test_flushes_on_max_wait():
    runner = FakeRunner()
    # fewer requests than the size cap, so only the timer can flush them
    batcher = DynamicBatcher(runner, max_batch_size=32, max_wait_ms=20)
    batcher.start()
    results = await asyncio.gather(*[batcher.enqueue(f"t{i}") for i in range(3)])
    await batcher.stop()

    assert len(results) == 3
    assert runner.batches == [["t0", "t1", "t2"]]


async def test_model_error_isolated_and_loop_survives():
    batcher = DynamicBatcher(FlakyRunner(), max_batch_size=2, max_wait_ms=10)
    batcher.start()

    failed = await asyncio.gather(
        batcher.enqueue("a"), batcher.enqueue("b"), return_exceptions=True
    )
    assert all(isinstance(r, RuntimeError) for r in failed)

    ok = await batcher.enqueue("c")
    await batcher.stop()
    assert ok.label == "POSITIVE"
