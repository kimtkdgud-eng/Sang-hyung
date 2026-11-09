import unittest
from electrolyte_platform.schema import connect
from electrolyte_platform.coverage import build_table, Config


def mk():
    con = connect()
    con.execute("INSERT INTO composition VALUES ('C1',1,'t')")
    con.execute("INSERT INTO composition VALUES ('C2',1,'t')")
    for b, c in (("B1", "C1"), ("B2", "C1"), ("B3", "C2")):
        con.execute("INSERT INTO batch VALUES (?,?,1,'x','t')", (b, c))
    return con


def meas(con, b, p, u, t=25.0, v=1.0):
    con.execute("INSERT INTO property_measurement(batch_id,property,value,unit,temp_c) VALUES (?,?,?,?,?)", (b, p, v, u, t))


def cell(con, cid, b, v=90.0):
    con.execute("INSERT INTO cell_result(cell_id,batch_id,metric,value,unit,cell_spec,temp_c,soc_pct,protocol)"
                " VALUES (?,?,'M',?,'%','S',25,100,'P')", (cid, b, v))


UNITS = (("conductivity", "mS/cm"), ("viscosity", "mPa.s"), ("density", "g/cm3"))


class T(unittest.TestCase):
    def test_counts_unique_not_rows(self):
        con = mk()
        for i in range(3):          # 같은 배치의 반복 셀 3개
            cell(con, f"c{i}", "B1")
        for p, u in UNITS:
            meas(con, "B1", p, u)
        t = build_table(con)[0]
        self.assertEqual((t["cell_rows"], t["batches"], t["compositions"]), (3, 1, 1))
        self.assertEqual(t["complete_compositions"], 1)

    def test_exclusions(self):
        con = mk()
        cell(con, "a", None); cell(con, "b", "B404"); cell(con, "c", "B2"); cell(con, "d", "B3")
        meas(con, "B2", "conductivity", "S/m")              # 단위 불일치
        meas(con, "B3", "conductivity", "mS/cm", t=40.0)    # 온도 불일치
        t = build_table(con)[0]
        ex = t["exclusions"]
        self.assertEqual(ex["배치 ID 누락(셀 결과)"], 1)
        self.assertEqual(ex["배치 ID 미등록(셀 결과)"], 1)
        self.assertEqual(ex["conductivity 단위 불일치"], 1)
        self.assertEqual(ex["conductivity 온도 불일치"], 1)
        self.assertEqual(t["complete_batches"], 0)

    def test_missing_not_zero_filled_and_duplicates_flagged(self):
        con = mk()
        cell(con, "a", "B1")
        for p, u in UNITS:
            meas(con, "B1", p, u)
        meas(con, "B1", "density", "g/cm3")                 # 중복
        t = build_table(con)[0]
        self.assertEqual(t["exclusions"]["물성 중복 측정(검토 필요)"], 1)
        self.assertEqual(t["complete_batches"], 1)

    def test_splittable_threshold(self):
        con = mk()
        cell(con, "a", "B1")
        for p, u in UNITS:
            meas(con, "B1", p, u)
        self.assertFalse(build_table(con, Config(min_compositions=2))[0]["splittable"])
        self.assertTrue(build_table(con, Config(min_compositions=1))[0]["splittable"])


if __name__ == "__main__":
    unittest.main()
