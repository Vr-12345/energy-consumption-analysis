"""Step 1: Generate a realistic hourly household electricity dataset and load it into SQLite.

The data is synthetic (so the project is self-contained), but built to behave like real smart-meter data:
daily peaks, weekday/weekend differences, heating/cooling driven by temperature, a mid-2024 EV
charging step-change in one household, plus deliberately messy rows (missing values, duplicates,
negatives, spikes) so the cleaning step has real work to do.

To use REAL data instead (e.g. a Kaggle / IESO / utility export), skip this script and load your CSV
into the `raw_readings` table with the same column names.
"""
import sqlite3
from pathlib import Path

import numpy as np
import pandas as pd

rng = np.random.default_rng(42)
OUT = Path(__file__).parent
DB = OUT / "energy.db"

households = pd.DataFrame(
    {
        "household_id": ["H001", "H002", "H003"],
        "home_type": ["Detached", "Condo", "Townhouse"],
        "sqft": [2400, 750, 1500],
        "occupants": [4, 1, 3],
        "base_kw": [0.45, 0.15, 0.30],
        "heat_k": [0.055, 0.015, 0.035],   # kWh per degree below 15C
        "cool_k": [0.060, 0.020, 0.040],   # kWh per degree above 22C
    }
)

idx = pd.date_range("2023-01-01 00:00", "2025-12-31 23:00", freq="h")
doy = idx.dayofyear.values
hour = idx.hour.values
dow = idx.dayofweek.values
weekend = dow >= 5

# Toronto-ish temperature: seasonal + daily cycle + noise
temp = (
    9
    + 14 * np.sin(2 * np.pi * (doy - 110) / 365.25)
    + 4 * np.sin(2 * np.pi * (hour - 9) / 24)
    + rng.normal(0, 2.5, len(idx))
)

# Daily load shape: morning and evening peaks, quieter at night
morning = np.exp(-0.5 * ((hour - 7.5) / 1.5) ** 2)
evening = np.exp(-0.5 * ((hour - 19) / 2.2) ** 2)
night_dip = np.where((hour >= 0) & (hour <= 5), -0.3, 0)

frames = []
for _, h in households.iterrows():
    shape = (
        h.base_kw
        + h.base_kw * (0.9 * morning * (0.6 if weekend[0] else 1) + 1.3 * evening)
        + h.base_kw * night_dip
    )
    # weekends: later, flatter morning, more daytime use
    shape = np.where(weekend, h.base_kw * (1 + 0.5 * morning * 0.4 + 1.3 * evening + 0.35 * ((hour > 10) & (hour < 17))), shape)
    heating = h.heat_k * np.clip(15 - temp, 0, None)
    cooling = h.cool_k * np.clip(temp - 22, 0, None)
    kwh = shape + heating + cooling + rng.normal(0, 0.05 * h.base_kw + 0.03, len(idx))

    # H001 gets an EV in July 2024: overnight charging 23:00-03:00
    if h.household_id == "H001":
        ev_on = (idx >= "2024-07-01") & ((hour >= 23) | (hour <= 3))
        kwh = kwh + np.where(ev_on, 1.8, 0)

    # H002 slow efficiency gain (LED/appliance upgrades): ~ -8% across 3 years
    if h.household_id == "H002":
        kwh = kwh * np.linspace(1.0, 0.92, len(idx))

    kwh = np.clip(kwh, 0.02, None)
    frames.append(
        pd.DataFrame(
            {
                "household_id": h.household_id,
                "reading_ts": idx.strftime("%Y-%m-%d %H:%M:%S"),
                "kwh": kwh.round(3),
                "outdoor_temp_c": temp.round(1),
            }
        )
    )

raw = pd.concat(frames, ignore_index=True)

# ---- Inject realistic mess -------------------------------------------------
n = len(raw)
# 1) missing readings (meter dropouts)
raw.loc[rng.choice(n, int(n * 0.006), replace=False), "kwh"] = np.nan
# 2) negative values (sensor / sign errors)
raw.loc[rng.choice(n, 40, replace=False), "kwh"] = -raw["kwh"].abs()
# 3) spikes (unit error, e.g. Wh recorded as kWh)
spike_idx = rng.choice(n, 25, replace=False)
raw.loc[spike_idx, "kwh"] = raw.loc[spike_idx, "kwh"].abs() * 1000
# 4) duplicate rows
raw = pd.concat([raw, raw.sample(150, random_state=1)], ignore_index=True)
# 5) missing temperature
raw.loc[rng.choice(len(raw), 300, replace=False), "outdoor_temp_c"] = np.nan
raw = raw.sample(frac=1, random_state=7).reset_index(drop=True)  # shuffle like a real export

# ---- Load into SQLite ------------------------------------------------------
if DB.exists():
    DB.unlink()
con = sqlite3.connect(DB)
households[["household_id", "home_type", "sqft", "occupants"]].to_sql("households", con, index=False)
raw.to_sql("raw_readings", con, index=False)
con.close()

raw.to_csv(OUT / "raw_readings.csv", index=False)
print(f"Wrote {len(raw):,} raw rows to {DB.name} (table raw_readings) and raw_readings.csv")
