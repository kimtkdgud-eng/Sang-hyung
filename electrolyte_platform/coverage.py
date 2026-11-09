"""평가 지표별 데이터 연결 현황표 (읽기 전용 조회).

행 단위 = 지표 x 동일 평가 조건(셀 사양, 온도, SOC, 프로토콜, 추가 조건).
'표본'은 셀 결과 행 수가 아니라 고유 조성 수 / 제조 배치 수로 센다.
"""
from collections import Counter, defaultdict
from dataclasses import dataclass, field

# 물성 비교 기준 (회사 기준으로 교체): property -> (단위, 측정 온도 C)
STANDARD = {
    "conductivity": ("mS/cm", 25.0),
    "viscosity": ("mPa.s", 25.0),
    "density": ("g/cm3", 25.0),
}
REASON_KO = {"missing": "미측정", "unit": "단위 불일치", "temp": "온도 불일치"}


@dataclass
class Config:
    standard: dict = field(default_factory=lambda: dict(STANDARD))
    required_props: tuple = ("conductivity", "viscosity", "density")
    min_compositions: int = 20          # 검증 분할이 가능한 최소 고유 조성 수 (5-fold에서 분할당 4개)
    importance: dict = field(default_factory=dict)   # 지표별 연구 중요도, 미지정은 1.0 (연구자가 입력)


def _classify(rows, std_unit, std_temp):
    """한 배치의 한 물성 측정 목록 -> (usable 여부, 사유, 중복 여부)."""
    if not rows:
        return False, "missing", False
    ok = [r for r in rows if r["unit"] == std_unit and r["temp_c"] == std_temp and r["value"] is not None]
    if ok:
        return True, None, len(rows) > 1
    if any(r["unit"] != std_unit for r in rows):
        return False, "unit", len(rows) > 1
    return False, "temp", len(rows) > 1


def build_table(con, cfg=None):
    cfg = cfg or Config()
    batch_comp = {r["batch_id"]: r["composition_id"] for r in con.execute("SELECT batch_id, composition_id FROM batch")}
    meas = defaultdict(lambda: defaultdict(list))
    for r in con.execute("SELECT * FROM property_measurement WHERE batch_id IS NOT NULL"):
        meas[r["batch_id"]][r["property"]].append(r)

    groups = defaultdict(list)
    for r in con.execute("SELECT * FROM cell_result"):
        key = (r["metric"], r["unit"], r["cell_spec"], r["temp_c"], r["soc_pct"], r["protocol"], r["extra"] or "")
        groups[key].append(r)

    out = []
    for key, rows in groups.items():
        metric, unit, spec, temp, soc, proto, extra = key
        excl = Counter()
        cell_ids = Counter(r["cell_id"] for r in rows)
        dup_cells = sum(1 for c in cell_ids.values() if c > 1)
        valid = []
        for r in rows:
            if r["batch_id"] is None:
                excl["배치 ID 누락(셀 결과)"] += 1
            elif r["batch_id"] not in batch_comp:
                excl["배치 ID 미등록(셀 결과)"] += 1
            elif r["value"] is None:
                excl["셀 결과값 없음"] += 1
            else:
                valid.append(r)
        if dup_cells:
            excl["셀 ID 중복"] += dup_cells
        batches = {r["batch_id"] for r in valid}
        comps = {batch_comp[b] for b in batches}
        per_prop = {p: 0 for p in cfg.standard}
        complete_b = set()
        dup_meas = 0
        for b in batches:
            ok_all = True
            for p, (su, st) in cfg.standard.items():
                usable, why, dup = _classify(meas[b].get(p, []), su, st)
                dup_meas += dup
                if usable:
                    per_prop[p] += 1
                else:
                    excl[f"{p} {REASON_KO[why]}"] += 1
                    if p in cfg.required_props:
                        ok_all = False
            if ok_all:
                complete_b.add(b)
        complete_c = {batch_comp[b] for b in complete_b}
        if dup_meas:
            excl["물성 중복 측정(검토 필요)"] += dup_meas
        out.append(dict(
            metric=metric, unit=unit, condition=f"{spec} / {temp:g}C / SOC{soc:g}% / {proto}" + (f" / {extra}" if extra else ""),
            cell_rows=len(rows), compositions=len(comps), batches=len(batches),
            per_prop=per_prop, complete_batches=len(complete_b), complete_compositions=len(complete_c),
            exclusions=dict(excl),
            splittable=len(complete_c) >= cfg.min_compositions,
            score=cfg.importance.get(metric, 1.0) * len(complete_c),
        ))
    out.sort(key=lambda x: (-x["score"], x["metric"]))
    return out


def recommend(table, cfg=None):
    cfg = cfg or Config()
    ok = [t for t in table if t["splittable"]]
    if not ok:
        best = max(table, key=lambda t: t["complete_compositions"], default=None)
        if not best:
            return "셀 결과가 없어 추천할 수 없다."
        return (f"검증 분할이 가능한 조합이 없다(기준: 물성이 갖춰진 고유 조성 {cfg.min_compositions}개 이상). "
                f"가장 가까운 조합은 '{best['metric']}'({best['complete_compositions']}개)이며, 먼저 배치 매핑·물성 측정 보강이 필요하다.")
    t = ok[0]
    return (f"첫 검증은 '{t['metric']}' [{t['condition']}]을 추천한다: 물성이 모두 갖춰진 고유 조성 "
            f"{t['complete_compositions']}개(배치 {t['complete_batches']}개)로 기준 {cfg.min_compositions}개를 넘어 그룹 분할 검증이 가능하다.")


def to_markdown(table, cfg=None):
    cfg = cfg or Config()
    props = list(cfg.standard)
    h = ["지표·조건", "셀 결과 행", "고유 조성", "제조 배치"] + [f"{p} 배치" for p in props] + \
        ["물성 동시 확보 (조성/배치)", "제외 사유", "분할 가능"]
    lines = ["| " + " | ".join(h) + " |", "|" + "---|" * len(h)]
    for t in table:
        ex = ", ".join(f"{k} {v}" for k, v in sorted(t["exclusions"].items())) or "-"
        row = [f"**{t['metric']}** ({t['unit']}) {t['condition']}", t["cell_rows"], t["compositions"], t["batches"]] + \
              [t["per_prop"][p] for p in props] + \
              [f"{t['complete_compositions']} / {t['complete_batches']}", ex, "예" if t["splittable"] else "아니오"]
        lines.append("| " + " | ".join(str(x) for x in row) + " |")
    return "\n".join(lines) + "\n\n**추천:** " + recommend(table, cfg) + "\n"
