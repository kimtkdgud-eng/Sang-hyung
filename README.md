# Electrolyte AI Platform (구조 프로토타입)

여기서는 **구조와 로직만** 만들고, 실제 데이터 연결은 사내 환경에서 한다.

## 보안·이전 원칙
- 외부 패키지·네트워크 호출 없음 (Python 3 표준 라이브러리 + SQLite). 폴더째 사내로 옮겨 실행 가능.
- 저장소에는 가상 데이터(`synthetic.py`)만 있다. 사내 데이터·열 이름·수치를 커밋하지 않는다 (`*.sqlite`, `*.csv`, `*.xlsx`는 .gitignore).
- 현황표 조회는 읽기 전용. 원본값은 변형하지 않고 누락은 NULL로 둔다.

## 구성
| 파일 | 역할 |
|---|---|
| `electrolyte_platform/schema.py` | 공통 데이터 모델: 물질 → 조성 버전 → 제조 배치 → 실측 물성·셀 평가 |
| `electrolyte_platform/coverage.py` | 지표·조건별 데이터 연결 현황표 + 첫 검증 추천 |
| `electrolyte_platform/synthetic.py` | 결함(누락·중복·단위/온도 불일치)을 일부러 넣은 가상 데이터 |
| `tests/` | 집계 규칙 시험 |

## 실행
```
python -m electrolyte_platform coverage          # 가상 데이터로 현황표 출력
python -m electrolyte_platform coverage --db x.sqlite   # 사내 DB(같은 스키마)
python -m unittest discover -s tests
```

## 사내 적용 시 바꿀 곳 (coverage.py 상단 `Config`)
- `STANDARD`: 물성별 기준 단위·측정 온도
- `required_props`: 비교에 필수인 물성 (현재 3종 모두 필수 → 가장 엄격한 기준)
- `min_compositions`: 검증 분할 가능 최소 고유 조성 수 (현재 20, 임시값)
- `importance`: 지표별 연구 중요도 (미입력 시 모두 1.0)
- 사내 테이블이 이 스키마와 다르면 Adapter(뷰 또는 변환 함수)로 `schema.py` 형태에 맞춘다.
