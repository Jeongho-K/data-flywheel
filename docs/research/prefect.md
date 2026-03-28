# Prefect

## 1. 핵심 철학/설계 사상

Prefect는 **"코드 우선(Code-first)"** 오케스트레이션 프레임워크다.
기존 Python 코드에 데코레이터(`@flow`, `@task`)만 추가하면 워크플로우 오케스트레이션이 완성된다.
별도의 DAG 정의 파일이나 YAML 설정 없이, Python 함수 호출 그 자체가 파이프라인이 된다.

### 핵심 원리

- **데코레이터 기반 선언**: `@flow`와 `@task` 두 개의 데코레이터만으로 오케스트레이션 전체를 표현한다. 기존 Python 함수를 거의 수정 없이 워크플로우로 전환할 수 있다.
- **실패를 당연시하는 설계**: 분산 시스템에서 실패는 불가피하다. Prefect는 재시도(retries), 캐싱(caching), 트랜잭션(transactions)을 기본 제공하여 실패 시 복원력을 확보한다.
- **관찰 가능성(Observability)**: 모든 flow/task 실행이 자동으로 추적되며, Prefect UI에서 실행 상태, 로그, 소요 시간, 실패 원인을 실시간으로 확인할 수 있다.
- **점진적 채택(Incremental Adoption)**: 처음에는 단순한 `@flow` + `@task`만 사용하고, 필요에 따라 캐싱, 아티팩트, 트랜잭션 등 고급 기능을 점진적으로 도입할 수 있다.

### Prefect 3.0 주요 변경점

Prefect 3.0(현재 프로젝트 사용 버전: `3.6.23`)에서 대폭 단순화되었다:

| 구분 | Prefect 2.x | Prefect 3.x |
|------|-------------|-------------|
| 핵심 개념 | flows, tasks, deployments, work pools, agents | flows, tasks, deployments (단순화) |
| 실행 방식 | Worker/Agent 필수 | `flow.serve()` 만으로 배포 가능 |
| 캐싱 | `cache_key_fn` + `cache_expiration` | `cache_policy` 객체 (INPUTS, TASK_SOURCE 등) |
| 트랜잭션 | 미지원 | `with transaction()` 지원 |
| 아티팩트 | 기본 지원 | Markdown, Table, Image 등 확장 |

---

## 2. 주요 기능 정리

### 2.1 기본: `@flow`, `@task`

`@flow`는 워크플로우의 진입점이며, `@task`는 그 안에서 실행되는 개별 작업 단위다.
flow 안에서 task를 호출하면 Prefect가 자동으로 의존 관계를 추적하고 실행 상태를 기록한다.

```python
from prefect import flow, task

@task(name="prepare-dataset", retries=1, retry_delay_seconds=30)
def prepare_dataset(data_dir: str) -> str:
    """Verify dataset exists and return its path."""
    ...
    return data_dir

@task(name="validate-images", retries=1, retry_delay_seconds=10)
def validate_images(data_dir: str) -> dict:
    """Run CleanVision image quality validation."""
    ...
    return {"health_score": 0.95, "total_images": 5000}

@task(name="train-model", retries=0, timeout_seconds=7200)
def train_model(data_dir: str, model_name: str) -> dict:
    """Run model training with MLflow tracking."""
    ...
    return {"accuracy": 0.92}

@flow(
    name="training-pipeline",
    log_prints=True,
    description="End-to-end CV model training: data prep -> validation -> training",
)
def training_pipeline(data_dir: str = "data/raw/cifar10-demo") -> dict:
    dataset_path = prepare_dataset(data_dir)
    validation = validate_images(dataset_path)
    metrics = train_model(dataset_path, model_name="resnet18")
    return metrics
```

**주요 매개변수 정리:**

| 매개변수 | 적용 대상 | 설명 |
|----------|-----------|------|
| `retries` | flow, task | 실패 시 재시도 횟수 |
| `retry_delay_seconds` | flow, task | 재시도 간 대기 시간(초) |
| `timeout_seconds` | task | 최대 실행 시간(초), 초과 시 강제 종료 |
| `log_prints` | flow | `print()` 출력을 Prefect 로그로 캡처 |
| `description` | flow, task | UI에 표시되는 설명 문자열 |

---

