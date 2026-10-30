"""Step 2: Run 02_clean_and_query.sql against energy.db, print results, export each to CSV."""
import re
import sqlite3
from pathlib import Path

import pandas as pd

HERE = Path(__file__).parent
OUT = HERE / "sql_outputs"
OUT.mkdir(exist_ok=True)

sql_text = (HERE / "02_clean_and_query.sql").read_text()
# split on "-- NAME: xxx" markers
parts = re.split(r"^-- NAME:\s*(\w+)\s*$", sql_text, flags=re.M)
blocks = list(zip(parts[1::2], parts[2::2]))

con = sqlite3.connect(HERE / "energy.db")
pd.set_option("display.width", 140)

for name, body in blocks:
    statements = [s.strip() for s in body.split(";") if s.strip() and not all(l.strip().startswith("--") or not l.strip() for l in s.splitlines())]
    result = None
    for stmt in statements:
        cur = con.execute(stmt)
        if cur.description:  # a SELECT
            result = pd.DataFrame(cur.fetchall(), columns=[d[0] for d in cur.description])
    con.commit()
    if result is not None:
        result.to_csv(OUT / f"{name}.csv", index=False)
        print(f"\n=== {name} ({len(result)} rows) ===")
        print(result.head(12).to_string(index=False))
    else:
        print(f"\n=== {name}: executed ===")

con.close()
