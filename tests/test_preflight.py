import hashlib
import os
import sqlite3
import tempfile
import unittest
from electrolyte_platform import synthetic
from electrolyte_platform.adapters import SqlAdapter, open_readonly, preflight, preflight_markdown


def sha(p):
    return hashlib.sha256(open(p, "rb").read()).hexdigest()


class T(unittest.TestCase):
    def test_open_readonly_never_writes_or_creates(self):
        with tempfile.TemporaryDirectory() as d:
            path = os.path.join(d, "x.sqlite")
            src = synthetic.build(db=path); src.close()
            before = sha(path)
            con = open_readonly(path)
            ad = SqlAdapter(con)
            self.assertGreater(len(ad.results()), 0)
            with self.assertRaises(sqlite3.OperationalError):
                con.execute("CREATE TABLE evil(x)")
            with self.assertRaises(sqlite3.OperationalError):
                con.execute("DELETE FROM batches")
            con.close()
            self.assertEqual(before, sha(path))
            with self.assertRaises(FileNotFoundError):
                open_readonly(os.path.join(d, "missing.sqlite"))
            self.assertFalse(os.path.exists(os.path.join(d, "missing.sqlite")))

    def test_preflight_reports_missing_columns_and_errors(self):
        ad = SqlAdapter(synthetic.build(), {"batches": "SELECT batch_id FROM batches",
                                            "properties": "SELECT * FROM no_such_table"})
        res = {r["name"]: r for r in preflight(ad)}
        self.assertEqual(res["batches"]["missing"], ["recipe_id"])
        self.assertIn("no_such_table", res["properties"]["error"])
        self.assertFalse(res["versions"]["configured"])
        self.assertGreater(res["results"]["rows"], 0)
        self.assertGreater(res["results"]["nulls"]["batch_id"], 0)       # 가상 데이터에 넣어 둔 배치 ID 누락
        self.assertIn("열 부족", preflight_markdown(list(res.values())))

    def test_preflight_all_pass_on_default_sql(self):
        for r in preflight(SqlAdapter(synthetic.build())):
            if r["configured"]:
                self.assertEqual(r["missing"], [], r["name"])


if __name__ == "__main__":
    unittest.main()