### 2.2 캐싱 (`cache_policy`)

동일한 입력으로 task를 반복 호출할 때, 이전 결과를 재사용하여 불필요한 재실행을 방지한다.
데이터 검증처럼 입력이 바뀌지 않으면 결과도 동일한 작업에 특히 유용하다.

**캐시 정책 종류:**

| 정책 | 설명 |
|------|------|
| `INPUTS` | task 인자 값이 동일하면 캐시 반환 |
| `TASK_SOURCE` | task 소스 코드 + 인자가 동일하면 캐시 반환 |
| `FLOW_PARAMETERS` | 상위 flow 매개변수 기준 캐시 |
| `NO_CACHE` | 캐싱 비활성화 (기본값) |

```python
from prefect import task
from prefect.cache_policies import INPUTS
from datetime import timedelta

@task(
    cache_policy=INPUTS,
    cache_expiration=timedelta(hours=1),
)
def validate_images(data_dir: str) -> dict:
    """Same data_dir -> cached result returned without re-execution."""
    ...
```

**동작 방식:**
1. 첫 번째 호출: `validate_images("data/raw/cifar10-demo")` -- 실제 실행, 결과 캐시 저장
2. 동일 인자로 재호출 (1시간 이내): 캐시된 결과 즉시 반환, CleanVision 실행 생략
3. 인자 변경 또는 1시간 경과: 캐시 무효화, 재실행

---

### 2.3 아티팩트 (Artifacts)

task 실행 결과를 Prefect UI에서 바로 확인할 수 있는 구조화된 출력물이다.
Markdown 테이블, JSON 데이터, 이미지 링크 등을 아티팩트로 기록하면 별도 도구 없이 UI에서 파이프라인 결과를 검토할 수 있다.

**아티팩트 유형:**

| 함수 | 용도 |
|------|------|
| `create_markdown_artifact` | Markdown 형식 보고서 |
| `create_table_artifact` | 테이블 데이터 (리스트 of 딕셔너리) |
| `create_link_artifact` | 외부 링크 (MLflow UI, S3 리포트 등) |
| `create_progress_artifact` | 진행률 표시 |

```python
from prefect.artifacts import create_markdown_artifact, create_table_artifact

@task
def report_validation(results: dict) -> None:
    markdown = f"""## Image Validation Report
| Metric | Value |
|--------|-------|
| Total Images | {results['total_images']} |
| Health Score | {results['health_score']:.2f} |
"""
    create_markdown_artifact(key="image-validation", markdown=markdown)
```

테이블 형태의 아티팩트도 생성 가능하다:

```python
@task
def report_training_metrics(metrics: dict) -> None:
    table_data = [{"Metric": k, "Value": f"{v:.4f}"} for k, v in metrics.items()]
    create_table_artifact(
        key="training-metrics",
        table=table_data,
        description="Final training metrics from the latest run",
    )
```

아티팩트의 `key`는 동일 키로 새 아티팩트를 생성하면 이력이 누적되어 시간에 따른 변화를 추적할 수 있다.

---

### 2.4 상태 변경 훅 (State Change Hooks)

flow 또는 task의 상태가 변경될 때 자동으로 실행되는 콜백 함수다.
파이프라인 실패 시 알림 전송, 완료 시 요약 로깅 등에 활용한다.

**지원하는 훅:**

| 훅 | 트리거 시점 |
|----|-------------|
| `on_completion` | 성공적으로 완료 시 |
| `on_failure` | 실패 시 |
| `on_cancellation` | 취소 시 |
| `on_crashed` | 비정상 종료 시 |
| `on_running` | 실행 시작 시 |

```python
from prefect import flow
from prefect.states import State
import logging

logger = logging.getLogger(__name__)

def on_pipeline_failure(flow, flow_run, state: State):
    logger.error("Pipeline %s failed: %s", flow_run.name, state.message)

def on_pipeline_completion(flow, flow_run, state: State):
    logger.info("Pipeline %s completed in %s", flow_run.name, flow_run.total_run_time)

@flow(on_failure=[on_pipeline_failure], on_completion=[on_pipeline_completion])
def training_pipeline(...):
    ...
```

훅은 리스트로 전달하므로 여러 개의 콜백을 동시에 등록할 수 있다.
예를 들어 실패 시 로깅 + Slack 알림 + 메트릭 기록을 모두 수행할 수 있다.

