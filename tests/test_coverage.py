import unittest
from electrolyte_platform.adapters import SqlAdapter
from electrolyte_platform.coverage import build_table, Config
from tests.helpers import mk, meas, cell, full_props


class T(unittest.TestCase):
    def table(self, con, **kw):
        return build_table(SqlAdapter(con), Config(**kw))

    def test_counts_unique_not_rows(self):
        con = mk()
        for i in range(3):
            cell(con, f"t{i}", "C1", "B1")      # 같은 배치의 반복 셀 3개
        full_props(con, "B1")
        t = self.table(con)[0]
        self.assertEqual((t["cell_rows"], t["batches"], t["compositions"]), (3, 1, 1))
        self.assertEqual(t["complete_compositions"], 1)

    def test_exclusions(self):
        con = mk()
        cell(con, "a", "C1", None); cell(con, "b", "C1", "B404"); cell(con, "c", "C1", "B2"); cell(con, "d", "C2", "B3")
        meas(con, "B2", "conductivity", "S/m")
        meas(con, "B3", "conductivity", "mS/cm", t=40.0)
        ex = self.table(con)[0]["exclusions"]
        self.assertEqual(ex["배치 ID 누락(셀 결과)"], 1)
        self.assertEqual(ex["배치 ID 미등록(셀 결과)"], 1)
        self.assertEqual(ex["conductivity 단위 불일치"], 1)
        self.assertEqual(ex["conductivity 온도 불일치"], 1)

    def test_no_batch_mapping_is_unknown_not_missing(self):
        con = mk()
        cell(con, "a", "C1", None); cell(con, "b", "C2", None)
        ex = self.table(con)[0]["exclusions"]
        self.assertIn("확인 불가: 결과→배치 매핑 필요", ex)

    def test_different_protocols_are_separate_rows(self):
        con = mk()
        cell(con, "a", "C1", "B1", cond='{"protocol":"P","hours":336}')
        cell(con, "b", "C1", "B2", cond='{"protocol":"P","hours":672}')
        cell(con, "c", "C2", "B3", cond='{"protocol":"P","hours":336}', temp=60.0)
        self.assertEqual(len(self.table(con)), 3)

    def test_duplicate_measurement_flagged_and_not_zero_filled(self):
        con = mk()
        cell(con, "a", "C1", "B1")
        full_props(con, "B1"); meas(con, "B1", "density", "g/cm3")
        t = self.table(con)[0]
        self.assertEqual(t["exclusions"]["물성 중복 측정(검토 필요)"], 1)
        con2 = mk(); cell(con2, "a", "C1", "B1"); meas(con2, "B1", "density", "g/cm3")
        self.assertEqual(self.table(con2)[0]["complete_batches"], 0)

    def test_splittable_threshold(self):
        con = mk(); cell(con, "a", "C1", "B1"); full_props(con, "B1")
        self.assertFalse(self.table(con, min_compositions=2)[0]["splittable"])
        self.assertTrue(self.table(con, min_compositions=1)[0]["splittable"])

    def test_adapter_is_read_only_and_select_only(self):
        con = mk()
        ad = SqlAdapter(con)
        with self.assertRaises(Exception):
            con.execute("INSERT INTO batches VALUES ('X','C1','x','t')")
        with self.assertRaises(ValueError):
            SqlAdapter(con, {"results": "DELETE FROM internal_results"})
        with self.assertRaises(ValueError):
            SqlAdapter(con, {"results": "SELECT 1; DROP TABLE batches"})


if __name__ == "__main__":
    unittest.main()
