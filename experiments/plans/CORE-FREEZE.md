# 코어·공통 언어 동결 기록 (이식성 실험 기준점)

- 동결 커밋: **`e93573918a74c4ff1642787dde5ba1c8e592b7f7`** (GitHub 푸시, 커밋 시각 2026-11-11T06:43:13Z)
- 범위: `src/asel/core/`, `src/asel/vocabulary.py`(공통 언어 v0), 정책·평가·입출력 공용 엔진
- 관련: 티켓 #35, 측정 방법 [PORTABILITY-METRICS.md](PORTABILITY-METRICS.md)

## 규칙

- 환경 B(조립 라인, #37)·환경 C(미공개, #41) 이식의 변경량은 **이 커밋을 기준**으로 `portability_metrics.py` 로 잰다.
- 환경 C 는 이 커밋 이후에 설계를 시작한다. C 의 설계 시작 커밋 시각을 이 문서와 보고서에 적는다.
- 환경 B 는 공통 언어 v0 작성·코어 정리 단계에서 존재가 알려져 있었다 → '설계 참고 환경'으로 따로 보고한다.

## 동결 시점 상태

- 공통 언어 v0: 개념 7, 값 개념 1(capability), 관계 15, 행동 7, 사건 13 (`docs/11-COMMON-LANGUAGE.md`)
- 도메인 어댑터: `job_flow` 하나 (환경 A 물류 = 별칭 `warehouse_like`, 물류 전용 코드 0줄)
- 재현성: EXP-001 270/270 사건 로그 바이트 동일, EXP-002 810회 평가표 동일
