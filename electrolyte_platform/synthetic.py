"""구조 검증용 가상 데이터 (실제 데이터 아님). 결함(누락·중복·단위/온도 불일치·조건 혼재)을 일부러 넣는다.

signal='none'     : 셀 결과가 조성에만 의존 (물성은 무관) -> 물성 추가 효과 없음이 정답
signal='property' : 셀 결과가 조성 + 배치 전도도에 의존 (전도도는 조성과 독립) -> 물성 추가 효과 있음이 정답
"""
import json
import random
import time
from .demo_schema import connect

# metric: (unit, 조건 dict, 사이클·저장 온도, 커버리지). 지표 이름은 예시이며 사내 이름은 registry 로 연결한다.
def _life(temp, rpt):
    c = {"cell_spec": "NCM811/Gr 2Ah", "soc_window": "0-100", "c_rate": "1C", "readout_cycles": 300}
    if rpt:
        c.update(rpt_temp_c=25, rpt_c_rate="0.33C")
    return c


_STO = {"cell_spec": "NCM811/Gr 2Ah", "storage_soc": 100, "storage_hours": 336}
METRICS = {}
for _cat, _temp, _cov in (("상온수명", 25, 0.9), ("고온수명", 45, 0.5)):
    for _basis, _rpt in (("real", False), ("RPT", True)):
        for _q in ("용량유지율", "저항증가율"):
            METRICS[f"{_cat}/{_basis}/{_q}"] = ("%", _life(_temp, _rpt), _temp, _cov * (0.7 if _rpt else 1.0))
METRICS["고온저장/retention/용량"] = ("%", dict(_STO), 60, 0.6)
METRICS["고온저장/recovery/용량"] = ("%", dict(_STO), 60, 0.55)
METRICS["고온저장/저항"] = ("%", dict(_STO), 60, 0.3)


def build(seed=0, n_comp=60, signal="none", defects=True, db=":memory:"):
    rnd = random.Random(seed)
    con = connect(db)
    now = time.time()
    comps, batches = {}, []
    for i in range(n_comp):
        rid = f"RCP-{i:03d}"
        ec = rnd.uniform(20, 40)
        emc = rnd.uniform(20, 100 - ec - 10)
        dmc = 100 - ec - emc
        feat = dict(salt=rnd.uniform(0.8, 1.4), EC=ec, EMC=emc, DMC=dmc, VC=rnd.uniform(0, 2), FEC=rnd.uniform(0, 10))
        comps[rid] = feat
        con.execute("INSERT INTO internal_recipes VALUES (?,?,?,?)", (rid, f"synthetic {i}", "synthetic", now))
        rows = [("LiPF6", "salt", feat["salt"], "mol/L"), ("EC", "solvent", ec, "vol%"), ("EMC", "solvent", emc, "vol%"),
                ("DMC", "solvent", dmc, "vol%"), ("VC", "additive", feat["VC"], "wt%"), ("FEC", "additive", feat["FEC"], "wt%")]
        mid = {"LiPF6": "MAT-S1", "EC": "MAT-V1", "EMC": "MAT-V2", "DMC": "MAT-V3", "VC": "MAT-A1", "FEC": "MAT-A2"}
        con.executemany("INSERT INTO internal_recipe_components(recipe_id,name,component_class,amount,unit,basis,material_id)"
                        " VALUES (?,?,?,?,?,'total_electrolyte',?)",
                        [(rid,) + r + (None if defects and rnd.random() < 0.05 else mid[r[0]],) for r in rows])
        for _ in range(rnd.choice([1, 1, 2, 3])):
            bid = f"B{len(batches):04d}"
            cond = rnd.uniform(4, 12)                      # 배치별 전도도: 조성과 독립
            batches.append((bid, rid, cond))
            con.execute("INSERT INTO batches VALUES (?,?,'2026-10-01','synthetic')", (bid, rid))
    for bid, rid, cond in batches:
        for prop, unit, temp, cov in (("conductivity", "mS/cm", 25, 0.85), ("viscosity", "mPa.s", 25, 0.6),
                                      ("density", "g/cm3", 25, 0.8)):
            if rnd.random() > cov:
                continue
            u, t, v = unit, temp, round(rnd.uniform(1, 12), 3)
            if prop == "conductivity":
                v = round(cond, 3)
            r = rnd.random()
            if defects and r < 0.05 and prop == "conductivity":
                u = "S/m"
            elif defects and r < 0.10:
                t = 40
            con.execute("INSERT INTO batch_properties(batch_id,property,value,unit,temp_c,method,source)"
                        " VALUES (?,?,?,?,?,'EIS','synthetic')", (bid, prop, v, u, t))
            if defects and rnd.random() < 0.04:
                con.execute("INSERT INTO batch_properties(batch_id,property,value,unit,temp_c,method,source)"
                            " VALUES (?,?,?,?,?,'EIS','synthetic')", (bid, prop, v, u, t))
    n = 0
    for metric, (unit, cnd, temp, cov) in METRICS.items():
        for bid, rid, cond in batches:
            if rnd.random() > cov:
                continue
            f = comps[rid]
            base = 80 + 0.25 * f["EC"] - 0.05 * f["EMC"] + 1.5 * f["VC"] + 0.3 * f["FEC"]
            if signal == "property":
                base += 2.0 * (cond - 8)
            c = dict(cnd)
            if metric.startswith("고온저장") and rnd.random() < 0.25:
                c["storage_hours"] = 672                   # 다른 저장 시간 -> 별도 조건 행
            if metric == "고온수명/RPT/저항증가율" and rnd.random() < 0.15:
                c.pop("rpt_temp_c")                        # 필수 조건 누락 -> 비교 불가 표시
            for _ in range(rnd.choice([1, 2, 3])):
                n += 1
                b = bid
                r = rnd.random()
                if defects and r < 0.03:
                    b = None
                elif defects and r < 0.05:
                    b = "B9999"
                con.execute("INSERT INTO internal_results(recipe_id,test_id,metric,value,unit,temperature_C,condition_json,"
                            "source_ref,created_at,batch_id) VALUES (?,?,?,?,?,?,?,'synthetic',?,?)",
                            (rid, f"T{n:05d}", metric, round(base + rnd.gauss(0, 1.0), 3), unit, temp,
                             json.dumps(c, ensure_ascii=False), now, b))
    con.commit()
    return con
