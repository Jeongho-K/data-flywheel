# Evidently

## 1. 핵심 철학/설계 사상

Evidently는 **"Monitoring as Code"** 를 표방하는 오픈소스 ML 모니터링 라이브러리다.
프로덕션 ML 모델의 데이터 드리프트, 타겟 드리프트, 모델 품질 저하를 코드 기반으로 탐지하고 자동화한다.

### 핵심 원리

- **두 가지 모드**: Report(시각적 분석)와 TestSuite(자동 pass/fail 검증)를 제공한다. Report는 탐색적 분석용이고, TestSuite는 CI/파이프라인에서 품질 게이트로 활용한다.
- **Preset 기반 설계**: 100+ 내장 메트릭을 목적별 Preset으로 묶어 제공한다. `DataDriftPreset`, `ClassificationPreset` 등 한 줄로 복잡한 모니터링 시나리오를 구성할 수 있다.
- **Reference vs Current 비교**: 모든 분석이 기준 데이터(reference)와 현재 데이터(current)의 비교로 이루어진다. 통계 검정(KS-test, PSI, Chi-square 등)을 자동 선택하여 분포 변화를 판단한다.
- **오케스트레이터 친화적**: Prefect, Airflow 등과 쉽게 통합되도록 설계되었다. 결과를 dict/JSON으로 추출하여 다운스트림 로직에 전달할 수 있다.
- **Prometheus/Grafana 연동**: 드리프트 메트릭을 Pushgateway로 전송하여 기존 모니터링 스택과 자연스럽게 통합한다.

---

## 2. 주요 기능 정리

### 2.1 Report --- 시각적 분석

Report는 reference 데이터와 current 데이터를 비교하여 시각적 HTML 리포트를 생성한다.
데이터 과학자가 드리프트 원인을 탐색적으로 분석할 때 유용하다.

```python
from evidently import Report
from evidently.presets import DataDriftPreset

report = Report([DataDriftPreset()])
result = report.run(reference_data=ref_df, current_data=curr_df)

# HTML 파일로 저장
result.save_html("drift_report.html")

# Python dict로 결과 추출
result_dict = result.as_dict()

# JSON 문자열로 추출
result_json = result.json()
```

**주요 출력 형식:**

| 메서드 | 반환 타입 | 용도 |
|--------|-----------|------|
| `save_html()` | HTML 파일 | 브라우저에서 시각적 분석 |
| `as_dict()` | `dict` | 파이프라인 내 프로그래밍적 처리 |
| `json()` | `str` (JSON) | API 응답, 로그 저장 |

### 2.2 Metric Presets --- 사전 정의된 메트릭 모음

Preset은 관련 메트릭을 하나로 묶은 편의 객체다. 한 줄로 여러 메트릭을 동시에 실행할 수 있다.

| Preset | 용도 | 필요 데이터 |
|--------|------|-------------|
| `DataDriftPreset` | 입력 데이터 분포 변화 탐지 | 입력 피처 |
| `DataQualityPreset` | 데이터 품질 (결측값, 이상치, 새로운 카테고리 등) | 입력 피처 |
| `TargetDriftPreset` | 예측/타겟 분포 변화 탐지 | 예측값 또는 타겟 |
| `ClassificationPreset` | 분류 모델 성능 (Accuracy, F1, ROC AUC 등) | 예측값 + 실제 라벨 |
| `RegressionPreset` | 회귀 모델 성능 (RMSE, MAE 등) | 예측값 + 실제값 |

```python
from evidently.presets import (
    ClassificationPreset,
    DataDriftPreset,
    DataQualityPreset,
    TargetDriftPreset,
)

# 여러 Preset을 동시에 실행
report = Report([
    DataDriftPreset(),
    DataQualityPreset(),
    TargetDriftPreset(),
])
result = report.run(reference_data=ref_df, current_data=curr_df)
```

### 2.3 TestSuite --- 자동 pass/fail 검증

TestSuite는 Preset이나 개별 메트릭에 pass/fail 조건을 추가하여 자동 검증을 수행한다.
CI/CD 파이프라인이나 Prefect 품질 게이트에서 "드리프트가 임계값을 초과하면 파이프라인 중단" 같은 로직에 활용한다.

