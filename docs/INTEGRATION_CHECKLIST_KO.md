# 사내 연결 점검 순서

목적: 이 저장소의 엔진을 **사내 DB를 건드리지 않고** 사내 데이터에 처음 연결하고, 결과가 믿을 만한지 단계별로 확인한다.
원칙: 읽기 전용 · 값은 고치지 않는다 · 사내 이름·수치를 이 저장소에 되돌려 커밋하지 않는다 · 실행 결과(표)도 사내 자료로 취급한다.

## 0. 시작 전 결정 (사람이 정한다)
아래는 이 프로토타입이 **가정한 값**이다. 틀리면 결과가 틀리므로 먼저 확정한다.

| # | 확인할 것 | 현재 가정 | 바꾸는 곳 |
|---|---|---|---|
| 1 | real 과 RPT 의 정의 | real = 사이클 중 실측, RPT = 주기적 기준 조건 측정 | `configs/metric_registry` |
| 2 | `temperature_C` 의 의미 | 사이클/저장 온도. RPT 측정 온도는 `rpt_temp_c` 같은 조건 키 | 지표 사전 필수 조건 |
| 3 | 저항 지표의 형태 | 초기 대비 증가율(%) — 절대값(mΩ)·DCIR/ACIR 이면 서로 비교 불가 | 지표 사전(지표 이름을 분리) |
| 4 | 첨가제 wt% 의 기준 | 전체 전해액 기준(`total_electrolyte`) | `composition_rules.basis_by_class` |
| 5 | 염 mol/L 의 기준 | 단위만 확인, 기준(용매/용액 부피) 미검사 | 사내 정의 확인 후 규칙 추가 필요 |
| 6 | 읽는 시점(수명 사이클 수, 저장 시간) | 시점이 다르면 별도 행 | 표가 너무 잘게 쪼개지면 시점 묶음 기준 결정 |
| 7 | 물성 비교 기준(단위·측정 온도) | 전도도 mS/cm · 점도 mPa.s · 밀도 g/cm3, 모두 25 °C | `coverage.Config.standard` |
| 8 | 조성 허용 범위·허용 물질·비호환 쌍 | 예시 값 | `composition_rules` |
| 9 | 조성 버전·QC 상태가 어디에 있는지 | 없음(→ '확인 불가') | `versions`, `qc` SELECT |
| 10 | 사내 DB 종류 | SQLite 가정(본체 v2.12 가 SQLite) | 아래 1단계 |

## 1. 환경 (10분)
1. 저장소 폴더를 사내로 복사한다. Python 3.10+ 와 `numpy`·`scikit-learn`(`addvalue`·`doe` 용)이 있는지 확인한다. 현황표·허브 점검은 표준 라이브러리만 쓴다.
2. 사내에서 합성 데이터 시험이 통과하는지 먼저 본다: `python -m pytest -q tests` (사내에 pytest 가 없으면 `python -m unittest discover -s tests`; sklearn 이 없으면 해당 시험은 건너뛴다).
3. **읽기 전용 경로를 확보한다.** SQLite 파일은 `--db` 가 읽기 전용(`mode=ro`)으로 연다. SQLite 가 아닌 DB 라면 이 보호가 없으므로 **읽기 전용 계정이나 읽기 전용 뷰**로만 연결하고, 연결 코드는 사내 Claude 가 `SqlAdapter(con, sql)` 에 DB-API 연결(행을 이름으로 접근 가능한)을 넘기도록 만든다.
4. 원본 DB 를 직접 쓰기 전에 파일 복사본 또는 스냅샷으로 먼저 시도한다.

## 2. SELECT 작성 — `configs/adapter_sql.template.json` 복사본을 사내에서 편집
열 별칭(AS)은 아래 이름이어야 한다. 단일 SELECT 만 허용되며 `;` 로 문장을 이을 수 없다.

