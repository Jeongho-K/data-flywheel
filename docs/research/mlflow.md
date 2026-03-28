# MLflow

## 1. 핵심 철학 / 설계 사상

MLflow는 ML 라이프사이클 전체를 하나의 플랫폼에서 관리하기 위해 설계되었다.

- **실험 추적 -> 모델 패키징 -> 모델 레지스트리 -> 서빙**의 전체 흐름을 단일 인터페이스로 제공한다.
- **프레임워크 독립적**: PyTorch, TensorFlow, scikit-learn 등 어떤 모델 프레임워크든 동일한 API로 동작한다.
- **실험 재현성**: 파라미터, 메트릭, 아티팩트, 코드 버전을 한 곳에서 추적하여 언제든 실험을 재현할 수 있다.
- **Model Registry**: 모델 버전 관리와 배포 워크플로우의 중심 역할을 한다. 별칭(alias) 기반으로 champion/challenger 패턴을 지원한다.

---

## 2. 주요 기능 정리

### 2.1 실험 추적 (Experiment Tracking)

MLflow의 가장 기본적인 기능으로, 모든 학습 실행(run)의 파라미터, 메트릭, 아티팩트를 기록한다.

```python
import mlflow

mlflow.set_tracking_uri("http://localhost:5050")
mlflow.set_experiment("my-experiment")

with mlflow.start_run():
    mlflow.log_params({
        "model_name": "resnet18",
        "learning_rate": 1e-3,
        "batch_size": 32,
    })

    for epoch in range(num_epochs):
        train_loss, val_acc = train_one_epoch(model, train_loader, val_loader)
        mlflow.log_metrics(
            {"train_loss": train_loss, "val_accuracy": val_acc},
            step=epoch,
        )

    mlflow.pytorch.log_model(
        model,
        name="model",
        registered_model_name="ImageClassifier",
    )
```

핵심 함수:
- `log_params()` -- 하이퍼파라미터 기록 (run당 1회)
- `log_metrics()` -- 메트릭 기록 (step 지정으로 epoch별 추적 가능)
- `log_model()` -- 모델 아티팩트 저장 + 선택적 레지스트리 등록

### 2.2 PyTorch Autolog

`mlflow.pytorch.autolog()`를 호출하면 PyTorch Lightning 기반 학습 시 loss, optimizer 파라미터, 모델 구조 등을 자동으로 기록한다. 순수 PyTorch 루프에서는 optimizer 파라미터와 모델 summary 정도를 자동 기록한다.

```python
import mlflow

# 한 줄로 자동 로깅 활성화
mlflow.pytorch.autolog(log_models=False)  # 수동 best model 로깅과 충돌 방지

with mlflow.start_run():
    for epoch in range(num_epochs):
        train_loss = train_one_epoch(model, train_loader)
        val_acc = evaluate(model, val_loader)
        # autolog이 자동으로 optimizer params 등 기록
        # 수동으로 epoch별 메트릭도 추가 가능
        mlflow.log_metrics({"val_accuracy": val_acc, "train_loss": train_loss}, step=epoch)
```

`log_models=False` 옵션이 중요한 이유: autolog은 학습 종료 시 자동으로 모델을 저장하려 하는데, best model을 수동으로 선택하여 저장하는 패턴과 충돌할 수 있다.

### 2.3 시스템 메트릭 로깅

학습 중 GPU, CPU, 메모리, 디스크 I/O 등 시스템 리소스 사용량을 자동으로 수집한다. 병목 지점 분석과 리소스 최적화에 유용하다.

```python
# GPU, CPU, 메모리, 디스크 I/O 자동 수집
mlflow.enable_system_metrics_logging()

with mlflow.start_run():
    # 학습 중 시스템 리소스 사용량이 자동으로 기록됨
    train(model, train_loader)
```

수집 항목:
- CPU 사용률, 메모리 사용량
- GPU 사용률, GPU 메모리 (CUDA 환경)
- 디스크 I/O, 네트워크 I/O

### 2.4 모델 시그니처 & Input Example

모델의 입출력 스키마를 명시적으로 기록한다. 서빙 시 입력 검증과 문서화에 활용된다.

```python
from mlflow.models import infer_signature
import torch
import numpy as np

# 샘플 입력/출력으로 시그니처 추론
sample_input = torch.randn(1, 3, 224, 224)
with torch.no_grad():
    sample_output = model(sample_input.to(device))

signature = infer_signature(
    sample_input.numpy(),
    sample_output.cpu().numpy()
)

mlflow.pytorch.log_model(
    model,
    name="model",
    signature=signature,
    input_example=sample_input.numpy(),
    registered_model_name="ImageClassifier",
)
```

