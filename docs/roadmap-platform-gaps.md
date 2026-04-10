# Platform Gap Analysis & 구현 로드맵

> **작성일**: 2026-04-10
> **최종 업데이트**: 2026-04-10 (Phase E-1 완료)
> **목적**: 업계 표준 MLOps 플랫폼(ZenML, ClearML, MLRun, Lightly.ai, Google MLOps Level 2) 대비 data-flywheel 플랫폼의 격차를 식별하고, 다중 세션에 걸친 구현 로드맵을 제시한다.

---

## 1. 현재 상태 요약

data-flywheel은 Active Learning-First Closed-Loop MLOps 플랫폼으로, 4개 Phase(A~D)를 거쳐 핵심 구조가 구현되었다:

- **Phase A**: Active Learning Core (uncertainty estimation, confidence routing, pseudo-label accumulation, Label Studio bridge)
- **Phase B**: Continuous Training Loop (event-driven retrain, champion gate, data integration)
- **Phase C**: CI/CD & Deployment (GitHub Actions, CML, canary deploy, rollback)
- **Phase D**: Architecture Refactoring (core/plugins 분리, Protocol interfaces)

**12개 Docker 서비스**: PostgreSQL, MinIO, MLflow, Prefect Server, Redis, API, API-Canary, Nginx, Prometheus, Pushgateway, Grafana, Label Studio

**6개 Prefect Flow**: training, continuous-training, monitoring, active-learning, data-accumulation, deployment

---

## 2. 업계 벤치마킹 비교

### 비교 대상

| 플랫폼 | 특징 |
|--------|------|
| **ZenML** | Pipeline-as-code, artifact lineage 자동 추적, 모듈식 orchestrator/deployer 교체 |
| **ClearML** | End-to-end MLOps suite, experiment tracking, data versioning, pipeline orchestration 통합 |
| **MLRun** | Iguazio 기반, Kubernetes-native, real-time serving graph, feature store 내장 |
| **Lightly.ai** | Active Learning 전문, embedding 기반 diversity selection, coreset/typicality selection |
| **Google MLOps Level 2** | CI/CD pipeline 완전 자동화, event-driven retrain, 품질 검증 자동화 |

### 기능별 비교표

| 기능 | data-flywheel | ZenML | ClearML | Lightly.ai | MLRun | Google L2 |
|------|:---:|:---:|:---:|:---:|:---:|:---:|
| Closed-Loop Retrain | ✅ | ⚠️ Partial | ✅ | ✅ | ✅ | ✅ |
| Event-Driven Triggers | ⚠️ **Partial** (E-1 완료, E-2 대기) | ✅ | ✅ | N/A | ✅ | ✅ |
| Canary Deploy | ⚠️ Partial | ✅ (Seldon) | N/A | N/A | ✅ (Nuclio) | ✅ |
| Shadow Deploy | ❌ | ✅ (Seldon) | N/A | N/A | ✅ | ✅ |
| A/B Testing | ❌ | ✅ (Seldon) | N/A | N/A | ✅ | ✅ |
| Active Learning | ✅ | ⚠️ Plugin | ⚠️ Plugin | ✅ **Core** | N/A | N/A |
| Embedding Diversity | ❌ | N/A | N/A | ✅ **Core** | N/A | N/A |
| Drift Detection | ✅ | ✅ (Evidently) | ✅ | N/A | ✅ | ✅ |
| Feature Store | ❌ | ✅ (Feast) | ⚠️ | N/A | ✅ **Core** | ✅ (Vertex) |
| Data Lineage | ⚠️ Partial | ✅ **Core** | ✅ | N/A | ✅ | ✅ |
| Alerting/Notification | ❌ | ✅ (Notifier) | ✅ | N/A | ✅ | ✅ |
| Multi-Model Serving | ❌ | ✅ | ✅ | N/A | ✅ | ✅ |
| Plugin/Domain Agnostic | ✅ Protocol | ⚠️ | ❌ | ❌ CV-only | ⚠️ | ✅ |