```python
from evidently import Report
from evidently.presets import DataDriftPreset

# 방법 1: Preset에 include_tests 사용 (기본 임계값 적용)
report = Report([DataDriftPreset()], include_tests=True)
result = report.run(reference_data=ref_df, current_data=curr_df)

# 테스트 결과 확인
test_results = result.as_dict()
```

```python
# 방법 2: 개별 메트릭에 커스텀 조건 설정
from evidently import Report
from evidently.metrics import MissingValueCount, MinValue
from evidently.tests import eq, gte

report = Report([
    MissingValueCount(column="confidence", tests=[eq(0)]),
    MinValue(column="confidence", tests=[gte(0.1)]),
])
result = report.run(reference_data=ref_df, current_data=curr_df)
```

**TestSuite 활용 시나리오:**

| 시나리오 | 검증 조건 예시 |
|----------|---------------|
| 데이터 드리프트 게이트 | 드리프트된 컬럼 비율 < 30% |
| 데이터 품질 게이트 | 결측값 비율 = 0%, 새로운 카테고리 없음 |
| 모델 성능 게이트 | Accuracy > 0.85, F1 > 0.80 |
| 예측 분포 게이트 | confidence 최솟값 >= 0.1 |

### 2.4 ColumnMapping --- 데이터 컬럼 역할 정의

ColumnMapping은 DataFrame의 컬럼이 어떤 역할(타겟, 예측, 수치형 피처, 범주형 피처 등)을 하는지 명시적으로 선언한다.
Evidently가 자동으로 컬럼 타입을 추론하지만, 명시적 매핑이 더 정확하고 안정적이다.

```python
from evidently import ColumnMapping

column_mapping = ColumnMapping(
    target="actual_class",           # 실제 라벨 컬럼
    prediction="predicted_class",    # 예측 컬럼
    numerical_features=["confidence"],
    categorical_features=["predicted_class"],
)

report = Report([DataDriftPreset()])
result = report.run(
    reference_data=ref_df,
    current_data=curr_df,
    column_mapping=column_mapping,
)
```

**ColumnMapping 주요 필드:**

| 필드 | 설명 | 기본값 |
|------|------|--------|
| `target` | 실제 라벨 컬럼명 | 자동 추론 |
| `prediction` | 모델 예측 컬럼명 | 자동 추론 |
| `numerical_features` | 수치형 피처 목록 | 자동 추론 |
| `categorical_features` | 범주형 피처 목록 | 자동 추론 |
| `datetime` | 시간 컬럼명 | `None` |
| `id` | ID 컬럼명 (분석에서 제외) | `None` |

### 2.5 커스텀 메트릭

Preset 대신 개별 메트릭을 직접 조합하여 세밀한 모니터링을 구성할 수 있다.
특정 컬럼에 특정 통계 검정 방법을 지정하거나, 값 범위를 검사하는 등 Preset으로 커버되지 않는 시나리오에 유용하다.

```python
from evidently.metrics import ColumnDriftMetric, ColumnValueRangeMetric

# 개별 컬럼에 대한 드리프트 검사 (통계 검정 방법 지정)
report = Report([
    ColumnDriftMetric(column_name="confidence", method="psi"),
    ColumnDriftMetric(column_name="predicted_class", method="chi-square"),
])
result = report.run(reference_data=ref_df, current_data=curr_df)
```

**주요 드리프트 검정 방법:**