---

### 2.5 트랜잭션 (Transactions)

여러 task를 하나의 원자적 단위로 묶어, 중간에 실패하면 이전 task의 결과를 롤백할 수 있다.
모델 등록처럼 부분 실패가 일관성 문제를 야기하는 작업에 필수적이다.

```python
from prefect import task, flow
from prefect.transactions import transaction

@task
def register_model(model, name): ...

@register_model.on_rollback
def cleanup_model(txn):
    """Delete partially registered model on failure."""
    ...

@flow
def safe_training():
    with transaction():
        model = train()
        register_model(model, "my-model")
        validate_model(model)  # if this fails, rollback triggers
```

**동작 순서:**
1. `train()` 실행 -- 성공
2. `register_model()` 실행 -- 성공, MLflow에 모델 등록됨
3. `validate_model()` 실행 -- 실패!
4. `cleanup_model()` 롤백 핸들러 자동 호출 -- 등록된 모델 삭제
5. 시스템이 일관된 상태로 복원됨

트랜잭션 없이는 3단계에서 실패하면 불완전한 모델이 레지스트리에 남게 된다.

---

### 2.6 결과 저장 (Result Persistence)

task 결과를 외부 저장소에 영구 보관하여, 파이프라인 재실행 시 중간 결과부터 이어서 실행할 수 있다.
장시간 학습 파이프라인에서 특히 중요하다 -- 학습 완료 후 후처리 단계에서 실패해도 학습을 다시 실행하지 않아도 된다.

```python
@task(persist_result=True, result_storage="s3-bucket/prefect-results")
def train_model(config: dict) -> dict:
    ...
```

**저장소 옵션:**

| 저장소 | 설정 예시 |
|--------|-----------|
| 로컬 파일시스템 | `LocalFileSystem(basepath="/tmp/prefect-results")` |
| S3 / MinIO | `"s3-bucket/prefect-results"` (Prefect Block 사전 등록 필요) |
| GCS | `"gcs-bucket/prefect-results"` |

캐싱과 결합하면 더 강력하다: 캐시 정책으로 "재실행 필요 여부"를 판단하고, 결과 저장소에서 "이전 결과"를 불러온다.

---

### 2.7 동시성 제어 (Concurrency)

동시에 실행되는 task 수를 제한하여 GPU, API rate limit 등 공유 자원의 과부하를 방지한다.

```python
from prefect import flow, task
from prefect.concurrency.sync import concurrency

@task
def process_with_limit():
    with concurrency("gpu-training", occupy=1):
        # Only N tasks can run in this block simultaneously
        ...
```

사전에 Prefect에서 동시성 제한을 설정해야 한다:

```bash
# CLI로 동시성 제한 생성 (GPU 1개만 동시 사용)
prefect concurrency-limit create gpu-training 1

# 또는 API 호출 제한
prefect concurrency-limit create external-api 5
```

**활용 시나리오:**

| 자원 | 제한 값 | 이유 |
|------|---------|------|
| GPU 학습 | 1 | GPU 메모리 부족 방지 |
| S3 업로드 | 5 | MinIO 연결 수 제한 |
| 외부 API | 10 | Rate limit 준수 |

---

## 3. 현재 프로젝트 활용 상태

### 3.1 파일 구조

```
src/orchestration/
├── __init__.py
├── serve.py                          # 배포 및 스케줄링
├── flows/
│   ├── __init__.py
│   ├── training_pipeline.py          # 학습 파이프라인 flow
│   └── monitoring_flow.py            # 드리프트 모니터링 flow
└── tasks/
    ├── __init__.py
    ├── data_tasks.py                 # 데이터 준비 + 검증 tasks
    └── training_tasks.py             # 모델 학습 task
```

### 3.2 사용 중인 기능

| 기능 | 사용 위치 | 상세 |
|------|-----------|------|
| `@flow` | `training_pipeline.py`, `monitoring_flow.py` | 2개 flow 정의 |
| `@task` | `data_tasks.py`, `training_tasks.py`, `monitoring_flow.py` | 총 7개 task |
| `retries` + `retry_delay_seconds` | `data_tasks.py`, `monitoring_flow.py` | 네트워크 의존 작업에 재시도 설정 |
| `timeout_seconds` | `training_tasks.py` | 학습 task에 2시간 타임아웃 |
| `flow.serve()` | `serve.py` | cron 스케줄 기반 배포 |

