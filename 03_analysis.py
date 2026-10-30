"""Step 3: Pandas analysis of the cleaned data (patterns, trends, weather sensitivity, anomalies).

Reads the `readings_clean` table built by the SQL step, saves tidy CSVs for the dashboard,
PNG charts for the README, and a findings.json with the headline numbers.
"""
import json
import sqlite3
from pathlib import Path

import matplotlib
matplotlib.use("Agg")
import matplotlib.pyplot as plt
import numpy as np
import pandas as pd

HERE = Path(__file__).parent
OUT = HERE / "analysis_outputs"
CHARTS = HERE / "charts"
OUT.mkdir(exist_ok=True)
CHARTS.mkdir(exist_ok=True)

con = sqlite3.connect(HERE / "energy.db")
df = pd.read_sql("SELECT * FROM readings_clean", con, parse_dates=["reading_ts", "reading_date"])
hh = pd.read_sql("SELECT * FROM households", con)
con.close()

HOUSES = sorted(df.household_id.unique())
COLORS = {"H001": "#1f4e79", "H002": "#c0504d", "H003": "#4f8a3c"}
findings = {}

# ---------------------------------------------------------------- 1. Daily table
daily = (
    df.groupby(["household_id", "reading_date"])
    .agg(daily_kwh=("kwh", "sum"), hours=("kwh", "size"), avg_temp=("outdoor_temp_c", "mean"))
    .reset_index()
)
# drop days with large gaps so partial days don't look like low usage
daily = daily[daily.hours >= 20].copy()
daily["daily_kwh"] = daily.daily_kwh * 24 / daily.hours  # scale days with a few missing hours
daily["year"] = daily.reading_date.dt.year
daily["month"] = daily.reading_date.dt.month
daily["hdd"] = (15 - daily.avg_temp).clip(lower=0)   # heating degree days (base 15C)
daily["cdd"] = (daily.avg_temp - 22).clip(lower=0)   # cooling degree days (base 22C)

# ---------------------------------------------------------------- 2. Daily patterns
hourly = df.groupby(["household_id", "day_type", "hour"]).kwh.mean().reset_index()
prof = hourly.pivot_table(index="hour", columns=["household_id", "day_type"], values="kwh")
prof.columns = [f"{h}_{d}" for h, d in prof.columns]
prof.reset_index().to_csv(OUT / "hourly_profile_wide.csv", index=False)

findings["peak_hour"] = {}
for h in HOUSES:
    wk = hourly[(hourly.household_id == h) & (hourly.day_type == "Weekday")].set_index("hour").kwh
    we = hourly[(hourly.household_id == h) & (hourly.day_type == "Weekend")].set_index("hour").kwh
    findings["peak_hour"][h] = {
        "weekday_peak_hour": int(wk.idxmax()),
        "weekend_peak_hour": int(we.idxmax()),
        "weekend_vs_weekday_daily_pct": round(100 * (we.sum() / wk.sum() - 1), 1),
    }

# ---------------------------------------------------------------- 3. Monthly trend + YoY
monthly = daily.groupby(["household_id", "year", "month"]).daily_kwh.sum().reset_index(name="kwh")
monthly["year_month"] = monthly.year.astype(str) + "-" + monthly.month.astype(str).str.zfill(2)
monthly = monthly.sort_values(["household_id", "year", "month"])
monthly["yoy_pct"] = monthly.groupby(["household_id", "month"]).kwh.pct_change() * 100
monthly["rolling_12m"] = monthly.groupby("household_id").kwh.transform(lambda s: s.rolling(12).sum())
monthly.to_csv(OUT / "monthly_trend.csv", index=False)

yearly = daily.groupby(["household_id", "year"]).daily_kwh.sum().reset_index(name="kwh")
yearly["yoy_pct"] = yearly.groupby("household_id").kwh.pct_change() * 100
yearly.to_csv(OUT / "yearly.csv", index=False)
findings["yoy_2025_vs_2023_pct"] = {
    h: round(100 * (yearly[(yearly.household_id == h) & (yearly.year == 2025)].kwh.iloc[0]
                    / yearly[(yearly.household_id == h) & (yearly.year == 2023)].kwh.iloc[0] - 1), 1)
    for h in HOUSES
}

# ---------------------------------------------------------------- 4. Weather sensitivity & weather-adjusted trend
rows, adj_rows = [], []
for h in HOUSES:
    d = daily[daily.household_id == h].dropna(subset=["avg_temp"])
    X = np.column_stack([np.ones(len(d)), d.hdd, d.cdd])
    beta, *_ = np.linalg.lstsq(X, d.daily_kwh.values, rcond=None)
    pred = X @ beta
    r2 = 1 - ((d.daily_kwh - pred) ** 2).sum() / ((d.daily_kwh - d.daily_kwh.mean()) ** 2).sum()
    rows.append({"household_id": h, "base_kwh_per_day": beta[0], "kwh_per_heating_degree_day": beta[1],
                 "kwh_per_cooling_degree_day": beta[2], "r_squared": r2,
                 "corr_with_temp": d.daily_kwh.corr(d.avg_temp)})
    # weather-adjusted = baseline + unexplained residual => underlying usage with weather removed
    tmp = d.assign(adjusted=beta[0] + (d.daily_kwh - pred))
    adj_rows.append(tmp.groupby(["household_id", "year"]).adjusted.mean().reset_index())
