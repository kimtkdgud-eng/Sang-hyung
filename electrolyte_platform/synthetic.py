"""구조 검증용 가상 데이터. 실제 데이터가 아니며 일부러 결함(누락·중복·단위 불일치)을 넣는다."""
import random
from .schema import connect

METRICS = {
    # metric: (unit, cell_spec, temp, soc, protocol, extra, n_comp_coverage)
    "고온저장 회복률": ("%", "NCM811/Gr 2Ah", 60, 100, "60C 저장 후 25C 회복", "14d", 0.6),
    "초기 DCIR": ("mohm", "NCM811/Gr 2Ah", 25, 50, "10s 펄스", "", 0.9),
    "수명 유지율": ("%", "NCM811/Gr 2Ah", 25, 100, "1C/1C 300cyc", "300cyc", 0.5),
    "급속충전 유지율": ("%", "NCM811/Gr 2Ah", 25, 100, "3C 충전 100cyc", "100cyc", 0.3),
    "저온 방전 용량비": ("%", "NCM811/Gr 2Ah", -10, 100, "0.5C 방전", "", 0.12),
}


def build(seed=0, n_comp=60, db=":memory:"):
    rnd = random.Random(seed)
    con = connect(db)
    mats = [("S1", "LiPF6", "salt"), ("S2", "LiFSI", "salt"),
            ("V1", "EC", "solvent"), ("V2", "EMC", "solvent"), ("V3", "DMC", "solvent"),
            ("A1", "VC", "additive"), ("A2", "FEC", "additive")]
    con.executemany("INSERT INTO material VALUES (?,?,?,'synthetic')", mats)
    batches = []
    for i in range(n_comp):
        cid = f"C{i:03d}"
        con.execute("INSERT INTO composition VALUES (?,1,'synthetic')", (cid,))
        con.execute("INSERT INTO composition_item VALUES (?,1,'S1',1.0,'mol/L')", (cid,))
        for k, mid in enumerate(rnd.sample(["V1", "V2", "V3"], 2)):
            con.execute("INSERT INTO composition_item VALUES (?,1,?,?, 'vol%')", (cid, mid, 50 if k == 0 else 50))
        for _ in range(rnd.choice([1, 1, 2, 3])):          # 조성당 배치 1~3개
            bid = f"B{len(batches):04d}"
            batches.append((bid, cid))
            con.execute("INSERT INTO batch VALUES (?,?,1,'2026-10-01','synthetic')", (bid, cid))
    # 실측 물성: 일부 배치만 측정, 일부러 결함 삽입
    for bid, _ in batches:
        for prop, unit, temp, cov in (("conductivity", "mS/cm", 25, 0.85),
                                      ("viscosity", "mPa.s", 25, 0.6),
                                      ("density", "g/cm3", 25, 0.8)):
            if rnd.random() > cov:
                continue
            u, t = unit, temp
            r = rnd.random()
            if r < 0.05 and prop == "conductivity":
                u = "S/m"                                  # 단위 불일치
            elif r < 0.10:
                t = 40                                     # 온도 불일치
            val = round(rnd.uniform(1, 12), 3)
            con.execute("INSERT INTO property_measurement(batch_id,property,value,unit,temp_c,method,source)"
                        " VALUES (?,?,?,?,?,'EIS','synthetic')", (bid, prop, val, u, t))
            if rnd.random() < 0.04:                        # 중복 입력
                con.execute("INSERT INTO property_measurement(batch_id,property,value,unit,temp_c,method,source)"
                            " VALUES (?,?,?,?,?,'EIS','synthetic')", (bid, prop, val, u, t))
    # 셀 평가
    n = 0
    for metric, (unit, spec, temp, soc, proto, extra, cov) in METRICS.items():
        for bid, _ in batches:
            if rnd.random() > cov:
                continue
            for rep in range(rnd.choice([1, 2, 3])):       # 반복 셀
                n += 1
                b = bid
                r = rnd.random()
                if r < 0.03:
                    b = None                               # 배치 ID 누락
                elif r < 0.05:
                    b = "B9999"                            # 존재하지 않는 배치
                con.execute("INSERT INTO cell_result(cell_id,batch_id,metric,value,unit,cell_spec,temp_c,soc_pct,"
                            "protocol,extra,source) VALUES (?,?,?,?,?,?,?,?,?,?,'synthetic')",
                            (f"CELL{n:05d}", b, metric, round(rnd.uniform(70, 99), 2), unit, spec, temp, soc, proto, extra))
    con.commit()
    return con