### 3.3 미사용 기능

| 기능 | 현재 상태 | 도입 시 이점 |
|------|-----------|--------------|
| 캐싱 (`cache_policy`) | 미사용 | 동일 데이터 재검증 방지 (수분 절약) |
| 아티팩트 (Artifacts) | 미사용 | UI에서 검증/학습 결과 즉시 확인 |
| 상태 훅 (Hooks) | 미사용 | 실패 알림, 완료 시 요약 자동화 |
| 트랜잭션 (Transactions) | 미사용 | 모델 등록 실패 시 안전한 롤백 |
| 결과 저장 (Persistence) | 미사용 | 파이프라인 중간 재시작 지원 |
| 동시성 제어 | 미사용 | GPU 자원 보호 |

---

## 4. 미활용 기능 & 개선 포인트

### 4.1 캐싱 도입 -- `validate_images` task

데이터가 변경되지 않았다면 CleanVision 검증을 매번 실행할 필요가 없다.
`INPUTS` 정책으로 `data_dir`가 동일하면 캐시를 반환하도록 한다.

**대상 파일:** `src/orchestration/tasks/data_tasks.py`

**Before:**
```python
@task(name="validate-images", retries=1, retry_delay_seconds=10)
def validate_images(data_dir: str) -> dict[str, Any]:
    ...
```

**After:**
```python
from prefect.cache_policies import INPUTS
from datetime import timedelta

@task(
    name="validate-images",
    retries=1,
    retry_delay_seconds=10,
    cache_policy=INPUTS,
    cache_expiration=timedelta(hours=1),
)
def validate_images(data_dir: str) -> dict[str, Any]:
    ...
```

**효과:** 동일 `data_dir`로 1시간 내 재실행 시 CleanVision 스캔 생략. 개발/디버깅 중 반복 실행 속도 대폭 향상.

---

### 4.2 아티팩트 도입 -- 검증 결과 + 학습 메트릭

Prefect UI에서 파이프라인 결과를 바로 확인할 수 있도록 아티팩트를 추가한다.

#### 4.2.1 이미지 검증 아티팩트

**대상 파일:** `src/orchestration/tasks/data_tasks.py`

**Before:**
```python
@task(name="validate-images", retries=1, retry_delay_seconds=10)
def validate_images(data_dir: str) -> dict[str, Any]:
    from src.data.validation import validate_image_dataset

    train_dir = Path(data_dir) / "train"
    report = validate_image_dataset(train_dir)
    logger.info(
        "Image validation: %d images, %d issues, health=%.2f",
        report.total_images, report.issues_found, report.health_score,
    )
    return report.to_dict()
```

**After:**
```python
from prefect.artifacts import create_markdown_artifact

@task(name="validate-images", retries=1, retry_delay_seconds=10)
def validate_images(data_dir: str) -> dict[str, Any]:
    from src.data.validation import validate_image_dataset

    train_dir = Path(data_dir) / "train"
    report = validate_image_dataset(train_dir)
    logger.info(
        "Image validation: %d images, %d issues, health=%.2f",
        report.total_images, report.issues_found, report.health_score,
    )

    result = report.to_dict()
    create_markdown_artifact(
        key="image-validation",
        markdown=f"""## Image Validation Report
| Metric | Value |
|--------|-------|
| Total Images | {result['total_images']} |
| Issues Found | {result['issues_found']} |
| Health Score | {result['health_score']:.2f} |
""",
        description=f"CleanVision scan for {data_dir}",
    )
    return result
```

#### 4.2.2 학습 메트릭 아티팩트

**대상 파일:** `src/orchestration/tasks/training_tasks.py`

**Before:**
```python
    metrics = train(config)
    logger.info("Training complete: %s", metrics)
    return metrics
```

**After:**
```python
    from prefect.artifacts import create_table_artifact, create_link_artifact

    metrics = train(config)
    logger.info("Training complete: %s", metrics)

    create_table_artifact(
        key="training-metrics",
        table=[{"Metric": k, "Value": f"{v:.4f}"} for k, v in metrics.items()],
        description=f"Training results: {model_name}, {epochs} epochs",
    )
    create_link_artifact(
        key="mlflow-run",
        link=f"{mlflow_tracking_uri}",
        description="MLflow experiment tracking UI",
    )
    return metrics
```

