# 02. 시스템 아키텍처와 인터페이스

> 상태: **계층 경계는 확정 원칙 / 프로토콜·구현 기술은 잠정**

## 1. 설계 목표

'환경이 무엇이냐'와 '누가 어떻게 제어하느냐'를 분리한다. 2D 관계 실험에서 검증한 논리 계약을 3D 통합 환경으로 운반하되, 3D 물리 도입 시 달라지는 상태·제약을 명시적으로 처리한다.

## 2. 논리 계층

```text
[Experiment Runner: seeds, scenarios, hidden ground truth]
       |                         | (private evaluation)
       v                         v
[World Adapters] -> [World State / Simulation Engine] -> [Independent Evaluator]
       ^                    ^          | events/replay
       | observations       |          v
[Agent/Policy Runtime] -> [Action Validator] -> [Event Log / Dataset]
                            |
                       [2D / 3D Viewer]
```

- **World Adapter:** 도메인 모델을 공통 세계 모델에 연결. 1차 도메인은 물류/생산 기능이 있는 소형 작업 세계 후보.
- **Simulation Engine:** 시간·자원·작업 진행·상태 전이의 권위. 헤드리스 지원.
- **Policy/Agent Runtime:** 제어/AI 주체를 등록·호출·교체. 내부 AI는 제한된 관측만 얻는다.
- **Action Validator:** 행동의 문법·권한·선행조건·불변조건을 검사. 거절도 이벤트로 기록.
- **Independent Evaluator:** 숨겨진 사실과 실제 적용 결과를 읽어 실험을 판정. 운영 AI에 평가 정답을 제공하지 않음.
- **Viewer:** 상태/이벤트의 시각화. 렌더링 때문에 핵심 사건이 달라져서는 안 됨(물리 엔진 권위 구간 예외 명시).

## 3. 상태 권위: 2D 논리 모델과 3D 물리 모델

| 영역 | 최초 권위 | 3D 통합 시 원칙 |
|---|---|---|
| 작업 완료/자원 예약 | Python 논리 시뮬레이터(잠정) | 논리 코어 권위 유지 |
| 추상 경로/작업 연결 | 도메인 모델 | 3D 내 경로 가능성·충돌 검증 반영 |
| 연속적인 3D 위치·충돌 반응 | 해당 없음 | **3D 물리 엔진 권위**로 지정한 물체만 물리 엔진이 갱신 |
| 통합 이벤트 시간 | Simulation Clock | 시뮬레이션 시간과 물리 시간의 변환·보간 계약 명시 |

**금지:** 같은 객체의 물리 위치를 Python과 3D 엔진이 각각 별도 적분하여 경쟁시키는 구조.

## 4. 핵심 계약(언어 독립적 개념)

```text
reset(seed, scenario_spec) -> world_version
observe(actor_id, scope) -> Observation(view, timestamp, version)
propose(actor_id, action, expected_version) -> ActionRequest
validate(ActionRequest) -> Accepted | Rejected(reasons)
apply(Accepted) -> [StateEvent...]
step(until_sim_time) -> [StateEvent...]
get_evaluation(run_id) -> EvaluationRecord   # private evaluator only
replay(run_id, event_offset) -> Snapshot + Events
```

- `expected_version`으로 경쟁하는 구조 변경 요청의 오래된 상태 버전을 검출한다.
- `validate`의 결과만으로 미래의 안전이 증명된 것은 아니다. 필요한 경우 전환 시나리오 시뮬레이션도 수행.
- 행동이 거절되면 원인과 당시 스냅샷 버전은 기록하되 세계 상태는 그대로 유지.

## 5. 이벤트 모델 및 재현성

권장 이벤트 공통 필드: `run_id`, `seq`, `sim_time`, `actor_id`, `event_type`, `entity_id`, `world_version`, `payload`, `schema_version`.

기록할 사건: `TaskArrived`, `TaskStarted`, `TaskCompleted`, `ResourceReserved`, `ActionProposed`, `ActionRejected`, `ReconfigurationStarted`, `ReconfigurationCompleted`, `ConstraintViolated`, `FaultInjected`(private partition), `ObservationEmitted`.

**주의:** 에이전트에 공개하는 이벤트 스트림과 평가기 내부 사건 스트림을 분리한다. 결정성은 모델·병렬 처리·물리 엔진·외부 API의 종류에 따라 범위를 기술한다.

## 6. 실행 흐름(예시)

1. 시나리오와 시드로 `reset`; 숨겨진 실제 고장 원인과 관측 노이즈 생성.
2. 환경은 공개된 관측 스키마로 일부 상태만 노출.
3. AI/알고리즘은 허가된 도구와 관측을 기반으로 행동 제안.
4. 검증기가 행동의 적용 가능성과 계약 조건을 검사.
5. 시뮬레이터가 상태 전이를 실행하고 사건 기록.
6. 독립 평가기가 입력/출력·참값과 비교하여 별도 결과 파일 저장.
7. 2D/3D 클라이언트가 실행 로그를 구독하거나 재생.

## 7. 디렉터리 구조

> 상태: **확정(2026-11-11)** — `08-TECHNICAL-STACK.md` §4 구조로 통일. 이전 초안의 단일 `viewer/`는 `viewer-2d/`·`viewer-3d/`로 분리하고 `src/physics/`를 추가했다.
> Python 패키지는 표준 라이브러리 `io` 와의 이름 충돌을 피하려고 `src/asel/` 아래에 둔다 (`src/asel/core`, `src/asel/io` …). 근거: `docs/decisions/0002-python-package-layout.md`.

```text
src/core/        # world state, clock, events, validators, invariants
src/domains/     # warehouse_like adapter, later production adapter
src/policies/    # fixed, central, modular, cost-aware candidates
src/agents/      # model adapters, tool boundaries, orchestrator
src/physics/     # PhysicsAdapter, units, stepping, result mapping
src/evaluation/  # private scoring and diagnostics
src/io/          # scenario/config/event schemas, snapshots, replay
experiments/     # versioned configs; measurements; reproducible scripts
viewer-2d/       # small relationship/spatial viewer
viewer-3d/       # render/interaction adapter, engine TBD
tests/           # invariant/property/integration/replay tests
```

폴더는 필요해지는 시점에 만든다. 빈 폴더를 미리 만들지 않는다.

## 8. 가장 먼저 검증할 위험

- 시간 스케일 및 이벤트 순서 오류.
- 권한/정답 누출.
- 구조 변경 중 두 정책의 충돌과 중복 자원 예약.
- 동일 객체의 상태에 대해 서로 다른 엔진이 권위를 주장하는 문제.
- 도메인 전환 시 코어에 조건문이 누적되는 문제.

관련: 세계 모델 `03`, AI `04`, 시뮬레이션 `05`, 실험 `07`.
