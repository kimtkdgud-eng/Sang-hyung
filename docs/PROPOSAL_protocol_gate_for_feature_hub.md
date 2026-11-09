# 제안: build_training_samples 에 평가 조건 일치 게이트 추가

대상: v2.12 `backend/feature_hub.py::build_training_samples` (사내 코드, 여기서는 수정하지 않음)

## 현재 동작 (소스 확인)
- `SELECT * FROM internal_results WHERE metric=? AND unit=?` 로 학습 데이터를 고른다.
- `_numeric_condition_features` 는 condition_json 의 숫자·불리언만 특징으로 쓰고 **문자열(프로토콜, 셀 사양 등)은 버린다**.
- 결과: 셀 사양·프로토콜이 다른 결과가 한 모델에 합쳐질 수 있다. `readiness()` 의 'mixed' 표시는 경고일 뿐 학습을 막지 않는다.

## 제안 (기존 동작 유지, 선택 인자로 추가)
```python
def build_training_samples(metric, unit=None, *, condition_profile=None, require_single_profile=False):
    ...
    profiles = {(r['temperature_C'], r['condition_json']) for r in rows}      # 정규화한 JSON 권장
    if condition_profile is not None:
        rows = [r for r in rows if (r['temperature_C'], r['condition_json']) == condition_profile]
    elif require_single_profile and len(profiles) > 1:
        raise ValueError(f'평가 조건 {len(profiles)}가지가 섞여 있다. condition_profile 을 선택하세요.')
```
- 기본값(`require_single_profile=False`)은 현재와 동일하므로 회귀 위험이 없다.
- feature flag 로 UI 기본값을 True 로 바꾸는 것은 별도 결정.
- 시험: 조건이 다른 두 결과가 섞인 fixture 에서 (1) 기본 호출은 기존과 동일, (2) require_single_profile 은 오류, (3) condition_profile 지정 시 해당 행만 반환.

참고 구현: 이 저장소의 `electrolyte_platform/gate.py`.
