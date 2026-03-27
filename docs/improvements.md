# 개선 사항

Phase 1–6 완료 후 QC 과정에서 도출된 개선 포인트.
각 항목은 Context7 MCP 도구를 통해 공식 문서를 참조하여 검증되었습니다.

---

## 서빙 (Layer 5)

### 1. Nginx — `limit_req` 적용 누락

**문제**
`configs/nginx/nginx.conf`에서 `limit_req_zone`으로 `api_limit` 존을 정의했지만,
실제 location 블록에서 `limit_req` 지시어가 적용되지 않아 rate limiting이 동작하지 않습니다.

**해결책**
`configs/nginx/conf.d/` 하위의 서버 블록에 `limit_req`를 명시적으로 추가합니다.
현재 10 req/s + burst 20 설정 기준으로 `nodelay`를 추가하면 burst 범위 내 요청을 지연 없이 즉시 처리하고,
초과 요청만 503으로 거부합니다.

```nginx
# configs/nginx/conf.d/api.conf
location /predict {
    limit_req zone=api_limit burst=20 nodelay;
    proxy_pass http://api:8000;
}
```

공식 문서 참조: [NGINX Rate Limiting Guide](https://github.com/nginx/documentation/blob/main/content/nginx/admin-guide/security-controls/controlling-access-proxied-http.md)
— `burst=N nodelay`: burst 범위 내 요청을 즉시 처리, 초과 시 503 반환.

**우선순위**: 높음 (rate limiting이 선언만 되고 실제 미적용 상태)

---

### 2. Nginx — `/model/reload` 엔드포인트 인증 부재

**문제**
`/model/reload` 엔드포인트는 운영 모델을 교체하는 민감한 작업이지만 현재 인증 없이 외부에 노출됩니다.

**해결책**
Nginx 레벨에서 내부 네트워크만 허용하거나 `limit_except`로 POST를 제한합니다.

```nginx
location /model/reload {
    allow 10.0.0.0/8;
    allow 172.16.0.0/12;
    deny all;
    proxy_pass http://api:8000;
}
```

또는 FastAPI 레벨에서 Bearer 토큰 의존성을 추가합니다 (`Depends(verify_token)`).

**우선순위**: 높음

---

### 3. Gunicorn — 다중 워커 환경에서 `/model/reload` 동작 불일치

**문제**
`CLAUDE.md` Gotchas 항목에 기술되어 있듯, Gunicorn 워커 N개 중 reload 요청을 받은 워커에만
모델이 교체됩니다. 나머지 워커는 이전 모델을 계속 서빙합니다.

**해결책**
단기: `GUNICORN_WORKERS=1`로 설정하여 워커를 단일화합니다.
장기: 공유 메모리 또는 외부 레지스트리(Redis)를 사용해 워커 간 모델 상태를 동기화하거나,
워커 프리포크 전에 모델을 로드하는 구조로 전환합니다.

```python
# gunicorn/config.py — preload_app=True 설정 시 마스터 프로세스에서 모델 로드
preload_app = True  # 모든 워커가 동일한 모델 메모리를 공유 (CoW)
```

**우선순위**: 중간

---

## 모니터링 (Layer 6)

### 4. Prometheus — 데이터 보존 기간 미설정

**문제**
`configs/prometheus/prometheus.yml`에 retention 설정이 없어 기본값인 15일이 적용됩니다.
프로덕션 환경에서는 디스크 용량 예측과 데이터 보존 정책이 명시되어야 합니다.

**해결책**
`docker-compose.yml`의 Prometheus 서비스에 retention 플래그를 추가합니다.
공식 문서 권장사항에 따라 크기 기반 보존(`--storage.tsdb.retention.size`)을 함께 사용하고,
디스크 할당량의 80–85% 이하로 설정합니다.

```yaml
# docker-compose.yml — prometheus 서비스
services:
  prometheus:
    image: prom/prometheus:v3.10.0
    command:
      - "--config.file=/etc/prometheus/prometheus.yml"
      - "--storage.tsdb.path=/prometheus"
      - "--storage.tsdb.retention.time=30d"       # 프로덕션 권장: 30d~90d
      - "--storage.tsdb.retention.size=8GB"       # 디스크 10GB 기준 80%
      - "--storage.tsdb.wal-compression=true"     # WAL 압축 (v2.11+ 기본 활성화)
```

공식 문서 참조: [Prometheus Storage Docs](https://github.com/prometheus/prometheus/blob/main/docs/storage.md)
— retention.size는 할당 디스크의 80–85% 이하로 설정 권장.

**우선순위**: 중간

---

### 5. Grafana — Alerting 미구성 (드리프트 임계값 알림 부재)

**문제**
`evidently_drift_detected` 및 `evidently_drift_score` 메트릭이 Prometheus에 push되지만,
Grafana에서 이에 대한 Alert Rule과 알림 채널(Contact Point)이 구성되어 있지 않습니다.
드리프트 발생 시 담당자에게 자동 알림이 전송되지 않습니다.

**해결책**
`configs/grafana/` 아래에 alerting 프로비저닝 파일을 추가합니다.

```yaml
# configs/grafana/provisioning/alerting/drift_alerts.yaml
apiVersion: 1

contactPoints:
  - orgId: 1
    name: mlops-slack
    receivers:
      - uid: slack-receiver
        type: slack
        settings:
          url: ${SLACK_WEBHOOK_URL}
          recipient: "#mlops-alerts"
          username: grafana_bot
          title: |
            {{ template "slack.default.title" . }}
          text: |
            {{ len .Alerts.Firing }} alerts firing — drift detected in MLOps Pipeline

policies:
  - orgId: 1
    receiver: mlops-slack

groups:
  - orgId: 1
    name: drift-alerts
    folder: MLOps
    interval: 5m
    rules:
      - uid: drift-detected-rule
        title: "Data Drift Detected"
        condition: C
        data:
          - refId: A
            queryType: ""
            relativeTimeRange:
              from: 300
              to: 0
            datasourceUid: prometheus
            model:
              expr: evidently_drift_detected
              intervalMs: 1000
              maxDataPoints: 43200
          - refId: C
            queryType: ""
            relativeTimeRange:
              from: 0
              to: 0
            datasourceUid: "__expr__"
            model:
              type: threshold
              conditions:
                - evaluator:
                    params: [1]
                    type: gt
                  unloadEvaluator:
                    params: [0]
                    type: lt
        noDataState: NoData
        execErrState: Error
        for: 5m
        annotations:
          summary: "모델 입력 데이터 드리프트 감지됨"
          description: "evidently_drift_detected = 1 (drift_score: {{ $values.A }})"
```

공식 문서 참조: [Grafana Alerting File Provisioning](https://grafana.com/docs/grafana/latest/alerting/set-up/provision-alerting-resources/file-provisioning/)

**우선순위**: 높음

---

### 6. Evidently — 드리프트 감지 스케줄링 미연동

**문제**
`src/monitoring/evidently/drift_detector.py`의 `detect_drift()` 함수가 구현되어 있지만,
Prefect 플로우에서 주기적으로 호출되지 않습니다.
드리프트 감지는 수동 실행에 의존하고 있습니다.

**해결책**
Prefect를 사용해 드리프트 감지 플로우를 스케줄링합니다.
Evidently 공식 예시처럼 `DataDriftPreset(method="psi")`를 사용하면 PSI 기반 드리프트 측정이 가능합니다.

```python
# src/orchestration/flows/monitoring_flow.py (신규)
from prefect import flow, task
from prefect.schedules import CronSchedule
from src.monitoring.evidently.drift_detector import detect_drift, push_drift_metrics

@task
def run_drift_check(reference_path: str, current_path: str, pushgateway_url: str) -> dict:
    """예측 로그를 로드하고 드리프트를 감지한 후 Pushgateway에 push합니다."""
    import pandas as pd
    reference = pd.read_parquet(reference_path)
    current = pd.read_parquet(current_path)
    result = detect_drift(reference, current)
    push_drift_metrics(pushgateway_url, result["drift_detected"], result["drift_score"])
    return result

@flow(name="drift-monitoring", schedule=CronSchedule(cron="0 * * * *"))  # 매 1시간
def drift_monitoring_flow(
    reference_path: str = "s3://mlops/reference/predictions.parquet",
    current_path: str = "s3://mlops/current/predictions.parquet",
    pushgateway_url: str = "http://pushgateway:9091",
) -> None:
    """Evidently 드리프트 감지를 주기적으로 실행하고 Prometheus에 메트릭을 push합니다."""
    run_drift_check(reference_path, current_path, pushgateway_url)
```

Evidently `DataDriftPreset(method="psi")`는 PSI(Population Stability Index) 기반으로
수치형 특징의 분포 변화를 측정합니다 — 특히 추론 확률값 모니터링에 적합합니다.

**우선순위**: 높음

---

## 테스트

### 7. E2E 테스트 미작성

**문제**
`tests/e2e/` 디렉터리가 존재하지 않고 E2E 테스트가 없습니다.
전체 파이프라인(데이터 수집 → 학습 → 서빙 → 모니터링)의 통합 검증이 불가능합니다.

**해결책**
최소한 다음 시나리오를 포함하는 E2E 테스트를 작성합니다:
1. 학습 플로우 실행 → MLflow에 모델 등록 확인
2. 서빙 API 기동 → `/predict` 엔드포인트 이미지 추론 확인
3. Pushgateway → Prometheus → Grafana 메트릭 전파 확인

```python
# tests/e2e/test_full_pipeline.py
import pytest
import requests

@pytest.mark.e2e
def test_predict_endpoint_responds():
    """서빙 API가 이미지 추론 요청에 정상 응답하는지 확인합니다."""
    with open("tests/fixtures/sample.jpg", "rb") as f:
        response = requests.post(
            "http://localhost:8080/predict",
            files={"file": ("sample.jpg", f, "image/jpeg")},
            timeout=30,
        )
    assert response.status_code == 200
    payload = response.json()
    assert "predicted_class" in payload
    assert "confidence" in payload
    assert 0.0 <= payload["confidence"] <= 1.0
```

**우선순위**: 중간

---

### 8. 부하 테스트 미작성 (Locust)

**문제**
서빙 API의 처리 용량과 레이턴시 특성을 측정하는 부하 테스트가 없습니다.
Nginx rate limiting 설정(10 req/s, burst 20)의 적절성도 검증되지 않았습니다.

**해결책**
Locust를 사용해 `/predict` 엔드포인트에 대한 부하 테스트를 작성합니다.

```python
# tests/load/locustfile.py
from locust import HttpUser, task, between

class InferenceUser(HttpUser):
    """MLOps Pipeline 서빙 API 부하 테스트 사용자."""

    host = "http://localhost:8080"
    wait_time = between(0.05, 0.2)  # 5–200ms 대기 (초당 약 5–20 req/user)

    @task(10)
    def predict(self) -> None:
        """이미지 추론 엔드포인트 부하 테스트."""
        with open("tests/fixtures/sample.jpg", "rb") as f:
            self.client.post(
                "/predict",
                files={"file": ("sample.jpg", f, "image/jpeg")},
                name="/predict",
            )

    @task(1)
    def health_check(self) -> None:
        """헬스체크 엔드포인트 응답 확인."""
        self.client.get("/health", name="/health")
```

실행:
```bash
uv run locust -f tests/load/locustfile.py --headless \
    --users 50 --spawn-rate 5 --run-time 60s \
    --host http://localhost:8080
```

공식 문서 참조: [Locust Writing a Locustfile](https://github.com/locustio/locust/blob/master/docs/writing-a-locustfile.rst)

**우선순위**: 중간

---

## 인프라 (Layer 1)

### 9. Postgres — 헬스체크 없이 의존 서비스가 기동

**문제**
`docker-compose.yml`에서 MLflow, Prefect 등이 `depends_on: db`를 사용하지만,
`condition: service_healthy`가 설정되어 있지 않으면 DB 초기화 완료 전에 서비스가 기동될 수 있습니다.

**해결책**
```yaml
services:
  db:
    image: postgres:16.6-alpine
    healthcheck:
      test: ["CMD-SHELL", "pg_isready -U ${POSTGRES_USER} -d ${POSTGRES_DB}"]
      interval: 10s
      timeout: 5s
      retries: 5
      start_period: 30s

  mlflow:
    depends_on:
      db:
        condition: service_healthy
```

**우선순위**: 중간

---

### 10. MinIO — 버킷 버전 관리(Versioning) 미활성화

**문제**
모델 아티팩트와 데이터셋이 MinIO에 저장되지만 버킷 버전 관리가 활성화되어 있지 않아,
동일 경로에 업로드 시 이전 파일이 덮어씌워집니다.
MLflow가 이미 실험별로 아티팩트를 분리하지만, 학습 데이터 버킷(`datasets`)은 취약합니다.

**해결책**
`scripts/seed.sh`에서 MinIO mc 클라이언트로 버전 관리를 활성화합니다:

```bash
# scripts/seed.sh 추가
mc version enable local/datasets
mc version enable local/models
```

**우선순위**: 낮음

---

## CI/CD

### 11. GitHub Actions CI 파이프라인 미구성

**문제**
`.github/workflows/` 디렉터리가 없어 PR 생성 시 자동 lint, 테스트, Docker 이미지 빌드 검증이
실행되지 않습니다. 코드 품질은 로컬 실행에 의존합니다.

**해결책**
다음 워크플로우를 `.github/workflows/ci.yml`로 추가합니다.
Ruff + pytest 조합은 GitHub Actions 공식 Python CI 문서에서 권장하는 패턴입니다.

```yaml
# .github/workflows/ci.yml
name: CI

on:
  push:
    branches: [main]
  pull_request:
    branches: [main]

jobs:
  lint-and-test:
    runs-on: ubuntu-latest
    steps:
      - uses: actions/checkout@v5

      - name: Set up Python 3.11
        uses: actions/setup-python@v5
        with:
          python-version: "3.11"

      - name: Install uv
        run: pip install uv

      - name: Install dependencies
        run: uv sync

      - name: Lint with Ruff
        run: uv run ruff check --output-format=github .

      - name: Check formatting with Ruff
        run: uv run ruff format --diff .

      - name: Run unit tests
        run: uv run pytest tests/unit/ -v --junitxml=junit/test-results.xml

      - name: Upload test results
        uses: actions/upload-artifact@v4
        with:
          name: pytest-results
          path: junit/test-results.xml
        if: always()

  docker-build:
    runs-on: ubuntu-latest
    needs: lint-and-test
    steps:
      - uses: actions/checkout@v5

      - name: Build MLflow image
        run: docker build -t mlops/mlflow:ci docker/mlflow/

      - name: Build API image
        run: docker build -t mlops/api:ci docker/api/
```

공식 문서 참조:
- [GitHub Actions — Python lint with Ruff](https://docs.github.com/en/actions/tutorials/build-and-test-code/python)
- [GitHub Actions — Docker Build and Push](https://docs.github.com/en/actions/tutorials/publish-packages/publish-docker-images)

**우선순위**: 높음

---

## 우선순위 요약

| # | 항목 | 레이어 | 우선순위 |
|---|------|--------|--------|
| 1 | Nginx `limit_req` 적용 누락 | 서빙 | 높음 |
| 2 | `/model/reload` 인증 부재 | 서빙 | 높음 |
| 5 | Grafana Alerting 미구성 | 모니터링 | 높음 |
| 6 | Evidently 드리프트 스케줄링 미연동 | 모니터링 | 높음 |
| 11 | GitHub Actions CI 파이프라인 미구성 | CI/CD | 높음 |
| 3 | Gunicorn 다중 워커 reload 불일치 | 서빙 | 중간 |
| 4 | Prometheus retention 미설정 | 모니터링 | 중간 |
| 7 | E2E 테스트 미작성 | 테스트 | 중간 |
| 8 | Locust 부하 테스트 미작성 | 테스트 | 중간 |
| 9 | Postgres healthcheck 조건 미설정 | 인프라 | 중간 |
| 10 | MinIO 버킷 버전 관리 미활성화 | 인프라 | 낮음 |
