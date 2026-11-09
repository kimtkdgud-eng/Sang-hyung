"""평가 조건 일치 게이트.

v2.12 feature_hub.build_training_samples 는 metric+unit 만으로 학습 데이터를 고르고 문자열 조건을 버린다.
여기서는 '동일 평가 조건 1개'가 아니면 분석을 막는다 (Feature-to-Target v0.2 의 blocked_mixed_conditions 와 같은 원칙).
"""
from .adapters import CellRow


class MixedConditionsError(ValueError):
    pass


def select_group(rows, metric, unit, condition_key=None):
    """metric+unit 의 행들을 조건별로 나눈다. 조건이 여럿인데 condition_key 가 없으면 막는다."""
    rows = [r for r in rows if r.metric == metric and r.unit == unit]
    if not rows:
        raise ValueError(f"{metric} ({unit}) 결과가 없다")
    keys = sorted({r.group_key for r in rows}, key=str)
    if condition_key is None:
        if len(keys) > 1:
            raise MixedConditionsError(
                f"{metric} ({unit}) 에 평가 조건이 {len(keys)}가지 섞여 있다. 조건 하나를 선택하세요(condition_key).")
        condition_key = keys[0]
    chosen = [r for r in rows if r.group_key == condition_key]
    if not chosen:
        raise ValueError("선택한 평가 조건에 해당하는 결과가 없다")
    return chosen, condition_key
