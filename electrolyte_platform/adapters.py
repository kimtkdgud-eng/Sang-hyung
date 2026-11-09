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
from dataclasses import dataclass, field

DEFAULT_SQL = {
    "results": "SELECT test_id, metric, value, unit, recipe_id, batch_id, temperature_C AS temp_c, "
               "condition_json, source_ref FROM internal_results",
    "batches": "SELECT batch_id, recipe_id FROM batches",
    "properties": "SELECT batch_id, property, value, unit, temp_c, method FROM batch_properties",
    "components": "SELECT recipe_id, name, component_class, amount, unit, basis, material_id FROM internal_recipe_components",
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
        con.execute("PRAGMA query_only=ON")      # 쓰기 불가: 원본 보존

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
