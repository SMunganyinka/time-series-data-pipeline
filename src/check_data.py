"""Sanity check for the cleaned dataset used by Tasks 2-4."""
import pandas as pd

df = pd.read_csv("data/processed/traffic_for_db.csv", parse_dates=["date_time"])
assert df["date_time"].is_unique, "duplicate timestamps"
assert df.isna().sum().sum() == 0, "missing values"
print(f"OK: {len(df):,} rows, {df.date_time.min()} to {df.date_time.max()}")