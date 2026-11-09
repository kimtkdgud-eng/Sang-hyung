import unittest
from electrolyte_platform.adapters import SqlAdapter
from electrolyte_platform.coverage import build_table, Config
from electrolyte_platform.registry import load_registry
from electrolyte_platform import addvalue as av
from tests.helpers import mk, cell, full_props

REG = load_registry("configs/metric_registry.example.json")
COND_OK = '{"cell_spec":"S","soc_window":"0-100","c_rate":"1C","readout_cycles":300}'


class T(unittest.TestCase):
    def setUp(self):
        self.con = mk()
        cell(self.con, "a", "C1", "B1", cond=COND_OK, metric="상온수명/real/용량유지율")
        full_props(self.con, "B1")

    def row(self, con=None, **kw):
        return build_table(SqlAdapter(con or self.con), Config(min_compositions=1), registry=REG)[0]

    def test_mapped_metric_labelled(self):
        r = self.row()
        self.assertEqual(r["definition"].basis, "real")
        self.assertEqual(r["missing_conditions"], [])
        self.assertTrue(r["splittable"])

    def test_missing_required_condition_blocks_comparison(self):
        cell(self.con, "b", "C1", "B1", cond='{"cell_spec":"S","c_rate":"1C"}', metric="상온수명/RPT/용량유지율")
        rows = {t["metric"]: t for t in build_table(SqlAdapter(self.con), Config(min_compositions=1), registry=REG)}
        r = rows["상온수명/RPT/용량유지율"]
        self.assertIn("rpt_temp_c", r["missing_conditions"])
        self.assertFalse(r["splittable"])

    def test_unmapped_metric_is_surfaced_not_recommended(self):
        cell(self.con, "c", "C1", "B1", cond=COND_OK, metric="사내 임의 지표")
        rows = {t["metric"]: t for t in build_table(SqlAdapter(self.con), Config(min_compositions=1), registry=REG)}
        self.assertTrue(rows["사내 임의 지표"]["unmapped"])
        self.assertFalse(rows["사내 임의 지표"]["splittable"])

    def test_real_and_rpt_never_pooled(self):
        cell(self.con, "d", "C1", "B1", cond=COND_OK, metric="상온수명/RPT/용량유지율")
        metrics = {t["metric"] for t in build_table(SqlAdapter(self.con), Config(min_compositions=1), registry=REG)}
        self.assertEqual(len(metrics), 2)

    def test_without_registry_behaviour_unchanged(self):
        r = build_table(SqlAdapter(self.con), Config(min_compositions=1))[0]
        self.assertIsNone(r["definition"])
        self.assertFalse(r["unmapped"])

    def test_addvalue_blocks_incomplete_conditions(self):
        try:
            import sklearn  # noqa
        except ImportError:
            self.skipTest("scikit-learn 필요")
        cell(self.con, "e", "C1", "B1", cond='{"cell_spec":"S"}', metric="상온수명/RPT/용량유지율")
        r = av.compare(SqlAdapter(self.con), "상온수명/RPT/용량유지율", "%", av.Plan(0.5), registry=REG)
        self.assertEqual(r["status"], "blocked_incomplete_conditions")


if __name__ == "__main__":
    unittest.main()
