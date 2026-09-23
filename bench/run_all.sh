#!/usr/bin/env bash
# runs every load scenario against the kind cluster and writes csvs to bench/results/
set -euo pipefail

cd "$(dirname "$0")/.."

HOST=${HOST:-http://localhost:30080}
OUT=${OUT:-bench/results}
PROCS=${PROCS:-4}

locust_run() {  # name repeat_rate extra_args...
  local name=$1 repeat=$2
  shift 2
  mkdir -p "$OUT/$name"
  REPEAT_RATE=$repeat uv run locust -f bench/locustfile.py --headless \
    --processes "$PROCS" --host "$HOST" --csv "$OUT/$name/run" \
    --csv-full-history "$@" 2>&1 | tee "$OUT/$name/locust.log"
}

set_batch_size() {
  local current
  current=$(kubectl get configmap serve-config -o jsonpath='{.data.MAX_BATCH_SIZE}')
  [ "$current" = "$1" ] && return 0
  kubectl patch configmap serve-config --type merge -p "{\"data\":{\"MAX_BATCH_SIZE\":\"$1\"}}"
  kubectl rollout restart deployment/serve
  kubectl rollout status deployment/serve --timeout=300s
}

pin_replicas() {
  kubectl delete hpa serve --ignore-not-found
  kubectl scale deployment/serve --replicas="$1"
  kubectl rollout status deployment/serve --timeout=300s
}

# call after the warmup, never before: warmup cpu trips the hpa and a run that
# starts already scaled out measures nothing. deleting the hpa rather than scaling
# it down drops the history that would revert this inside its 5-minute window.
reset_to_floor() {
  kubectl delete hpa serve --ignore-not-found
  kubectl scale deployment/serve --replicas=2
  kubectl rollout status deployment/serve --timeout=300s
  # let the warmup's cpu drain out of the metrics api before the hpa reads it
  sleep 90
  kubectl apply -f k8s/serve-hpa.yaml
  kubectl wait --for=jsonpath='{.status.readyReplicas}'=2 deployment/serve --timeout=300s
}

# the flush matters: warmup texts would otherwise come back as cache hits
warmup() {
  REPEAT_RATE=0.0 uv run locust -f bench/locustfile.py --headless --processes "$PROCS" \
    --host "$HOST" --users 16 --spawn-rate 16 --run-time 20s >/dev/null 2>&1 || true
  kubectl exec deploy/redis -- redis-cli flushall
}

sample_replicas() {  # name -> pid
  mkdir -p "$OUT/$1"
  # without the redirect the $( ) capturing this pid never sees eof and hangs
  uv run python bench/sample_replicas.py --out "$OUT/$1/replicas.csv" >/dev/null 2>&1 &
  echo $!
}

mkdir -p "$OUT"

echo "=== one pod, no batching, all misses ==="
set_batch_size 1
pin_replicas 1
warmup
locust_run no-batching 0.0 --users 64 --spawn-rate 64 --run-time 3m

echo "=== one pod, batch 32, all misses ==="
set_batch_size 32
pin_replicas 1
warmup
locust_run batching 0.0 --users 64 --spawn-rate 64 --run-time 3m

echo "=== one pod, batch 32, 90% repeats ==="
warmup
locust_run cache 0.9 --users 64 --spawn-rate 64 --run-time 3m

echo "=== autoscaled, 50% repeats, sustained ==="
warmup
reset_to_floor
pid=$(sample_replicas sustained)
locust_run sustained 0.5 --users 64 --spawn-rate 64 --run-time 5m
kill "$pid" || true

echo "=== autoscaled, 50% repeats, burst 25 -> 200 users ==="
warmup
reset_to_floor
pid=$(sample_replicas burst)
SHAPE=burst locust_run burst 0.5
kill "$pid" || true

echo "=== restoring the shipped config ==="
kubectl apply -f k8s/serve-configmap.yaml -f k8s/serve-hpa.yaml
kubectl rollout restart deployment/serve
kubectl rollout status deployment/serve --timeout=300s

grep -h HITRATE "$OUT"/*/locust.log || true
