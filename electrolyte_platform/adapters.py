"""읽기 전용 Adapter. 사내 테이블은 SELECT 문 4개로만 연결한다 (플랫폼 코드·스키마는 수정하지 않는다).

각 SELECT 가 돌려줘야 하는 열 이름:
  results    : test_id, metric, value, unit, recipe_id, batch_id, temp_c, condition_json, source_ref
  batches    : batch_id, recipe_id
  properties : batch_id, property, value, unit, temp_c, method
  components : recipe_id, name, component_class, amount, unit, basis, material_id
  versions   : (선택) recipe_id, version        -- 조성 버전. 없으면 계약 점검에서 '확인 불가'
  qc         : (선택) test_id, qc_status        -- 셀 결과 QC 상태. 없으면 '확인 불가'

"""
import json
import re
import sqlite3
from dataclasses import dataclass, field

DEFAULT_SQL = {
    "results": "SELECT test_id, metric, value, unit, recipe_id, batch_id, temperature_C AS temp_c, "
               "condition_json, source_ref FROM internal_results",
    "batches": "SELECT batch_id, recipe_id FROM batches",
    "properties": "SELECT batch_id, property, value, unit, temp_c, method FROM batch_properties",
    "components": "SELECT recipe_id, name, component_class, amount, unit, basis, material_id FROM internal_recipe_components",
}
REQUIRED = {
    "results": ["test_id", "metric", "value", "unit", "recipe_id", "batch_id", "temp_c", "condition_json", "source_ref"],
    "batches": ["batch_id", "recipe_id"],
    "properties": ["batch_id", "property", "value", "unit", "temp_c", "method"],
    "components": ["recipe_id", "name", "component_class", "amount", "unit", "basis", "material_id"],
    "versions": ["recipe_id", "version"],
    "qc": ["test_id", "qc_status"],
}
_SELECT_ONLY = re.compile(r"^\s*select\b", re.I)


@dataclass(frozen=True)
class CellRow:
    test_id: str
    metric: str
    value: float
    unit: str
    recipe_id: str
    batch_id: str
    temp_c: float
    condition: tuple          # 정렬된 (키, 값) 튜플: 문자열 조건도 보존한다
    source_ref: str = None

    @property
    def group_key(self):
        """지표 x 동일 평가 조건. 문자열 프로토콜·셀 사양도 키에 포함된다."""
        return (self.metric, self.unit, self.temp_c, self.condition)


@dataclass(frozen=True)
class PropRow:
    batch_id: str
    property: str
    value: float
    unit: str
    temp_c: float
    method: str


def _condition(text):
    if not text:
        return ()
    try:
        obj = json.loads(text)
    except (TypeError, ValueError):
        return (("_unparsed", str(text)),)
    if not isinstance(obj, dict):
        return (("_unparsed", str(text)),)
    return tuple(sorted((str(k), v if isinstance(v, (int, float, str, bool)) or v is None else str(v))
                        for k, v in obj.items()))


class SqlAdapter:
    def __init__(self, con, sql=None):
        self.sql = {**DEFAULT_SQL, **(sql or {})}
        for name, q in self.sql.items():
            if not _SELECT_ONLY.match(q) or ";" in q.strip().rstrip(";"):
                raise ValueError(f"{name}: 단일 SELECT 문만 허용한다")
        self.con = con
        if isinstance(con, sqlite3.Connection):
            con.execute("PRAGMA query_only=ON")  # 쓰기 불가: 원본 보존
        # SQLite 가 아니면 이 보호가 없다 -> 반드시 읽기 전용 계정/뷰로 연결한다(docs/INTEGRATION_CHECKLIST_KO.md)

    def _rows(self, name):
        return self.con.execute(self.sql[name].rstrip().rstrip(";")).fetchall()

    def results(self):
        return [CellRow(r["test_id"], r["metric"], r["value"], r["unit"], r["recipe_id"], r["batch_id"],
                        r["temp_c"], _condition(r["condition_json"]), r["source_ref"]) for r in self._rows("results")]

    def batch_recipe(self):
        return {r["batch_id"]: r["recipe_id"] for r in self._rows("batches")}

    def properties(self):
        return [PropRow(r["batch_id"], r["property"], r["value"], r["unit"], r["temp_c"], r["method"])
                for r in self._rows("properties") if r["batch_id"] is not None]

    def optional(self, name):
        """선택 SELECT(versions, qc). 설정이 없으면 None = 확인 불가."""
        return {tuple(r) for r in self._rows(name)} if name in self.sql else None

    def components(self):
        out = {}
        for r in self._rows("components"):
            out.setdefault(r["recipe_id"], []).append(dict(r))
        return out


def open_readonly(path):
    """사내 SQLite 파일을 읽기 전용으로 연다(테이블 생성·쓰기 불가, 없는 파일을 만들지도 않는다)."""
    from pathlib import Path
    if not Path(path).is_file():
        raise FileNotFoundError(path)
    con = sqlite3.connect(f"file:{Path(path).resolve().as_posix()}?mode=ro", uri=True)
    con.row_factory = sqlite3.Row
    return con


def preflight(adapter):
    """SELECT 별로 실행 가능 여부, 필요한 열 이름, 행 수, 열별 NULL 수를 점검한다. 값은 읽지 않고 집계만 한다."""
    out = []
    for name, cols in REQUIRED.items():
        optional = name in ("versions", "qc")
        if name not in adapter.sql:
            out.append(dict(name=name, optional=optional, configured=False))
            continue
        q = adapter.sql[name].strip().rstrip(";")
        item = dict(name=name, optional=optional, configured=True, rows=None, missing=[], nulls={}, error=None)
        try:
            have = [d[0] for d in adapter.con.execute(f"SELECT * FROM ({q}) AS _q LIMIT 0").description]
            item["missing"] = [c for c in cols if c not in have]
            item["rows"] = adapter.con.execute(f"SELECT count(*) FROM ({q}) AS _q").fetchone()[0]
            present = [c for c in cols if c in have]
            if present and item["rows"]:
                agg = ", ".join(f"sum(CASE WHEN {c} IS NULL THEN 1 ELSE 0 END)" for c in present)
                row = adapter.con.execute(f"SELECT {agg} FROM ({q}) AS _q").fetchone()
                item["nulls"] = {c: int(v or 0) for c, v in zip(present, row)}
        except Exception as e:                      # 사내 SQL 오류는 그대로 보여 준다
            item["error"] = f"{type(e).__name__}: {e}"
        out.append(item)
    return out


def preflight_markdown(rows):
    lines = ["| SELECT | 상태 | 행 수 | 누락된 열 | NULL 이 있는 열 |", "|---|---|---|---|---|"]
    for r in rows:
        tag = " (선택)" if r["optional"] else ""
        if not r["configured"]:
            lines.append(f"| {r['name']}{tag} | 미설정 | - | - | - |")
        elif r["error"]:
            lines.append(f"| {r['name']}{tag} | 오류 | - | - | {r['error']} |")
        else:
            nulls = ", ".join(f"{k} {v}" for k, v in r["nulls"].items() if v) or "-"
            state = "통과" if not r["missing"] and r["rows"] else ("행 없음" if not r["rows"] else "열 부족")
            lines.append(f"| {r['name']}{tag} | {state} | {r['rows']} | {', '.join(r['missing']) or '-'} | {nulls} |")
    return "\n".join(lines) + "\n"