| 방법 | 적용 대상 | 설명 |
|------|-----------|------|
| `ks` (Kolmogorov-Smirnov) | 수치형 | 두 분포의 최대 차이 검정 |
| `psi` (Population Stability Index) | 수치형 | 분포 안정성 지수 |
| `chi-square` | 범주형 | 카이제곱 독립성 검정 |
| `jensenshannon` | 수치형/범주형 | Jensen-Shannon 발산 |
| `wasserstein` | 수치형 | Wasserstein 거리 (Earth Mover's Distance) |

### 2.6 Prometheus 연동

Evidently 결과를 Prometheus Pushgateway로 전송하면 Grafana 대시보드에서 드리프트 추이를 시계열로 모니터링할 수 있다.
주기적 배치 작업(Prefect flow)에서 실행하고, 결과를 push하는 패턴이 일반적이다.

```python
from prometheus_client import CollectorRegistry, Gauge, push_to_gateway


def push_drift_metrics(drift_result: dict, pushgateway_url: str) -> None:
    """Push Evidently drift metrics to Prometheus Pushgateway."""
    registry = CollectorRegistry()

    drift_detected = Gauge(
        "evidently_drift_detected",
        "1 if dataset drift was detected, else 0",
        registry=registry,
    )
    drift_score = Gauge(
        "evidently_drift_score",
        "Share of drifted columns (0.0 to 1.0)",
        registry=registry,
    )

    drift_detected.set(1.0 if drift_result["drift_detected"] else 0.0)
    drift_score.set(drift_result["drift_score"])

    push_to_gateway(pushgateway_url, job="evidently_drift", registry=registry)
```

**Grafana 알림 설정 예시:**
- `evidently_drift_detected == 1` 이면 Slack/이메일 알림 발송
- `evidently_drift_score > 0.5` 이면 Critical 등급 알림

---

## 3. 현재 프로젝트 활용 상태

### 3.1 구현된 기능

현재 프로젝트에서는 Evidently의 **DataDriftPreset만** 사용하고 있다.

**`src/monitoring/evidently/drift_detector.py`:**

| 함수 | 역할 |
|------|------|
| `build_dataframe_from_logs()` | JSONL 문자열을 DataFrame으로 변환 |
| `detect_drift()` | DataDriftPreset으로 드리프트 탐지, dict 반환 |
| `save_drift_report_html()` | HTML 리포트 생성 |
| `push_drift_metrics()` | Pushgateway에 `drift_detected`, `drift_score` 전송 |

**`src/monitoring/evidently/config.py`:**

`DriftConfig`(Pydantic Settings)로 S3 연결, 버킷명, lookback 기간, Pushgateway URL을 환경변수(`DRIFT_` prefix)로 관리한다.

**`src/orchestration/flows/monitoring_flow.py`:**

5개 task로 구성된 Prefect flow:

```
fetch_prediction_logs → fetch_reference_data → run_drift_detection → upload_drift_report
                                                      ↓
                                               push_drift_metrics (Pushgateway)
```

- `predicted_class`(범주형), `confidence`(수치형) 2개 컬럼만 모니터링
- lookback 기간(기본 1일)의 예측 로그를 reference 데이터와 비교

### 3.2 미사용 기능

| 기능 | 현재 상태 | 활용 가치 |
|------|-----------|-----------|
| `ClassificationPreset` | 미사용 | ground truth 라벨 확보 시 모델 성능 추적 |
| `TargetDriftPreset` | 미사용 | 예측 분포 변화 추적 (라벨 없이도 가능) |
| `DataQualityPreset` | 미사용 | 결측값, 이상치, 새로운 카테고리 탐지 |
| TestSuite (`include_tests`) | 미사용 | 파이프라인 품질 게이트 자동화 |
| `ColumnMapping` | 미사용 | 컬럼 역할 명시로 분석 안정성 향상 |
| 커스텀 메트릭 | 미사용 | 컬럼별 세밀한 검정 방법 지정 |

---

## 4. 미활용 기능 & 개선 포인트

### 4.1 ColumnMapping 적용 (즉시 적용 가능)

현재 `detect_drift()`는 ColumnMapping 없이 Evidently의 자동 추론에 의존한다.
`predicted_class`는 범주형, `confidence`는 수치형임을 명시하면 더 정확한 통계 검정이 적용된다.

```python
from evidently import ColumnMapping

MONITORING_COLUMN_MAPPING = ColumnMapping(
    prediction="predicted_class",
    numerical_features=["confidence"],
    categorical_features=["predicted_class"],
)


def detect_drift(
    reference: pd.DataFrame,
    current: pd.DataFrame,
    column_mapping: ColumnMapping | None = None,
) -> dict[str, Any]:
    """Run Evidently DataDriftPreset and return a summary dict."""
    report = Report([DataDriftPreset()])
    result = report.run(
        reference_data=reference,
        current_data=current,
        column_mapping=column_mapping or MONITORING_COLUMN_MAPPING,
    )
    # ... (기존 로직 동일)
```

### 4.2 TestSuite 품질 게이트 추가

TestSuite를 도입하면 "드리프트 비율이 임계값을 초과하면 자동으로 실패"하는 품질 게이트를 구현할 수 있다.
Prefect flow에서 이 결과에 따라 파이프라인을 중단하거나 알림을 발송한다.

```python
def check_drift_threshold(
    reference: pd.DataFrame,
    current: pd.DataFrame,
    column_mapping: ColumnMapping | None = None,
) -> dict[str, Any]:
    """Check if drift exceeds a threshold based on detect_drift results."""
    report = Report([DataDriftPreset()], include_tests=True)
    result = report.run(
        reference_data=reference,
        current_data=current,
        column_mapping=column_mapping or MONITORING_COLUMN_MAPPING,
    )

    result_dict = result.as_dict()
    # 테스트 결과에서 pass/fail 상태 추출
    tests = result_dict.get("tests", [])
    all_passed = all(t.get("status") == "SUCCESS" for t in tests)

    return {
        "passed": all_passed,
        "test_count": len(tests),
        "failed_tests": [t for t in tests if t.get("status") != "SUCCESS"],
        "result_dict": result_dict,
    }
```

### 4.3 ClassificationPreset 활용

ground truth 라벨(실제 정답)이 확보된 경우, ClassificationPreset으로 모델 성능을 자동 추적할 수 있다.
Active Learning 라운드 후 라벨이 확정되면 이 Preset을 실행하여 Accuracy, F1, ROC AUC 등의 변화를 모니터링한다.

```python
from evidently import ColumnMapping, Report
from evidently.presets import ClassificationPreset

column_mapping = ColumnMapping(
    target="actual_class",
    prediction="predicted_class",
)

report = Report([ClassificationPreset()])
result = report.run(
    reference_data=ref_df,        # 학습 데이터 기반 성능
    current_data=curr_df,         # 프로덕션 예측 + 실제 라벨
    column_mapping=column_mapping,
)
result.save_html("classification_report.html")
```

### 4.4 DataQualityPreset 추가

데이터 품질 모니터링은 드리프트 탐지보다 선행되어야 한다.
결측값, 이상치, 새로운 카테고리 등의 데이터 품질 문제가 드리프트 오탐의 원인이 될 수 있기 때문이다.

```python
from evidently import Report
from evidently.presets import DataQualityPreset

report = Report([DataQualityPreset()])
result = report.run(reference_data=ref_df, current_data=curr_df)

quality_dict = result.as_dict()
# 결측값 비율, 이상치 수, 새로운 카테고리 등 확인
```

**모니터링 파이프라인에 추가할 경우의 순서:**

```
데이터 품질 검사 (DataQualityPreset)
    ↓ pass
드리프트 탐지 (DataDriftPreset)
    ↓ pass
모델 성능 추적 (ClassificationPreset, 라벨 확보 시)
```

### 4.5 Prefect 품질 게이트 통합

TestSuite 결과를 Prefect task로 감싸면, 드리프트 임계값 초과 시 파이프라인을 자동 중단하고 Prefect 아티팩트로 실패 원인을 기록할 수 있다.

```python
from prefect import task
from prefect.artifacts import create_markdown_artifact


@task(name="run-quality-gate")
def run_quality_gate(
    reference: pd.DataFrame,
    current: pd.DataFrame,
) -> dict:
    """Run drift test suite and raise on failure."""
    result = check_drift_threshold(reference, current)

    if not result["passed"]:
        failed = result["failed_tests"]
        markdown = "## Drift Test Failed\n\n"
        for t in failed:
            markdown += f"- **{t.get('name', 'unknown')}**: {t.get('status')}\n"

        create_markdown_artifact(
            key="drift-test-failure",
            markdown=markdown,
        )
        raise RuntimeError(
            f"Drift test suite failed: {len(failed)}/{result['test_count']} tests failed"
        )

    logger.info("All %d drift tests passed.", result["test_count"])
    return result
```

**monitoring_flow.py에 통합하는 흐름:**

```python
@flow(name="monitoring-pipeline-v2")
def monitoring_pipeline_v2(...) -> dict:
    # Step 1-2: 데이터 fetch (기존 동일)
    current_df = fetch_prediction_logs(...)
    reference_df = fetch_reference_data(...)

    # Step 3: 품질 게이트 (신규)
    gate_result = run_quality_gate(reference_df, current_df)

    # Step 4: 드리프트 탐지 + 메트릭 push (기존 동일)
    drift_result = run_drift_detection(reference_df, current_df, pushgateway_url)

    # Step 5: 리포트 업로드 (기존 동일)
    report_key = upload_drift_report(reference_df, current_df, ...)

    return {**drift_result, "gate_passed": gate_result["passed"]}
```

### 4.6 추가 Prometheus 메트릭 확장

현재는 `drift_detected`와 `drift_score` 2개 메트릭만 push하고 있다.
컬럼별 드리프트 점수와 데이터 품질 메트릭을 추가하면 Grafana에서 더 세밀한 모니터링이 가능하다.

```python
def push_extended_drift_metrics(
    drift_result: dict[str, Any],
    pushgateway_url: str,
) -> None:
    """Push extended drift metrics including per-column scores."""
    registry = CollectorRegistry()

    # 기존 메트릭
    g_detected = Gauge("evidently_drift_detected", "...", registry=registry)
    g_score = Gauge("evidently_drift_score", "...", registry=registry)

    # 컬럼별 드리프트 점수 (신규)
    g_column = Gauge(
        "evidently_column_drift_score",
        "Per-column drift score",
        labelnames=["column"],
        registry=registry,
    )

    g_detected.set(1.0 if drift_result["drift_detected"] else 0.0)
    g_score.set(drift_result["drift_score"])

    for col, score in drift_result.get("column_drifts", {}).items():
        g_column.labels(column=col).set(score)

    push_to_gateway(pushgateway_url, job="evidently_drift", registry=registry)
```

---

## 5. 다른 도구와의 연결점

### Prometheus + Grafana (Layer 6)

드리프트 메트릭을 Pushgateway를 통해 Prometheus에 저장하고, Grafana 대시보드에서 시계열 추이를 시각화한다.
임계값 기반 알림을 설정하여 드리프트 발생 시 즉시 대응할 수 있다.

```
Evidently → Pushgateway → Prometheus → Grafana Dashboard
                                           ↓
                                    Alert (Slack, Email)
```

### Prefect (Layer 4)

모니터링 파이프라인을 Prefect flow로 오케스트레이션한다.
TestSuite 결과를 품질 게이트로 활용하고, HTML 리포트를 Prefect 아티팩트로 기록한다.
`flow.serve()`로 주기적 스케줄(daily, weekly) 실행을 설정한다.

### MLflow (Layer 3)

드리프트 점수를 MLflow 메트릭으로 로깅하여 모델 버전별 드리프트 추이를 추적할 수 있다.
champion 모델 승격/강등 조건에 드리프트 점수를 포함하면 자동화된 모델 거버넌스가 가능하다.

```python
import mlflow

with mlflow.start_run():
    mlflow.log_metric("drift_score", drift_result["drift_score"])
    mlflow.log_metric("drift_detected", int(drift_result["drift_detected"]))
    for col, score in drift_result["column_drifts"].items():
        mlflow.log_metric(f"drift_{col}", score)
```

### MinIO (Layer 1)

예측 로그(JSONL)를 MinIO `prediction-logs` 버킷에 날짜별로 저장하고, 드리프트 HTML 리포트를 `drift-reports` 버킷에 업로드한다.
reference 데이터도 MinIO에 저장하여 S3 호환 API로 일관되게 접근한다.

### Active Learning 루프

라운드별 예측 분포 변화를 드리프트로 추적한다.
새로운 라벨이 확보되면 ClassificationPreset으로 모델 성능 변화를 정량적으로 측정하고, 재학습 필요 여부를 자동으로 판단한다.
