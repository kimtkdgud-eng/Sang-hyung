# Electrolyte AI Platform (구조 프로토타입)

여기서는 **구조와 로직만** 만들고, 실제 데이터 연결은 사내 환경에서 한다.

## 보안·이전 원칙
- 네트워크 호출 없음. 현황표는 표준 라이브러리 + SQLite 만 쓴다. 물성 비교(`addvalue`)만 scikit-learn·numpy 가 필요하다(v2.12 본체도 사용).
- 저장소에는 가상 데이터만 있다. 사내 데이터·열 이름·수치를 커밋하지 않는다 (`*.sqlite`, `*.csv`, `*.xlsx` 는 .gitignore).
- Adapter 는 **단일 SELECT 문만** 허용하고 `PRAGMA query_only=ON` 으로 연결해 원본을 바꾸지 못한다. 누락은 NULL 로 두고 0으로 채우지 않는다.

## 구성
| 파일 | 역할 |
|---|---|
| `adapters.py` | 읽기 전용 Adapter. 사내 테이블은 `DEFAULT_SQL` 의 SELECT 4개(results/batches/properties/components)만 바꿔 연결 |
| `coverage.py` | 지표 x 동일 평가 조건별 데이터 연결 현황표 + 첫 검증 추천 |
| `gate.py` | 평가 조건 일치 게이트. 조건이 섞이면 분석 차단 |
| `composition.py` | 조성 표기 규칙(염 mol/L · 용매 vol% · 첨가제 wt%)과 검증. 합계 100 닫힘은 **용매 vol%에만** 적용, 단위는 자동 환산하지 않음 |
| `hub_contract.py` | 공통 DB 허브 계약 점검: 물질 ID·조성 버전·배치·평가 조건·출처·QC 상태. 열이 없으면 통과가 아니라 '확인 불가' |
| `doe_constraints.py` | DOE 후보 제약 검토(Pareto 앞단). 통과 후보도 `pending_researcher_approval` 로만 표시 |
| `addvalue.py` | 조성 단독 vs 조성+실측 물성 비교 (조성 그룹 분할, 사전 기준, 결과 기록) |
| `demo_schema.py`, `synthetic.py` | 데모 스키마와 가상 데이터. v2.12 의 `internal_recipes/_components/_results` 는 소스 사용 흔적에서 복원, `batches`·`batch_properties`·`internal_results.batch_id` 는 사내 11/09 변경의 **자리표시자** |
| `docs/PROPOSAL_protocol_gate_for_feature_hub.md` | 본체 학습 데이터에 조건 게이트를 넣는 제안 |

## 실행
```
python -m electrolyte_platform coverage
python -m electrolyte_platform addvalue --metric "초기 DCIR" --unit mohm --min-improvement 0.5   # 사전 기준 필수
python -m electrolyte_platform addvalue ... --signal property   # 가상 데이터: 물성 효과를 심은 경우
python -m electrolyte_platform hub --rules configs/composition_rules.example.json     # 허브 계약 점검
python -m electrolyte_platform screen --candidates 후보.json --rules 규칙.json            # DOE 후보 제약 검토
python -m electrolyte_platform coverage --db x.sqlite           # 사내 DB
pytest -q tests
```
조건이 여러 가지 섞인 지표는 `addvalue`가 차단한다. `coverage` 표의 해당 지표 조건 순번을 `--condition-index N` 으로 지정한다.

## 사내 적용 시 바꿀 곳
- `adapters.DEFAULT_SQL`: 사내 테이블·열에 맞춘 SELECT 4개 (열 별칭은 위 표의 이름으로).
- `configs/composition_rules.example.json`: **예시 값**이다. 허용 범위·허용 목록·비호환 쌍·첨가제 합계 상한·첨가제 기준(`total_electrolyte` 가정)을 회사 기준으로 교체.
- `adapters.DEFAULT_SQL` 의 선택 항목 `versions`(조성 버전), `qc`(QC 상태): 사내 테이블이 있으면 추가, 없으면 계약 점검에서 '확인 불가'.
- `coverage.Config`: 물성 기준 단위·온도, 필수 물성, 최소 고유 조성 수(임시값 20), 지표별 중요도.
- `addvalue.Plan`: **결과를 보기 전에** 정할 MAE 개선 기준(`min_improvement`)과 일관성 비율(기본 80%).

## 해석 주의
- `addvalue` 결과는 물성이 실측된 배치에서의 비교다. 아직 제조하지 않은 후보에 같은 개선이 적용된다고 해석하지 않는다.
- 가상 데이터 결과는 구조 확인용이다 (효과 없음 → "선택 기능 유지", 효과 있음 → "후보 채택"이 나오는지만 시험).
