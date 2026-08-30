# Kubernetes and autoscaling

**Date:** 2026-08-29
**Hardware:** Apple M3, 8 cores, 8 GB RAM. Docker Desktop VM: 8 CPU.
**Model:** `distilbert-base-uncased-finetuned-sst-2-english`, CPU, torch 2.13+cpu in the
image.
**Cluster:** kind 0.32 (node image v1.36.1), single node.
**Setup:** `MAX_BATCH_SIZE=32`, `MAX_WAIT_MS=10`, `TORCH_THREADS=1`. Per pod: requests 500m CPU /
512Mi, limits 1 CPU / 1Gi. Redis and Prometheus in-cluster. HorizontalPodAutoscaler (HPA) min 2, max 4.
**Workload:** 100% unique texts, so every request runs the model. 64 concurrent clients split
across 4 processes, 16 connections each, 8000 requests per run. Redis flushed before every run.

## Image size

The default torch wheel bundles a CUDA stack that a CPU-only server never touches. Pointing torch
at the CPU index for linux only (macOS wheels are already CPU-only) drops 18 packages from the
resolution: `nvidia-cublas` at 543 MB, `nvidia-cudnn` at 445 MB, `triton` at 185 MB, and 15 more.
2.85 GB of linux/arm64 wheels in total.

| | Image | `kind load` |
| --- | --- | --- |
| Before | 5.44 GB | — |
| After | 1.42 GB | 71 s |

## Throughput by replica count

I pinned the replica count with `kubectl scale` and deleted the HPA, so the client opened its
connections after the pod count had already settled. Two runs each.

| Replicas | Throughput (req/s) | P50 (ms) | P95 (ms) | P99 (ms) |
| --- | --- | --- | --- | --- |
| 2 | 71.1 | 794 | 1233 | 6206 |
| 2 | 105.7 | 597 | 796 | 912 |
| 4 | 145.2 | 387 | 636 | 928 |
| 4 | 153.4 | 355 | 713 | 951 |

Twice the pods gives roughly twice the throughput and about half the P50, though the ratio lands
anywhere from 1.4x to 2.2x depending on which runs you compare. Midpoint to midpoint it's about
1.7x. The two-replica runs move around a lot (71 to 106 req/s) because the load generator shares
the same 8 cores as the Docker VM, so client and server compete for CPU.

These sit below the 315 req/s a single native worker managed in `phase2_cache.md`. That run had
four torch threads on the host; here each pod gets one thread and a 1-CPU limit inside Docker's
VM. That's four cores of compute either way, but this one also pays for virtualization, the
NodePort hop, a batch size of 32 instead of 8, and a different torch build.

At 4 replicas each pod sat at 940-965m CPU against its 1-core limit, and pod memory ran 286-416Mi
against the 512Mi request.

## Autoscaling

Load starts against 2 replicas; the HPA scales to its ceiling of 4.

| Run | Load starts | HPA raises desired to 4 | 4 pods Ready | Total |
| --- | --- | --- | --- | --- |
| 1 | t=16 s | t=37 s (CPU 156%) | t=47 s | 31 s |
| 2 | t=21 s | t=62 s (CPU 177%) | t=73 s | 52 s |

Scale-down came 326 s after the load stopped, against a 5-minute default stabilization window.
CPU was back under 3% within 50 s of the load ending, so almost all of that wait is the window
itself. Scale-up is immediate and scale-down is deliberately slow, so a burst that comes and goes
leaves the extra pods running for a few minutes.

## Note: why the scale-out didn't move throughput

I expected throughput to climb once the new pods went Ready and it didn't move at all, 53.6 req/s
before and after. Both autoscaling runs above added two pods that served **zero requests**.

kube-proxy load balances *connections*, not requests. The client opens 64 keep-alive connections
at the start, kube-proxy pins each to a pod that exists at that moment, and the connections never
move. I counted established sockets per pod mid-run: 28 and 36 on the two original pods, 1 each on
the two new ones, and that 1 is the Prometheus scrape.

So the table above and this section measure different things. The table is what 4 pods can do when
clients connect to all of them; this is what a client with long-lived connections gets from a
mid-flight scale-out, which is nothing. The fix would be client-side load balancing, or
connections that get recycled periodically.

## Reproduce

```bash
make cluster-up
make load-test          # flushes redis, then 4 client processes
kubectl get hpa serve -w
```

For the pinned replica numbers, take the HPA out of the way first:

```bash
kubectl delete hpa serve
kubectl scale deploy serve --replicas=2   # or 4
kubectl exec deploy/redis -- redis-cli flushall
for s in 1 2 3 4; do
  uv run python bench/cache_bench.py --url http://localhost:30080/predict \
    --repeats 0.0 --concurrency 16 --requests 2000 --seed $s --out /tmp/r_$s.csv &
done; wait
kubectl apply -f k8s/serve-hpa.yaml
```

Sum the reported throughputs; merge the `--out` CSVs for combined percentiles. The flush matters:
`cache_bench.py` seeds its RNG, so a rerun regenerates the same "unique" texts and reads them back
as cache hits.
