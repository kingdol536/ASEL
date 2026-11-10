# 03. 가상 세계 공통 모델

> 상태: **최소 공통 추상화는 잠정 / 도메인별 확장은 실험 검증 필요**

## 1. 원칙

공장/물류/IT를 같은 자산이라고 취급하지 않는다. 공통적으로 표현 가능한 **상태·기능·관계·제약·행동의 계약**을 만들고, 도메인별 의미와 물리는 어댑터가 제공한다.

## 2. 세계의 기본 구성

| 개념 | 필수 속성의 예 | 의미 |
|---|---|---|
| `Entity` | id, type, capabilities, properties | 설비·로봇·서비스·작업 셀 |
| `Relation` | source, target, kind, cost?, capacity? | 물질·정보·자원·제어 연결 |
| `Task` | id, inputs, predecessors, requirements, status | 실행·대기·완료할 일 |
| `Resource` | id, capacity, availability | 장비·작업자·컴퓨팅 용량 |
| `Constraint` | id, predicate, severity, scope | 금지/허용 조건, 보호할 불변조건 |
| `Objective` | id, target, priority?, horizon? | 달성하고자 하는 목표; 우선순위는 미결정 |
| `Action` | actor, target, kind, parameters | 허용된 상태 전이·구조 변경 요청 |
| `Observation` | actor, visible_state, timestamp, uncertainty | 특정 주체에게 공개한 상태의 부분집합 |
| `WorldState` | version, time, entities, relations, tasks | 시뮬레이션의 현재 상태 |

## 3. 그래프 표현

- 시스템 구조: `G_t=(V_t, E_t, A_t)` (`A_t`는 노드·간선 속성).
- 그래프가 바뀌는 `ReconfigureEdge`, `ChangeCapability`, `MoveAsset` 등의 행동은 일반 작업 처리와 분리한다.
- 공간은 처음부터 명시적인 선택 영역으로 둔다: `geometry=None | 2D | 3D`. **2D 좌표를 단순히 z=0으로 확장했다고 3D 물리 모델이 되는 것은 아님**.

## 4. 작업·자원 생명주기

`CREATED → WAITING → READY → RUNNING → COMPLETED`, 예외적으로 `BLOCKED / FAILED / CANCELLED`.

- 완료되지 않은 작업을 완료 상태로 전환하지 않는다.
- 자원 예약은 하나의 원자적 상태 전이로 처리한다.
- 작업 의존성을 위반한 시작을 거부한다.
- 수요·작업 완료·구조 변경을 별도 사건으로 기록한다.

## 5. 시나리오의 최소 스키마(초안)

```yaml
schema_version: '0.1-draft'
scenario_id: warehouse-small-a
seed: 42
sim_time_limit: 3600
entities:
  - id: cell-pick-1
    type: workstation
    capabilities: [pick]
    capacity: 1
  - id: cell-pack-1
    type: workstation
    capabilities: [pack]
    capacity: 1
relations:
  - {source: cell-pick-1, target: cell-pack-1, kind: material_flow}
workload:
  arrival_process: {type: poisson, rate_per_min: 0.8}
constraints:
  - {id: nonnegative-capacity, kind: invariant}
objectives:
  - {id: meet-order-deadline, kind: provisional}
```

**주의:** 이것은 계약을 논의하기 위한 예시이며 구현 완료된 schema나 최종 성능 설정이 아니다.

## 6. 두 가지 환경의 관계

- **환경 A(초기 잠정):** 모듈형 물류/작업 셀, 이동/대기/작업자원 경합.
- **환경 B(이식성 검증 후보):** 공정 선후관계가 더 강하고 전환 비용이 다른 생산 공정.
- B에서 코어 수정 없이 **어댑터·설정·제약 모델 교체로** 작동하는지 관측. 실패 시 수정이 필요했던 지점을 정확히 기록. 12주 내 범위가 과도하면 B는 제한된 구조 변형 테스트로 축소 가능.

## 7. 모델의 계약과 유효 범위

각 모델은 다음을 선언할 수 있게 한다.

```text
model_id, version, domain_scope, required_inputs,
produced_outputs, units, valid_range, update_interval,
assumptions, fidelity_level, estimated_compute_cost,
validation_tests, dependencies
```

장기 연구에서 '어느 모델의 가정이 깨졌는가'를 찾기 위한 기반이다. 12주에는 일부 핵심 속성만 구현한다.

## 8. 검증 가능한 불변조건 예

- `available_capacity >= 0` 및 `reserved <= total_capacity`.
- `TaskCompleted` 이전 필수 선행 작업 완료.
- 금지 연결을 통한 흐름 없음.
- 3D에 물리적으로 배치된 자산은 선택한 충돌·점유 정책을 준수.
- 운영 에이전트에게 비공개 상태 필드 미전달.
- 하나의 재구성 요청이 부분 적용되고 성공으로 보고되지 않음(롤백 또는 명시적 실패 상태).

## 9. 후속 고도화

- 타입별 단위·차원 검사, 공간 계층, 다중 스케일 그래프, 이벤트 소싱, 상태 추정, 모델 간 인과 의존 관계.
- 물리 모델 결합 시 포트의 의미·단위·시간 스케일을 검사하는 레지스트리.
