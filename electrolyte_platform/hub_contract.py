"""공통 DB 허브 계약 점검 (읽기 전용). 01·04·05 모듈이 허브에 안전하게 붙기 위한 최소 조건을 실제 데이터로 점검한다.

계약 필드: 물질 ID · 조성 버전 · 제조 배치 · 평가 조건 · 출처 · QC 상태. 값은 고치지 않고 충족 정도만 보고한다.
"""
from collections import Counter
from .composition import validate, Rules


def _ratio(n, d):
    return f"{n}/{d} ({n / d:.0%})" if d else "0/0"


def check(adapter, rules=None):
    rules = rules or Rules()
    comps = adapter.components()
    results = adapter.results()
    batch_recipe = adapter.batch_recipe()
    versions, qc = adapter.optional("versions"), adapter.optional("qc")
    rows = []

    allc = [c for cs in comps.values() for c in cs]
    linked = sum(1 for c in allc if c.get("material_id"))
    rows.append(("물질 ID 연결", linked == len(allc) and bool(allc), f"성분 {_ratio(linked, len(allc))} 가 Material ID 에 연결"))

    if versions is None:
        rows.append(("조성 버전", None, "확인 불가: 조성 버전 열이 없다(v2.12 internal_recipes 에는 없음). versions SELECT 필요"))
    else:
        have = {r[0] for r in versions}
        rows.append(("조성 버전", have >= set(comps), f"조성 {_ratio(len(have & set(comps)), len(comps))} 에 버전 있음"))

    viol, codes = [], Counter()
    for rid, cs in comps.items():
        iss = validate(cs, rules)
        if iss:
            viol.append(rid)
            codes.update(c for c, _ in iss)
    detail = ", ".join(f"{k} {v}" for k, v in sorted(codes.items())) or "-"
    rows.append(("조성 표기 규칙", not viol, f"위반 조성 {_ratio(len(viol), len(comps))}: {detail}"))

    with_batch = sum(1 for r in results if r.batch_id in batch_recipe)
    rows.append(("결과 → 제조 배치", with_batch == len(results) and bool(results), f"셀 결과 {_ratio(with_batch, len(results))} 가 등록된 배치에 연결"))
    has_cond = sum(1 for r in results if r.condition or r.temp_c is not None)
    rows.append(("평가 조건 기재", has_cond == len(results) and bool(results), f"셀 결과 {_ratio(has_cond, len(results))} 에 조건 있음"))
    has_src = sum(1 for r in results if r.source_ref)
    rows.append(("출처(원본 추적)", has_src == len(results) and bool(results), f"셀 결과 {_ratio(has_src, len(results))} 에 source_ref 있음"))
    if qc is None:
        rows.append(("QC 상태", None, "확인 불가: QC 상태 열이 없다. 환류(쓰기) 경로의 전제이므로 qc SELECT 필요"))
    else:
        approved = {r[0] for r in qc if r[1] == "approved"}
        rows.append(("QC 상태", None, f"셀 결과 {_ratio(sum(1 for r in results if r.test_id in approved), len(results))} 가 approved"))
    return rows


def to_markdown(rows):
    mark = {True: "충족", False: "미충족", None: "확인 불가"}
    lines = ["| 계약 항목 | 상태 | 내용 |", "|---|---|---|"]
    lines += [f"| {n} | {mark[ok]} | {d} |" for n, ok, d in rows]
    return "\n".join(lines) + "\n"