**효과:** Prefect UI의 Artifacts 탭에서 매 실행마다 검증 보고서와 학습 결과를 즉시 확인 가능. 동일 `key`를 사용하므로 시간에 따른 메트릭 변화를 추적할 수 있다.

---

### 4.3 상태 훅 도입 -- 파이프라인 실패/완료 알림

**대상 파일:** `src/orchestration/flows/training_pipeline.py`

**Before:**
```python
@flow(
    name="training-pipeline",
    log_prints=True,
    retries=0,
    description="End-to-end CV model training: data prep -> validation -> training",
)
def training_pipeline(...) -> dict[str, float]:
    ...
```

**After:**
```python
import logging
from prefect.states import State

logger = logging.getLogger(__name__)

def on_training_failure(flow, flow_run, state: State) -> None:
    logger.error(
        "Training pipeline '%s' FAILED: %s (duration: %s)",
        flow_run.name, state.message, flow_run.total_run_time,
    )

def on_training_completion(flow, flow_run, state: State) -> None:
    logger.info(
        "Training pipeline '%s' completed successfully (duration: %s)",
        flow_run.name, flow_run.total_run_time,
    )

@flow(
    name="training-pipeline",
    log_prints=True,
    retries=0,
    description="End-to-end CV model training: data prep -> validation -> training",
    on_failure=[on_training_failure],
    on_completion=[on_training_completion],
)
def training_pipeline(...) -> dict[str, float]:
    ...
```

**효과:** 파이프라인 실패 시 구조화된 에러 로그가 남고, 향후 Slack/이메일 알림 콜백을 훅 리스트에 추가하기만 하면 된다. 모니터링 파이프라인(`monitoring_flow.py`)에도 동일하게 적용 가능하다.

---

### 4.4 트랜잭션 도입 -- 모델 등록 안전성

학습 후 모델을 MLflow에 등록하는 과정에서, 후속 검증이 실패하면 등록된 모델을 롤백해야 한다.

**대상 파일:** `src/orchestration/flows/training_pipeline.py`

**Before:**
```python
    # Step 3: Train model
    metrics = train_model(
        data_dir=str(dataset_path),
        ...
        registered_model_name=registered_model_name,
    )
```

**After:**
```python
    from prefect.transactions import transaction

    # Step 3: Train model with transactional model registration
    with transaction():
        metrics = train_model(
            data_dir=str(dataset_path),
            ...
            registered_model_name=registered_model_name,
        )
        # Future: add post-training validation here
        # If validation fails, rollback deletes the registered model
```

`train_model` task에 `on_rollback` 핸들러를 등록하면, 트랜잭션 내 후속 작업 실패 시 MLflow에서 모델 버전을 자동 삭제할 수 있다.

---

### 4.5 개선 우선순위

즉시 적용 가능하면서 효과가 큰 순서로 정렬했다:

| 순위 | 기능 | 난이도 | 효과 | 이유 |
|------|------|--------|------|------|
| 1 | 아티팩트 | 낮음 | 높음 | 코드 3~5줄 추가, UI 가시성 대폭 향상 |
| 2 | 상태 훅 | 낮음 | 중간 | 콜백 함수 정의 + 데코레이터 인자 추가 |
| 3 | 캐싱 | 낮음 | 중간 | import 1줄 + 데코레이터 인자 2개 추가 |
| 4 | 트랜잭션 | 중간 | 높음 | 롤백 핸들러 구현 필요 |
| 5 | 결과 저장 | 중간 | 중간 | Prefect Block(S3 연동) 사전 설정 필요 |
| 6 | 동시성 제어 | 낮음 | 낮음 | 현재 단일 GPU 환경에서는 우선순위 낮음 |

---

## 5. 다른 도구와의 연결점

### 5.1 CleanVision/CleanLab + Prefect 아티팩트

CleanVision 검증 결과를 Prefect 아티팩트로 기록하면, Prefect UI에서 데이터 품질을 바로 확인할 수 있다.
별도로 로그를 뒤지거나 S3에서 리포트를 다운로드할 필요가 없다.