`signature`의 역할:
- 모델이 기대하는 입력 shape과 dtype을 명시
- 서빙 엔드포인트에서 잘못된 입력을 사전에 거부 가능
- MLflow UI에서 모델 입출력 스키마를 바로 확인 가능

`input_example`의 역할:
- 모델 테스트용 샘플 데이터를 아티팩트로 저장
- 모델 로딩 후 즉시 추론 테스트 가능

### 2.5 모델 별칭 (Champion / Challenger)

MLflow 2.x에서 도입된 별칭(alias) 시스템으로, 기존 Stage(Staging/Production) 방식을 대체한다. 하나의 모델에 여러 별칭을 부여하여 배포 워크플로우를 유연하게 관리한다.

```python
from mlflow import MlflowClient

client = MlflowClient()

# 학습 완료 후 새 모델에 challenger 별칭 부여
client.set_registered_model_alias(
    name="ImageClassifier",
    alias="challenger",
    version=model_version,
)

# 검증 통과 후 champion으로 승격
client.set_registered_model_alias(
    name="ImageClassifier",
    alias="champion",
    version=model_version,
)

# 서빙에서 champion 모델 로딩
model = mlflow.pytorch.load_model("models:/ImageClassifier@champion")
```

워크플로우:
1. 새 모델 학습 완료 -> `challenger` 별칭 부여
2. 검증(드리프트 검사, 성능 비교) 통과 -> `champion` 별칭 재할당
3. 서빙 서버가 `@champion` 별칭으로 모델 로딩 -> 무중단 교체

### 2.6 모델 태그 & 메타데이터

run에 태그를 부여하여 검색과 분류를 용이하게 한다. 학습 조건, 데이터셋 정보, 실험 컨텍스트 등을 자유롭게 기록할 수 있다.

```python
mlflow.set_tags({
    "model_type": "resnet18",
    "dataset": "cifar10",
    "framework": "pytorch",
    "training_round": "5",
})
```

태그는 메트릭과 달리 문자열 값을 저장하며, `search_runs()`에서 필터링 조건으로 활용된다.

### 2.7 실험 검색 & 비교

프로그래밍 방식으로 실험 결과를 검색하고 비교한다. 자동화된 모델 선택과 리포팅에 활용된다.

```python
runs = mlflow.search_runs(
    experiment_names=["active-learning"],
    filter_string="metrics.val_accuracy > 0.8",
    order_by=["metrics.val_accuracy DESC"],
)
```

반환 결과는 pandas DataFrame이므로 추가 분석이 바로 가능하다.

---

## 3. 현재 프로젝트 활용 상태

### 사용 중인 기능

| 파일 | 기능 | 설명 |
|---|---|---|
| `src/training/trainers/classification_trainer.py` | `mlflow.log_params()` | 모든 학습 하이퍼파라미터 수동 기록 |
| `src/training/trainers/classification_trainer.py` | `mlflow.log_metrics()` | epoch별 train_loss, train_accuracy, val_loss, val_accuracy 수동 기록 |
| `src/training/trainers/classification_trainer.py` | `mlflow.pytorch.log_model()` | best model 저장 + 모델 레지스트리 등록 |
| `src/serving/api/dependencies.py` | `mlflow.pytorch.load_model()` | 버전 번호로 모델 로딩 (`models:/{name}/{version}`) |
| `src/training/configs/train_config.py` | `TrainConfig` | experiment_name, mlflow_tracking_uri, registered_model_name 설정 |

### 미사용 기능

- `mlflow.pytorch.autolog()` -- 자동 로깅
- `mlflow.enable_system_metrics_logging()` -- 시스템 메트릭
- `infer_signature()` / `input_example` -- 모델 시그니처
- 모델 별칭 (champion/challenger)
- `mlflow.set_tags()` -- run 태그
- `mlflow.search_runs()` -- 프로그래밍 방식 검색

---

## 4. 미활용 기능 & 개선 포인트

### 4.1 Autolog 적용

**파일**: `src/training/trainers/classification_trainer.py`

현재 모든 파라미터와 메트릭을 수동으로 기록하고 있다. autolog을 추가하면 optimizer 파라미터 등 누락될 수 있는 정보를 자동으로 보완할 수 있다.

```python
# Before (line 120~134)
with mlflow.start_run() as run:
    mlflow.log_params({
        "model_name": config.model_name,
        ...
    })

# After
mlflow.pytorch.autolog(log_models=False)  # best model은 수동 저장

with mlflow.start_run() as run:
    mlflow.log_params({
        "model_name": config.model_name,
        ...
    })
```

`log_models=False`를 반드시 설정해야 한다. 현재 코드가 best model을 직접 선택하여 저장하는 패턴을 사용하고 있기 때문이다.

