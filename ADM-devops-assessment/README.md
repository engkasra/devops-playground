# DevOps Technical Assessment

A small FastAPI backend wrapped in a complete DevOps setup: Docker, GitLab
CI/CD, Kubernetes manifests, Prometheus/Grafana monitoring, and structured
logging for Loki/ELK. The application logic is deliberately trivial — the focus
is the surrounding infrastructure.

## What the service does

| Endpoint    | Purpose                                                  |
|-------------|----------------------------------------------------------|
| `GET /`         | Hello payload (app name + env)                       |
| `GET /api/items`| Trivial placeholder "business logic"                 |
| `GET /health`   | **Liveness** — 200 while the process is up           |
| `GET /ready`    | **Readiness** — 200 once startup finished (else 503) |
| `GET /metrics`  | Prometheus metrics (text format)                     |

All configuration comes from environment variables. Every request is logged as
a single structured JSON line.

## Project layout

```
.
├── app/                      # FastAPI service
│   ├── main.py
│   └── requirements.txt
├── tests/                    # pytest smoke tests (run in CI)
├── Dockerfile                # multi-stage, non-root, healthcheck
├── docker-compose.yml        # app + optional monitoring profile
├── .env.example              # sample environment file
├── .gitlab-ci.yml            # test -> build -> scan -> deploy
├── k8s/                      # Kubernetes manifests
│   ├── 00-namespace.yaml
│   ├── configmap.yaml
│   ├── secret.yaml
│   ├── deployment.yaml
│   ├── service.yaml
│   ├── ingress.yaml
│   └── hpa.yaml
├── kind/kind-config.yaml     # local cluster config (ingress-ready)
└── monitoring/
    ├── prometheus/           # scrape config + alert rules
    ├── grafana/              # auto-provisioned datasources
    ├── loki/                 # Loki config
    └── promtail/             # ships container logs to Loki
```

---

## 1. Prerequisites (local lab on Ubuntu)

You do **not** need a separate VM. Install Docker on the host and use `kind`
(Kubernetes in Docker) for the cluster — clusters are disposable containers, so
there is nothing to clean up afterwards.

```bash
# Docker Engine
sudo apt-get update
sudo apt-get install -y docker.io
sudo usermod -aG docker $USER   # then log out/in so the group applies

# kubectl
curl -LO "https://dl.k8s.io/release/$(curl -L -s https://dl.k8s.io/release/stable.txt)/bin/linux/amd64/kubectl"
sudo install -o root -g root -m 0755 kubectl /usr/local/bin/kubectl

# kind
curl -Lo ./kind https://kind.sigs.k8s.io/dl/latest/kind-linux-amd64
sudo install -o root -g root -m 0755 kind /usr/local/bin/kind

# helm (used to install metrics-server / monitoring stack)
curl https://raw.githubusercontent.com/helm/helm/main/scripts/get-helm-3 | bash
```

---

## 2. Run locally (no Docker)

```bash
cd app
python3 -m venv .venv && source .venv/bin/activate
pip install -r requirements.txt
uvicorn main:app --reload --port 8000

# in another terminal
curl localhost:8000/health
curl localhost:8000/ready
curl localhost:8000/metrics
```

---

## 3. Build and run with Docker

```bash
cp .env.example .env

# build the image
docker build -t devops-demo:local .

# run just the app
docker compose up --build
# -> http://localhost:8000  (Compose reports the container as healthy)
```

Bring up the **full observability stack** (app + Prometheus + Grafana + Loki):

```bash
docker compose --profile monitoring up --build
```

| Service    | URL                     | Notes                  |
|------------|-------------------------|------------------------|
| App        | http://localhost:8000   |                        |
| Prometheus | http://localhost:9090   | check *Status → Targets* / *Alerts* |
| Grafana    | http://localhost:3000   | login `admin` / `admin`, datasources pre-wired |
| Loki       | http://localhost:3100   | query via Grafana → *Explore* |

In Grafana, open **Explore → Loki** and run `{container="devops-demo"}` to see
the JSON logs; **Explore → Prometheus** and run `http_requests_total` to see
metrics.

---

## 4. Deploy on Kubernetes (kind)

```bash
# 1) create the cluster
kind create cluster --name devops --config kind/kind-config.yaml

# 2) install the NGINX ingress controller (kind flavour)
kubectl apply -f https://raw.githubusercontent.com/kubernetes/ingress-nginx/main/deploy/static/provider/kind/deploy.yaml
kubectl wait --namespace ingress-nginx \
  --for=condition=ready pod \
  --selector=app.kubernetes.io/component=controller --timeout=120s

# 3) build the image and load it INTO kind (no registry needed locally)
docker build -t devops-demo:local .
kind load docker-image devops-demo:local --name devops

# 4) apply manifests (namespace first to avoid ordering issues)
kubectl apply -f k8s/00-namespace.yaml
kubectl apply -f k8s/

# 5) watch it come up
kubectl get pods -n devops-demo -w
```

Test the ingress:

```bash
echo "127.0.0.1 devops-demo.local" | sudo tee -a /etc/hosts
curl http://devops-demo.local/health
```

### Enable the HPA

