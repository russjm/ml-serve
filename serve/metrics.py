from prometheus_client import Counter, Gauge, Histogram

# spans a cache hit (sub-ms) to a queued miss under load (hundreds of ms)
LATENCY_BUCKETS = (0.001, 0.005, 0.01, 0.025, 0.05, 0.1, 0.25, 0.5, 1.0, 2.5)

predict_requests = Counter(
    "predict_requests_total", "Requests served by /predict", ["cache"]
)
predict_latency = Histogram(
    "predict_latency_seconds",
    "End-to-end /predict latency",
    ["cache"],
    buckets=LATENCY_BUCKETS,
)
batch_size = Histogram(
    "batch_size",
    "Requests per forward pass",
    buckets=(1, 2, 4, 8, 16, 32, 64),
)
batch_queue_depth = Gauge("batch_queue_depth", "Requests waiting in the batcher queue")
inference_duration = Histogram(
    "inference_duration_seconds",
    "Time spent in the model forward pass",
    buckets=LATENCY_BUCKETS,
)
cache_errors = Counter("cache_errors_total", "Failed redis operations", ["op"])

# labeled series
for outcome in ("hit", "miss"):
    predict_requests.labels(cache=outcome)
    predict_latency.labels(cache=outcome)
for op in ("get", "set"):
    cache_errors.labels(op=op)