### 4.2 시스템 메트릭 로깅 적용

**파일**: `src/training/trainers/classification_trainer.py`

GPU 메모리 부족이나 CPU 병목을 사후 분석하려면 시스템 메트릭이 필수적이다.

```python
# Before (line 117~120)
mlflow.set_tracking_uri(config.mlflow_tracking_uri)
mlflow.set_experiment(config.experiment_name)

with mlflow.start_run() as run:

# After
mlflow.set_tracking_uri(config.mlflow_tracking_uri)
mlflow.set_experiment(config.experiment_name)
mlflow.enable_system_metrics_logging()

with mlflow.start_run() as run:
```

`psutil` 패키지가 필요하며, GPU 메트릭 수집을 위해서는 추가로 `pynvml` 패키지가 필요하다.

### 4.3 모델 시그니처 & Input Example 적용

**파일**: `src/training/trainers/classification_trainer.py`

현재 `log_model()` 호출 시 시그니처와 input example을 전달하지 않고 있다.

```python
# Before (line 179~184)
mlflow.pytorch.log_model(
    model,
    name="model",
    registered_model_name=config.registered_model_name,
)

# After
import numpy as np
from mlflow.models import infer_signature

sample_input = torch.randn(1, 3, config.image_size, config.image_size)
with torch.no_grad():
    sample_output = model(sample_input.to(device))

signature = infer_signature(
    sample_input.numpy(),
    sample_output.cpu().numpy(),
)

mlflow.pytorch.log_model(
    model,
    name="model",
    signature=signature,
    input_example=sample_input.numpy(),
    registered_model_name=config.registered_model_name,
)
```

### 4.4 모델 별칭 기반 서빙 통합

**파일**: `src/serving/api/dependencies.py`

현재 버전 번호로만 모델을 로딩하고 있어, 배포 시 버전 번호를 직접 지정해야 한다. 별칭을 지원하면 `@champion`으로 항상 최신 검증 모델을 로딩할 수 있다.

```python
# Before (line 88)
model_uri = f"models:/{model_name}/{model_version}"

# After -- 버전 번호와 @alias 형식 모두 지원
if model_version.startswith("@"):
    alias = model_version[1:]
    model_uri = f"models:/{model_name}@{alias}"
else:
    model_uri = f"models:/{model_name}/{model_version}"
```

이를 통해 환경변수에 `MODEL_VERSION=@champion`을 설정하면, 별칭 재할당만으로 서빙 모델을 교체할 수 있다.

### 4.5 Run 태그 적용

**파일**: `src/training/trainers/classification_trainer.py`

학습 컨텍스트 정보를 태그로 남기면 나중에 실험을 검색하고 분류하기 쉬워진다.

```python
# After mlflow.log_params() 아래 추가
mlflow.set_tags({
    "model_type": config.model_name,
    "dataset": config.data_dir,
    "framework": "pytorch",
})
```

---

## 5. 다른 도구와의 연결점

### Prefect (Layer 4: 오케스트레이션)

- Prefect flow의 `on_completion` 훅에서 MLflow run 요약 정보(best accuracy, model version)를 로깅할 수 있다.
- 트랜잭션 rollback 시 MLflow run에 `status: failed` 태그를 업데이트하여 실패한 학습을 추적한다.

### DVC (Layer 2: 데이터 파이프라인)

- MLflow run에 git 커밋 해시가 자동으로 기록된다.
- 해당 커밋의 `.dvc` 파일을 통해 학습에 사용된 데이터 버전을 역추적할 수 있다.
- 데이터 버전과 모델 버전의 연결고리를 형성한다.

### Evidently (Layer 6: 모니터링)

- 드리프트 TestSuite의 pass/fail 결과를 MLflow 메트릭으로 기록한다.
- champion 승격의 게이트 조건으로 활용: 드리프트 검사 통과 시에만 `@champion` 별칭을 재할당한다.

### CleanLab / CleanVision (Layer 2: 데이터 검증)

- 데이터 검증 결과(health_score, label_quality)를 MLflow 메트릭으로 기록한다.
- 데이터 품질과 모델 성능의 상관관계를 추적할 수 있다.

### Serving (Layer 5: 서빙)

- 모델 별칭 기반 무중단 교체 워크플로우:
  1. 새 모델 학습 -> `@challenger` 별칭 부여
  2. 검증 통과 -> `@champion` 별칭 재할당
  3. `/model/reload` 엔드포인트 호출 -> 서빙 서버가 `@champion` 모델 재로딩
- Gunicorn 멀티워커 환경에서는 reload 요청이 단일 워커에만 적용되므로, 컨테이너 재시작 또는 `GUNICORN_WORKERS=1` 설정이 필요하다.
