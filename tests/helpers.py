from electrolyte_platform.demo_schema import connect
from electrolyte_platform.adapters import SqlAdapter

UNITS = (("conductivity", "mS/cm"), ("viscosity", "mPa.s"), ("density", "g/cm3"))


def mk(recipes=("C1", "C2"), batches=(("B1", "C1"), ("B2", "C1"), ("B3", "C2"))):
    con = connect()
    for r in recipes:
        con.execute("INSERT INTO internal_recipes VALUES (?,?,?,0)", (r, r, ""))
        con.execute("INSERT INTO internal_recipe_components(recipe_id,name,component_class,amount,unit,basis)"
                    " VALUES (?,'EC','solvent',30,'vol%','total_electrolyte')", (r,))
    for b, r in batches:
        con.execute("INSERT INTO batches VALUES (?,?,'x','t')", (b, r))
    return con


def meas(con, b, p, u, t=25.0, v=1.0):
    con.execute("INSERT INTO batch_properties(batch_id,property,value,unit,temp_c) VALUES (?,?,?,?,?)", (b, p, v, u, t))


def cell(con, tid, rid, b, v=90.0, cond='{"protocol":"P"}', metric="M", temp=25.0):
    con.execute("INSERT INTO internal_results(recipe_id,test_id,metric,value,unit,temperature_C,condition_json,batch_id)"
                " VALUES (?,?,?,?,'%',?,?,?)", (rid, tid, metric, v, temp, cond, b))


def full_props(con, b):
    for p, u in UNITS:
        meas(con, b, p, u)
