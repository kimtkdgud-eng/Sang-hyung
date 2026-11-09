"""구조 검증용 가상 데이터 (실제 데이터 아님). 결함(누락·중복·단위/온도 불일치·조건 혼재)을 일부러 넣는다.

signal='none'     : 셀 결과가 조성에만 의존 (물성은 무관) -> 물성 추가 효과 없음이 정답
signal='property' : 셀 결과가 조성 + 배치 전도도에 의존 (전도도는 조성과 독립) -> 물성 추가 효과 있음이 정답
"""
import json
import random
import time
from .demo_schema import connect

# metric: (unit, 조건 dict, 온도, 커버리지)
METRICS = {
    "고온저장 회복률": ("%", {"cell_spec": "NCM811/Gr 2Ah", "soc_pct": 100, "protocol": "60C 저장 후 25C 회복", "hours": 336}, 60, 0.6),
    "초기 DCIR": ("mohm", {"cell_spec": "NCM811/Gr 2Ah", "soc_pct": 50, "protocol": "10s 펄스"}, 25, 0.9),
    "수명 유지율": ("%", {"cell_spec": "NCM811/Gr 2Ah", "soc_pct": 100, "protocol": "1C/1C", "cycles": 300}, 25, 0.5),
    "급속충전 유지율": ("%", {"cell_spec": "NCM811/Gr 2Ah", "soc_pct": 100, "protocol": "3C 충전", "cycles": 100}, 25, 0.3),
    "저온 방전 용량비": ("%", {"cell_spec": "NCM811/Gr 2Ah", "soc_pct": 100, "protocol": "0.5C 방전"}, -10, 0.12),
}


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
            if metric == "고온저장 회복률" and rnd.random() < 0.25:
                c["hours"] = 672                           # 다른 저장 시간 -> 별도 조건 행
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
