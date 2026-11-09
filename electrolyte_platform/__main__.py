"""사용: python -m electrolyte_platform coverage [--db 파일.sqlite]   (없으면 가상 데이터)"""
import argparse
from . import synthetic
from .schema import connect
from .coverage import build_table, to_markdown

p = argparse.ArgumentParser()
p.add_argument("cmd", choices=["coverage"])
p.add_argument("--db", help="SQLite 파일. 생략하면 가상 데이터로 실행")
a = p.parse_args()
con = connect(a.db) if a.db else synthetic.build()
print(to_markdown(build_table(con)))
