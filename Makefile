CLUSTER := ml-serve
IMAGE := ml-serve:dev
# third-party images get loaded into the node too, so the cluster comes up without
# the node needing to reach docker hub
DEP_IMAGES := prom/prometheus:v3.1.0 grafana/grafana:11.5.1 redis:7-alpine
METRICS_SERVER := https://github.com/kubernetes-sigs/metrics-server/releases/download/v0.9.0/components.yaml
DEPLOYMENTS := serve redis prometheus grafana

.PHONY: cluster-up cluster-down build load deploy redeploy load-test status bench-all plots demo demo-down

cluster-up:
	kind create cluster --name $(CLUSTER) --config k8s/kind/cluster.yaml
	kubectl apply -f $(METRICS_SERVER)
# kind's kubelet serves a self-signed cert, which metrics-server rejects by default
	kubectl -n kube-system patch deployment metrics-server --type=json \
	  -p '[{"op":"add","path":"/spec/template/spec/containers/0/args/-","value":"--kubelet-insecure-tls"}]'
	kubectl -n kube-system rollout status deployment/metrics-server
	$(MAKE) build load deploy

build:
	docker build -t $(IMAGE) .

load:
	for i in $(DEP_IMAGES); do docker image inspect $$i >/dev/null 2>&1 || docker pull $$i; done
	kind load docker-image $(IMAGE) $(DEP_IMAGES) --name $(CLUSTER)

# grafana config is generated from observability/ so the dashboard has one source of truth
deploy:
	kubectl create configmap grafana-datasources \
	  --from-file=observability/grafana/provisioning/datasources/prometheus.yml \
	  --dry-run=client -o yaml | kubectl apply -f -
	kubectl create configmap grafana-dashboard-provider \
	  --from-file=observability/grafana/provisioning/dashboards/dashboards.yml \
	  --dry-run=client -o yaml | kubectl apply -f -
	kubectl create configmap grafana-dashboards \
	  --from-file=observability/grafana/dashboards/serve.json \
	  --dry-run=client -o yaml | kubectl apply -f -
	kubectl apply -f k8s/
	for d in $(DEPLOYMENTS); do kubectl rollout status deployment/$$d --timeout=180s; done

redeploy: build load
	kubectl rollout restart deployment/serve
	kubectl rollout status deployment/serve

status:
	kubectl get pods,hpa

# all-miss workload, split across 4 client processes so the load generator isn't the bottleneck
# the flush matters: cache_bench seeds its rng, so a rerun regenerates the same
# "unique" texts and reads them back out of redis as hits
load-test:
	kubectl exec deploy/redis -- redis-cli flushall
	for s in 1 2 3 4; do \
	  uv run python bench/cache_bench.py --url http://localhost:30080/predict \
	    --repeats 0.0 --concurrency 16 --requests 4000 --seed $$s & \
	done; wait

cluster-down:
	kind delete cluster --name $(CLUSTER)

# the whole stack on compose, then a minute of load so grafana has something in it
demo:
	docker compose up -d --build
	@for i in $$(seq 90); do curl -sf localhost:8000/health >/dev/null && break || sleep 2; done
	@curl -s -X POST localhost:8000/predict -H 'content-type: application/json' \
	  -d '{"text":"this movie was absolutely fantastic"}'
	@echo
	REPEAT_RATE=0.5 uv run locust -f bench/locustfile.py --headless --processes 4 \
	  --host http://localhost:8000 --users 16 --spawn-rate 16 --run-time 60s
	@echo
	@echo "  api      http://localhost:8000/docs"
	@echo "  metrics  http://localhost:8000/metrics"
	@echo "  grafana  http://localhost:3000/d/ml-serve"
	@echo "  stop     make demo-down"

demo-down:
	docker compose down

# full scenario sweep (~30 min) plus the three charts the readme uses
bench-all:
	bash bench/run_all.sh

plots:
	uv run python bench/plot.py