The HPA needs metrics-server. On kind it must run with an insecure-kubelet flag:

```bash
kubectl apply -f https://github.com/kubernetes-sigs/metrics-server/releases/latest/download/components.yaml
kubectl patch -n kube-system deployment metrics-server --type=json \
  -p='[{"op":"add","path":"/spec/template/spec/containers/0/args/-","value":"--kubelet-insecure-tls"}]'

kubectl get hpa -n devops-demo
# generate load to watch it scale:
kubectl run -n devops-demo load --image=busybox --restart=Never -- \
  /bin/sh -c "while true; do wget -q -O- http://devops-demo/; done"
```

### Monitoring inside the cluster

For a real cluster, install the kube-prometheus-stack (Prometheus + Grafana +
Alertmanager) via Helm:

```bash
helm repo add prometheus-community https://prometheus-community.github.io/helm-charts
helm install monitoring prometheus-community/kube-prometheus-stack -n monitoring --create-namespace
```

The deployment pods carry `prometheus.io/scrape` annotations, so an
annotation-based Prometheus picks them up automatically. The alert rules in
`monitoring/prometheus/alert.rules.yml` can be loaded as a `PrometheusRule`.

---

## 5. CI/CD pipeline (`.gitlab-ci.yml`)

Four stages run on every push:

1. **test** — installs deps in a `python:3.12-slim` image and runs `pytest`.
2. **build** — builds the Docker image with Docker-in-Docker and pushes
   `:$CI_COMMIT_SHORT_SHA` and `:latest` to the GitLab Container Registry.
3. **scan** — runs **Trivy** against the built image. It prints a HIGH/CRITICAL
   report and then fails the job if any HIGH/CRITICAL (fixable) vulnerabilities
   exist. Set `allow_failure: true` to make it advisory while triaging.
4. **deploy** — a **manual** job scoped to the `production` environment. By
   default it is **simulated** (it echoes the exact `kubectl` commands). To make
   it real, add a `KUBE_CONFIG` CI/CD variable (base64-encoded kubeconfig) and
   uncomment the kubectl block in the file.

The registry variables (`CI_REGISTRY`, `CI_REGISTRY_IMAGE`, `CI_REGISTRY_USER`,
`CI_REGISTRY_PASSWORD`) are provided automatically by GitLab.

---

## 6. Monitoring approach

* The app exposes `/metrics` via `prometheus-fastapi-instrumentator`, which
  records request counts, latency histograms, and request/response sizes, on
  top of standard Python process metrics.
* Prometheus scrapes `/metrics`; Grafana visualises and explores.
* **Alert rules** (`monitoring/prometheus/alert.rules.yml`), all using the real
  exposed metric names:
  1. `ServiceDown` — `up == 0` for 1m (scrape target unreachable).
  2. `HighErrorRate` — 5xx ratio > 5% over 5m.
  3. `HighRequestLatency` — p95 latency > 500ms over 5m.
  4. `HighMemoryUsage` — resident memory > 200MB for 10m (leak detection).

## 7. Logging approach

* Logs are written to **stdout** as one **JSON object per line** — the standard
  pattern for containers, and directly consumable by Loki or ELK without parsing
  hacks.
* Each HTTP request emits a structured event with `request_id`, `method`,
  `path`, `status_code`, and `duration_ms`. Uvicorn's own logs are routed
  through the same JSON formatter.
* **Loki path (used here):** Promtail tails the Docker container logs, parses the
  JSON (so `level`, `path`, `status_code` become labels/fields), and ships them
  to Loki, queried through Grafana.
* **ELK path (alternative):** the same JSON on stdout is collected by Filebeat →
  Logstash/Elasticsearch → Kibana. No application changes required because the
  log format is already structured.

---

## 8. Rollback strategy

* **Kubernetes (fastest):** each deploy is a new ReplicaSet, so roll back with
  ```bash
  kubectl rollout undo deployment/devops-demo -n devops-demo
  kubectl rollout undo deployment/devops-demo --to-revision=<N> -n devops-demo
  kubectl rollout status deployment/devops-demo -n devops-demo
  ```
  Probes ensure a bad version never receives traffic (readiness) and crash-loops
  are restarted (liveness); `RollingUpdate` keeps old pods until new ones are
  ready.
* **Image level:** every build is tagged with the immutable commit SHA, so any
  previous version can be redeployed by tag — never rely on `:latest` for
  rollback.
* **CI/CD:** because deploy is a manual, environment-scoped job, GitLab's
  *Environments* view lets you re-run a prior successful deployment.

---

## 9. Assumptions and limitations

* `kind` + Docker is the target local environment; commands assume Ubuntu.
* The committed `secret.yaml` holds a placeholder. Real secrets should use
  Sealed Secrets, SOPS, or Vault and never be committed.
* The CI deploy stage is simulated by default; wiring it to a real cluster needs
  a `KUBE_CONFIG` variable.
* Loki/Grafana run via Docker Compose for the local demo. ELK is documented but
  not run, since Elasticsearch is memory-heavy for a 16 GB laptop — the JSON log
  format supports both.
* Trivy and the controller manifests pull `:latest`; pin specific versions for
  reproducible production pipelines.
```
