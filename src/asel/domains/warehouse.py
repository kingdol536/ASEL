"""환경 A (물류): 범용 작업 흐름 어댑터(job_flow)의 별칭 (#35).

물류 전용 코드는 더 이상 없다. 환경 A 는 시나리오 파일(개체·역할 라벨·공정 사슬)만으로 표현된다.
예전 import 경로를 쓰는 코드·테스트를 위해 이름만 다시 내보낸다.
"""

from __future__ import annotations

from asel.domains.job_flow import JobFlowWorkload, world_init_payload

WarehouseWorkload = JobFlowWorkload

__all__ = ["WarehouseWorkload", "world_init_payload"]