**범례**: ✅ 완전 구현 | ⚠️ 부분 구현 | ❌ 미구현 | N/A 해당 없음

---

## 3. Gap 상세 분석

### Gap 1: Event-Driven Automation 부재 (Critical → Partial) 🟠

**원래 현상**: Core Philosophy #3 "Event-Driven Automation"을 명시하지만, 실제 event-driven 트리거가 부재.

**진행 상황**: **Phase E-1 완료** (PR #26, commit `ab3d14a`).

- [x] `docker-compose.yml`에 `prefect-worker` 서비스 추가 (원래부터 존재하되 CT 단일 deployment만 서브) → 통합 `serve_all` 엔트리포인트로 전환
- [x] Flow deployment 자동 등록 startup script 작성 (`src/core/orchestration/flows/serve_all.py`, 단일 `prefect.serve(...)` 호출)
- [x] **CT, AL, monitoring, data-accumulation 4개 flow 모두 RunnerDeployment로 등록**
  - `continuous-training-deployment` (event-driven)
  - `active-learning-deployment` (event-driven)
  - `monitoring-deployment` (cron `0 3 * * *`, daily)
  - `data-accumulation-deployment` (cron `0 */6 * * *`)
- [x] **Latent broken link 해소 확인**: `monitoring_flow._trigger_active_learning_pipeline()`이 호출하던 `run_deployment("active-learning-pipeline/active-learning-deployment")`가 실제로 worker에 도달 — 런타임 검증에서 `fetch-uncertain-predictions` + `select-samples-for-labeling`이 `Completed()` 상태로 실행됨 (이전에는 silent no-op).
- [ ] Label Studio webhook → Prefect deployment 트리거 E2E 검증 (E-2)
- [ ] Drift 감지 → CT deployment 자동 트리거 E2E 검증 (E-2)
- [x] **S5 수정 완료**: `active_learning_flow`에 `trigger_source: str = "manual"` 인자 추가 (CT flow와 대칭). `monitoring_flow._trigger_active_learning_pipeline()`의 `run_deployment(..., parameters={"trigger_source": "g5_medium_drift"})` 호출이 이제 정상 수락되며, summary dict와 markdown artifact에도 trigger source가 노출되어 Prefect UI에서 "왜 이 AL run이 생성되었는지" 추적 가능. 회귀 테스트 2건 추가 (`test_flow_accepts_trigger_source_and_propagates_to_summary`, `test_flow_trigger_source_defaults_to_manual_on_empty_path`).

**남은 작업량**: 1 세션 (E-2 webhook/drift E2E 검증만 남음)

---

### Gap 2: Canary Deployment Docker exec 의존 (High) 🟠

**현상**: `deployment_tasks.py`의 canary 로직이 `subprocess`로 `docker compose` CLI를 호출. Nginx upstream 갱신도 `docker exec`로 sed 명령 실행.

- Docker-in-Docker 없이 호스트 Docker 소켓 필요 (보안 위험)
- Nginx reload가 atomic하지 않음 (중간 상태에서 요청 실패 가능)
- 테스트 환경에서 재현이 어려움

**업계 기준**: ZenML은 Seldon/KServe 기반 canary를, MLRun은 Nuclio serving graph를 사용하여 컨테이너 오케스트레이터 레벨에서 canary를 수행.

**필요 조치**:
- [ ] Nginx upstream 관리를 template + signal 방식으로 변경
- [ ] Canary 컨테이너 관리를 Docker SDK for Python 또는 compose profile로 변경
- [ ] G4 canary gate에 실제 traffic 비교 로직 E2E 검증
- [ ] Canary rollback 자동화 테스트 추가

**예상 작업량**: 2 세션

---

### Gap 3: A/B Testing & Shadow Deployment 미구현 (Medium) 🟡

**현상**: Canary deployment만 존재. A/B testing (user segment 기반 traffic split)과 shadow deployment (champion 결과만 반환, challenger는 로깅만) 미구현.

**업계 기준**: Google L2, ZenML(Seldon), MLRun 모두 shadow mode와 A/B testing 지원. Shadow deploy는 새 모델의 실전 성능을 위험 없이 평가하는 핵심 기법.

**필요 조치**:
- [ ] Shadow mode: predict 시 champion + challenger 모두 실행, champion 결과만 반환
- [ ] Shadow prediction 결과를 별도 S3 키에 로깅
- [ ] A/B test: Nginx header-based routing (`X-Experiment-Group`)
- [ ] Shadow/A/B 결과 비교 Grafana dashboard panel 추가
- [ ] Shadow deploy E2E 테스트

**예상 작업량**: 2~3 세션

---

### Gap 4: Embedding 기반 Diversity Selection 미구현 (Medium) 🟡

**현상**: `UncertaintyDiversitySelector`가 uncertainty score (1D float)의 거리만으로 diversity 계산. 실제 production active learning은 embedding space에서의 diversity가 필수.

**업계 기준**: Lightly.ai는 self-supervised learning embedding + coreset selection(k-center greedy)을 핵심으로 제공. Typicality-based selection으로 대표성/비정형 데이터 구분. Embedding 기반 diversity로 1,000개 선별 이미지가 recall +32%, F1 +10% 향상 사례.

**필요 조치**:
- [ ] 모델 penultimate layer에서 embedding 추출 기능 (CV plugin)
- [ ] Embedding storage: 예측 시 embedding을 S3/Redis에 캐싱
- [ ] Coreset selection (k-center greedy) in embedding space
- [ ] BADGE sampling (Bayesian Active Learning by Disagreement in Gradient Embedding) 추가
- [ ] Typicality-based selection 옵션 추가
- [ ] Embedding diversity selector를 Plugin protocol로 추상화

**예상 작업량**: 3~4 세션

---

### Gap 5: Feature Store 부재 (Medium) 🟡

**현상**: Prediction 시 feature engineering이 단순 image transform만. 메타데이터를 체계적으로 관리하는 feature store가 없음. Reference data와 current data 비교가 하드코딩된 column 이름에 의존.

**업계 기준**: MLRun은 feature store 내장, ZenML은 Feast 통합, Google Vertex AI는 Vertex Feature Store 제공. Feature store는 training-serving skew 방지와 feature 재사용의 핵심.

**필요 조치**:
- [ ] Feast 또는 Redis 기반 lightweight feature store 도입 검토
- [ ] Prediction log schema 표준화 (Pydantic model)
- [ ] Feature versioning과 training-serving consistency 보장
- [ ] Drift detection에서 feature store 참조로 전환

**예상 작업량**: 2~3 세션

---

### Gap 6: Data Lineage & Reproducibility 불완전 (Medium) 🟡

**현상**: DVC로 데이터 버전 관리하고 MLflow에 hash를 tag하지만:
- 어떤 prediction log들이 training data로 merge되었는지 추적 불가
- Pseudo-label vs human-label 비율이 MLflow run에 미기록
- 특정 모델이 어떤 AL round의 데이터로 학습되었는지 역추적 번거로움

**업계 기준**: ZenML은 모든 artifact에 자동 lineage 추적이 핵심 기능. ClearML도 data versioning + experiment lineage 통합 제공.

**필요 조치**:
- [ ] MLflow run에 data lineage metadata 체계적 기록
  - source_counts: {pseudo_label: N, human_label: M, original: K}
  - al_round: int
  - data_hash: str
  - merged_from: list[str] (S3 keys)
- [ ] Prefect artifact에 lineage chain 기록
- [ ] Lineage 조회 API 또는 CLI 추가
- [ ] Lineage visualization (Grafana 또는 별도 UI)

**예상 작업량**: 2 세션

---

### Gap 7: 알림(Alerting) 시스템 미구현 (Medium) 🟡

**현상**: Grafana alerting 설정 파일이 있지만, 실제 notification channel이 미설정. Quality gate 실패 시 로깅만 수행.

**업계 기준**: 모든 production MLOps 플랫폼이 alerting을 필수로 제공. ClearML은 내장 알림, ZenML은 Notifier step 제공.

**필요 조치**:
- [ ] Grafana alert rules → Slack webhook notification channel 설정
- [ ] Quality gate failure → Prefect notification block 연동
- [ ] G5 HIGH severity → PagerDuty-style escalation
- [ ] Alert rule 템플릿화 (configs/ 에 provisioning)
- [ ] Alert firing E2E 테스트

**예상 작업량**: 1~2 세션

---

### Gap 8: Multi-Model Serving (Low) 🟢

**현상**: `registered_model_name` 하나만 관리. 여러 모델 동시 서빙이나 모델 간 dependency 관리 미지원.

**필요 조치**:
- [ ] Multi-model serving endpoint (path-based: `/predict/{model_name}`)
- [ ] Model dependency graph 정의
- [ ] Per-model quality gate 설정
- [ ] Model ensemble 옵션

**예상 작업량**: 2~3 세션

---

### Gap 9: Rate Limiting & Authentication (Low) 🟢

**현상**: Predict endpoint 인증 없이 공개. Admin endpoint만 API key 보호.

**필요 조치**:
- [ ] Nginx level rate limiting (`limit_req_zone`)
- [ ] API key 또는 JWT authentication for predict endpoint
- [ ] Per-client rate limiting 및 usage tracking
- [ ] API usage metrics → Prometheus

**예상 작업량**: 1 세션

---

### Gap 10: Plugin Dynamic Loading 미완성 (Low) 🟢

**현상**: `plugins/loader.py`가 환경 변수 기반이지만, `app.py`에서 `SoftmaxEntropyEstimator` 직접 import.

**필요 조치**:
- [ ] Protocol 기반 dynamic loading 완성
- [ ] Plugin registry pattern (entry_points 또는 config-based)
- [ ] 설정만으로 CV/NLP/Tabular 전환 가능하게
- [ ] Plugin 설치/활성화 CLI

**예상 작업량**: 1~2 세션

---

## 4. 구현 로드맵

### Phase E: Event-Driven & Operational Hardening (우선순위 1)

| 순서 | 작업 | Gap | 예상 세션 | 상태 |
|:---:|------|:---:|:---:|:---:|
| E-1 | Prefect Worker 통합 serve_all & 4개 Deployment 등록 | Gap 1 | 1 | ✅ **완료** (PR #26, `ab3d14a`) |
| E-2 | Event-Driven Trigger E2E 검증 (webhook → CT, drift → CT/AL) + S5 수정 | Gap 1 | 1~2 | ⏳ 대기 |
| E-3 | Alerting 시스템 구축 (Grafana + Prefect notifications) | Gap 7 | 1~2 | ⏳ 대기 |
| E-4 | Rate Limiting & API Authentication | Gap 9 | 1 | ⏳ 대기 |

**완료 기준**: `docker compose up` 후 Label Studio annotation 완료 → 자동 CT 트리거 → 모델 갱신까지 수동 개입 없이 동작. Alert 발생 시 Slack 알림.

#### E-1 완료 요약 (2026-04-10)

- **커밋**: `ab3d14a feat(orchestration): unify prefect worker to serve all four core flows (#26)`
- **변경 파일**: 7 files (+371 / −115)
  - 신규: `src/core/orchestration/flows/serve_all.py`, `tests/unit/test_orchestration_serve_all.py`
  - 수정: `docker/orchestration/Dockerfile` (image 0.2.0, pandas/evidently/scikit-learn 추가, ENTRYPOINT 교체), `docker-compose.yml` (prefect-worker env/depends_on 확장), `src/core/monitoring/metrics.py`+`src/core/serving/gunicorn/config.py` (pre-existing lint fix 동반)
  - 삭제: `src/core/orchestration/flows/continuous_training_serve.py` (단일 CT serve 엔트리포인트, 통합본으로 대체)
- **검증**:
  - Unit: 316/316 pass (신규 5개 serve_all 테스트 포함)
  - Runtime: Prefect API에 4개 deployment 정확한 이름/크론으로 등록, AL deployment 트리거 → worker가 flow run pick up → `fetch-uncertain-predictions` + `select-samples-for-labeling` `Completed()` 도달
  - CI: Lint (Ruff) ✓, Unit Tests ✓

### Phase F: Advanced Active Learning (우선순위 2)

| 순서 | 작업 | Gap | 예상 세션 |
|:---:|------|:---:|:---:|
| F-1 | Embedding 추출 (CV plugin, penultimate layer) | Gap 4 | 1 |
| F-2 | Embedding Storage (S3/Redis caching) | Gap 4 | 1 |
| F-3 | Coreset Selection (k-center greedy) | Gap 4 | 1~2 |
| F-4 | BADGE / Typicality-based Selection | Gap 4 | 1 |

**완료 기준**: Active Learning pipeline이 embedding space에서 diversity-aware sample selection 수행. Selection quality metric 개선 검증.

### Phase G: Deployment Sophistication (우선순위 3)

| 순서 | 작업 | Gap | 예상 세션 |
|:---:|------|:---:|:---:|
| G-1 | Canary Deploy 리팩터링 (Docker SDK / compose profile) | Gap 2 | 1 |
| G-2 | Nginx Template + Signal 기반 upstream 관리 | Gap 2 | 1 |
| G-3 | Shadow Deployment 구현 | Gap 3 | 1~2 |
| G-4 | A/B Testing (header-based routing) | Gap 3 | 1 |

**완료 기준**: Canary, shadow, A/B 세 가지 deployment strategy가 설정으로 전환 가능. 각 전략의 E2E 테스트 통과.

### Phase H: Data & Feature Management (우선순위 4)

| 순서 | 작업 | Gap | 예상 세션 |
|:---:|------|:---:|:---:|
| H-1 | Data Lineage 체계화 (MLflow metadata + Prefect artifact) | Gap 6 | 1~2 |
| H-2 | Feature Store 도입 (Feast or Redis) | Gap 5 | 2~3 |
| H-3 | Multi-Model Serving | Gap 8 | 2~3 |
| H-4 | Plugin Dynamic Loading 완성 | Gap 10 | 1~2 |

**완료 기준**: 모든 모델에 대해 training data → model → prediction 역추적 가능. Feature store에서 training/serving 동일 feature 보장.

---

## 5. 우선순위 결정 기준

1. **Core Philosophy 충족도**: Gap 1(Event-Driven)은 5대 원칙 중 하나를 직접 위반하므로 최우선
2. **운영 안정성**: Gap 7(Alerting)은 production 운영의 기본 — 문제 발생 시 인지 불가
3. **차별화 가치**: Gap 4(Embedding Diversity)는 Lightly.ai 수준의 AL 품질 달성에 필수
4. **리스크 감소**: Gap 2(Canary)는 보안 위험(Docker 소켓 노출)과 배포 안정성 직결
5. **장기 확장성**: Gap 5, 8, 10은 플랫폼 성장에 따라 점진적 도입

---

## 6. 참고 자료

- [Google MLOps Level 0-2 Architecture](https://docs.google.com/architecture/mlops-continuous-delivery-and-automation-pipelines-in-machine-learning)
- [Google Practitioners Guide to MLOps](https://services.google.com/fh/files/misc/practitioners_guide_to_mlops_whitepaper.pdf)
- [ZenML vs ClearML vs MLflow Comparison](https://www.zenml.io/blog/clearml-vs-mlflow)
- [Lightly.ai Active Learning Guide](https://www.lightly.ai/blog/active-learning-in-machine-learning)
- [MLRun vs MLflow vs ZenML Comparison](https://www.zenml.io/blog/mlrun-vs-mlflow)
- [Self-Supervised Learning with Lightly AI for Data Curation](https://www.marktechpost.com/2025/10/11/a-coding-guide-to-master-self-supervised-learning-with-lightly-ai-for-efficient-data-curation-and-active-learning/)