| SELECT | 필요한 열 | 사내에서 주의할 점 |
|---|---|---|
| `results` | test_id, metric, value, unit, recipe_id, batch_id, temp_c, condition_json, source_ref | 셀 1개·측정 1회가 1행. `condition_json` 은 평가 조건 전체(문자열 포함)를 담은 JSON. 조건이 여러 열이면 SELECT 안에서 JSON 으로 합친다 |
| `batches` | batch_id, recipe_id | 제조 배치 → 조성. `results.recipe_id` 가 아니라 이 매핑이 기준 |
| `properties` | batch_id, property, value, unit, temp_c, method | `property` 는 `conductivity`/`viscosity`/`density`(또는 `Config.standard` 의 키). 배치 ID 가 NULL 인 행은 제외됨 |
| `components` | recipe_id, name, component_class, amount, unit, basis, material_id | `component_class` 는 `salt`/`solvent`/`additive` |
| `versions` (선택) | recipe_id, version | 없으면 허브 계약에서 '확인 불가' |
| `qc` (선택) | test_id, qc_status | 없으면 '확인 불가'. 환류(쓰기) 단계의 전제 |

## 3. 점검 순서 (각 단계가 통과해야 다음으로)

| 단계 | 명령 | 통과 기준 | 통과하지 못하면 |
|---|---|---|---|
| ① 연결 | `python -m electrolyte_platform preflight --db 사내.sqlite --sql 사내SELECT.json` | 필수 SELECT 4개가 '통과'(열 부족·오류·행 없음 없음) | SQL 의 열 별칭·테이블명 수정. NULL 이 많은 열은 ③에서 원인 확인 |
| ② 허브 계약 | `... hub --rules 규칙.json --db ... --sql ...` | '미충족'·'확인 불가' 항목마다 원인을 설명할 수 있다 | 물질 ID 미연결, 조성 표기 위반(단위·용매 합계), 배치 미연결 부터 정리 |
| ③ 현황표 | `... coverage --registry 지표사전.json --rules ... --db ... --sql ...` | '미분류' 지표 없음, '조건 미기재' 행의 원인 파악 | 지표 사전에 이름·필수 조건 추가. 행이 너무 잘게 쪼개지면 시점 묶음 기준 결정(0단계 #6) |
| ④ 첫 지표 결정 | 현황표의 추천 + 연구 중요도 | 지표·조건 1조합과 이유를 한 문장으로 적을 수 있다 | 추천이 없으면 '가장 가까운 조합'의 부족분(배치 매핑·물성 측정)을 보강 계획으로 |
| ⑤ 물성 추가 기여 | `... addvalue --metric ... --unit ... --min-improvement <사전 기준>` | **실행 전에** 개선 기준을 정했다. 결과 해석은 보고서 §3 따름 | 표본 부족이면 모델이 아니라 데이터 보강 |

각 단계에서 **수치를 고치거나 채워 넣지 않는다.** 누락·불일치는 제외 사유로 드러나는 것이 정상이다.

## 4. 결과를 믿기 전 확인 (사람이 직접)
- 현황표의 한 행을 골라 원본 DB 에서 **직접 세어** 고유 조성 수·배치 수가 같은지 맞춰 본다(2~3행).
- '배치 ID 누락' 비율이 높으면 결과 → 배치 매핑이 근본 문제다. 이 단계에서 `addvalue` 를 돌리지 않는다.
- 물성 '단위/온도 불일치'가 많으면 환산하지 말고 사내 측정 기록을 확인한다(자동 환산하지 않는 것이 의도).
- `addvalue` 의 조성 그룹 분할이 사내 '조성' 정의(`recipe_id` 가 조성 버전 단위인지)와 맞는지 확인한다. 같은 조성이 다른 ID 로 들어 있으면 학습·평가에 중복돼 성능이 과대평가된다.

## 5. 이 단계에서 하지 않는 것
- 사내 DB 에 쓰기(환류 포함), 사내 코드 수정, 사내 데이터를 이 저장소나 외부 서비스에 올리기.
- 기능 플래그·권한 확인: 서버에 붙이는 시점에 호스트가 넣는다(이 저장소에는 없음). 기본 OFF 로 시작한다.
- DOE(`doe`) 실제 적용: 본체 모델의 `predict` 를 붙이는 Adapter 와 사내 조성 규칙 확정 후.

## 6. 막혔을 때 사내 Claude 에게 넘길 정보
`preflight` 표, 오류 메시지, 0단계의 어느 항목이 불확실한지. **값이 들어 있는 행은 넘기지 않는다**(열 이름·건수만).
