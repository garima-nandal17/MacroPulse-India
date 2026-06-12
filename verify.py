"""verify.py — confirm Day 1 data landed in MySQL."""
import os
from dotenv import load_dotenv
import mysql.connector

load_dotenv()

conn = mysql.connector.connect(
    host=os.environ.get("DB_HOST", "localhost"),
    port=int(os.environ.get("DB_PORT", "3306")),
    user=os.environ.get("DB_USER"),
    password=os.environ.get("DB_PASSWORD"),
    database=os.environ.get("DB_NAME", "macropulse_india"),
)

cur = conn.cursor()
cur.execute(
    "SELECT date, indicator, value, pct_change "
    "FROM daily_indicators ORDER BY date DESC;"
)
rows = cur.fetchall()

print(f"\nRows in daily_indicators: {len(rows)}")
print("-" * 56)
print(f"{'date':<12} {'indicator':<10} {'value':>12} {'pct_change':>10}")
print("-" * 56)
for d, indicator, value, pct in rows:
    pct_str = f"{pct:+.2f}%" if pct is not None else "NULL"
    print(f"{str(d):<12} {indicator:<10} {value:>12.4f} {pct_str:>10}")
print("-" * 56)

cur.close()
conn.close()