```python
# src/orchestration/tasks/data_tasks.py
from prefect.artifacts import create_markdown_artifact, create_table_artifact

@task(name="validate-images")
def validate_images(data_dir: str) -> dict[str, Any]:
    report = validate_image_dataset(Path(data_dir) / "train")
    result = report.to_dict()

    # Issue breakdown as table artifact
    issue_rows = [
        {"Issue Type": k.replace("issue_", ""), "Count": v}
        for k, v in result.items() if k.startswith("issue_")
    ]
    if issue_rows:
        create_table_artifact(key="cleanvision-issues", table=issue_rows)

    return result
```

### 5.2 MLflow + 상태 훅 / 트랜잭션

**상태 훅:** 학습 파이프라인 완료 시 MLflow run의 요약 정보를 로깅한다.

```python
def on_training_completion(flow, flow_run, state: State) -> None:
    result = state.result()
    if result and "mlflow_run_id" in result:
        logger.info(
            "MLflow run %s completed. View at: %s/#/experiments/.../runs/%s",
            result["mlflow_run_id"], MLFLOW_URI, result["mlflow_run_id"],
        )
```

**트랜잭션:** MLflow 모델 등록을 트랜잭션으로 감싸면, 후속 검증 실패 시 모델 버전을 안전하게 삭제한다. 프로덕션 레지스트리에 검증되지 않은 모델이 남는 것을 방지한다.

### 5.3 Evidently + Prefect 품질 게이트

Evidently의 `TestSuite` 결과를 Prefect flow의 조건 분기에 활용한다.
드리프트가 감지되면 flow를 중단하거나 경고를 발생시킨다.

```python
# src/orchestration/flows/monitoring_flow.py
@task(name="run-drift-detection")
def run_drift_detection(reference, current, pushgateway_url) -> dict:
    result = detect_drift(reference, current)

    # Quality gate: drift detected -> create warning artifact
    if result["drift_detected"]:
        create_markdown_artifact(
            key="drift-alert",
            markdown=f"**Drift Detected!** Score: {result['drift_score']:.3f}",
        )

    push_drift_metrics(pushgateway_url=pushgateway_url, ...)
    return result
```

모니터링 flow에서 드리프트 점수가 임계값을 초과하면 자동으로 재학습 파이프라인을 트리거하는 구조도 가능하다:

```python
@flow(name="monitoring-pipeline")
def monitoring_pipeline(...):
    ...
    drift_result = run_drift_detection(reference, current, pushgateway_url)

    if drift_result["drift_detected"] and drift_result["drift_score"] > 0.3:
        logger.warning("Significant drift detected, triggering retraining...")
        training_pipeline(data_dir="data/raw/cifar10-demo")  # sub-flow call
```

### 5.4 DVC + Prefect task

파이프라인 시작 시 `dvc pull`로 최신 데이터를 가져오고, Active Learning 라운드 후 `dvc add/push`로 데이터를 버전 관리한다.

```python
import subprocess
from prefect import task

@task(name="dvc-pull", retries=2, retry_delay_seconds=10)
def dvc_pull(data_dir: str) -> str:
    """Pull latest data version from DVC remote."""
    subprocess.run(["dvc", "pull", data_dir], check=True)
    return data_dir

@task(name="dvc-push")
def dvc_push(data_dir: str) -> None:
    """Version and push updated data to DVC remote."""
    subprocess.run(["dvc", "add", data_dir], check=True)
    subprocess.run(["dvc", "push"], check=True)
```

이를 학습 파이프라인에 통합하면:

```python
@flow(name="training-pipeline")
def training_pipeline(data_dir: str = "data/raw/cifar10-demo"):
    dvc_pull(data_dir)               # 1. Pull latest data
    dataset_path = prepare_dataset(data_dir)  # 2. Verify structure
    validation = validate_images(str(dataset_path))  # 3. Quality check
    metrics = train_model(...)        # 4. Train
    return metrics
```

---

## 참고 자료

- [Prefect 공식 문서](https://docs.prefect.io/)
- [Prefect GitHub](https://github.com/PrefectHQ/prefect)
- [Prefect 3.x 마이그레이션 가이드](https://docs.prefect.io/latest/resources/upgrade-prefect-3/)