sens = pd.DataFrame(rows).round(3)
sens.to_csv(OUT / "weather_sensitivity.csv", index=False)
adj = pd.concat(adj_rows).rename(columns={"adjusted": "weather_adjusted_daily_kwh"}).round(2)
adj.to_csv(OUT / "weather_adjusted_yearly.csv", index=False)
findings["weather_sensitivity"] = sens.set_index("household_id")[["kwh_per_heating_degree_day", "r_squared"]].to_dict("index")
findings["weather_adjusted_change_2023_to_2025_pct"] = {
    h: round(100 * (adj[(adj.household_id == h) & (adj.year == 2025)].weather_adjusted_daily_kwh.iloc[0]
                    / adj[(adj.household_id == h) & (adj.year == 2023)].weather_adjusted_daily_kwh.iloc[0] - 1), 1)
    for h in HOUSES
}

# ---------------------------------------------------------------- 5. Structural change (overnight load step)
night = df[(df.hour >= 23) | (df.hour <= 3)].copy()
night_m = night.groupby(["household_id", "year_month"]).kwh.mean().reset_index()
step = {}
for h in HOUSES:
    s = night_m[night_m.household_id == h].set_index("year_month").kwh
    jump = s.diff()
    step[h] = {"largest_monthly_jump_month": jump.idxmax(), "jump_kwh_per_hour": round(float(jump.max()), 2)}
findings["overnight_step_change"] = step

# ---------------------------------------------------------------- 6. Anomalies (days unusual for their time of year)
daily["expected"] = daily.groupby(["household_id", "month"]).daily_kwh.transform("mean")
daily["resid"] = daily.daily_kwh - daily.expected
# also remove the weather effect so cold snaps are not flagged as "anomalies"
daily["z"] = daily.groupby(["household_id", "month"]).resid.transform(lambda s: (s - s.mean()) / s.std())
anom = daily[daily.z.abs() > 3].sort_values("z", key=abs, ascending=False)
anom[["household_id", "reading_date", "daily_kwh", "expected", "avg_temp", "z"]].round(2).head(25).to_csv(
    OUT / "anomaly_days.csv", index=False)
findings["anomaly_days_flagged"] = int(len(anom))

# ---------------------------------------------------------------- 7. Charts (PNG, for the README)
plt.rcParams.update({"font.family": "DejaVu Sans", "axes.spines.top": False, "axes.spines.right": False})

fig, ax = plt.subplots(figsize=(9, 4))
for h in HOUSES:
    m = monthly[monthly.household_id == h]
    ax.plot(pd.to_datetime(m.year_month + "-01"), m.kwh, label=h, color=COLORS[h], lw=2)
ax.set_title("Monthly electricity use by household", loc="left", fontweight="bold")
ax.set_ylabel("kWh per month"); ax.legend(frameon=False)
fig.tight_layout(); fig.savefig(CHARTS / "monthly_trend.png", dpi=150); plt.close(fig)

fig, axes = plt.subplots(1, 3, figsize=(11, 3.4), sharey=False)
for ax, h in zip(axes, HOUSES):
    for dt, ls in [("Weekday", "-"), ("Weekend", "--")]:
        s = hourly[(hourly.household_id == h) & (hourly.day_type == dt)]
        ax.plot(s.hour, s.kwh, ls, color=COLORS[h], label=dt, lw=2)
    ax.set_title(h, loc="left", fontweight="bold"); ax.set_xlabel("Hour of day"); ax.legend(frameon=False)
axes[0].set_ylabel("Avg kWh per hour")
fig.tight_layout(); fig.savefig(CHARTS / "hourly_profile.png", dpi=150); plt.close(fig)

fig, ax = plt.subplots(figsize=(6.5, 4.2))
d = daily[daily.household_id == "H003"]
ax.scatter(d.avg_temp, d.daily_kwh, s=8, alpha=.4, color=COLORS["H003"])
ax.set_title("H003: daily use vs outdoor temperature", loc="left", fontweight="bold")
ax.set_xlabel("Avg outdoor temp (°C)"); ax.set_ylabel("kWh per day")
fig.tight_layout(); fig.savefig(CHARTS / "temp_vs_usage.png", dpi=150); plt.close(fig)

(OUT / "findings.json").write_text(json.dumps(findings, indent=2, default=str))
print(json.dumps(findings, indent=2, default=str))
print("\nWeather sensitivity:\n", sens.to_string(index=False))
print("\nWeather-adjusted daily kWh by year:\n", adj.pivot(index="year", columns="household_id", values="weather_adjusted_daily_kwh"))
print("\nTop anomalies:\n", pd.read_csv(OUT / "anomaly_days.csv").head(8).to_string(index=False))
