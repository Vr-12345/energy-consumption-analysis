# Energy Consumption Data Analysis & Dashboard
**Python · Pandas · SQL (SQLite) · Excel** 

Analysis of hourly household electricity consumption (3 households, Jan 2023 – Dec 2025, ~79k readings) to find usage patterns, trends and changes over time, delivered as an interactive Excel dashboard.

> The dataset is synthetic (generated to behave like smart-meter data, including deliberately messy rows). To use real data, load your CSV into the `raw_readings` table with the same columns (`household_id, reading_ts, kwh, outdoor_temp_c`) and re-run steps 2-4.

## Pipeline
| Step | File | What it does |
|---|---|---|
| 1 | `01_generate_data.py` | Builds hourly data + injects duplicates, nulls, negatives and unit-error spikes; loads to `energy.db` |
| 2 | `02_clean_and_query.sql`, `02_run_sql.py` | SQL data-quality audit, builds `readings_clean`, runs analysis queries (CTEs, joins, window functions) |
| 3 | `03_analysis.py` | Pandas: hourly/weekday patterns, YoY trends, weather regression (HDD/CDD), weather-adjusted trend, step-change and anomaly detection, charts |
| 4 | `04_build_dashboard.py` | Excel dashboard with household dropdown, formula-driven KPIs and 4 native charts |

Run in order: `python 01_generate_data.py && python 02_run_sql.py && python 03_analysis.py && python 04_build_dashboard.py`

## Key findings
- Evening (19:00) is the peak for typical homes; weekends use ~4-5% more per day than weekdays.
- Temperature explains 80-99% of daily variation; winter days use ~2x the electricity of summer days.
- H001 consumption rose 18% (2024) and 14% (2025): overnight load jumped ~1.8 kWh/hr in July 2024, consistent with EV charging.
- Weather-adjusted, H001 is up ~56% (2023→2025), H002 down ~8.5% (efficiency gains), H003 flat.
- Cleaning removed 687 of 79,062 rows (0.9%): 150 duplicates, 473 missing, 39 negative, 25 spikes.

## Resume bullets (what you can say you did)
- Analyzed ~79k hourly electricity readings with Python and Pandas to identify daily, weekly and seasonal usage patterns and a 34% multi-year increase in one household traced to a July 2024 overnight load shift.
- Cleaned and structured the data with SQL (de-duplication, validation rules, window functions for year-over-year change), removing 0.9% invalid records before analysis.
- Built a weather-normalized regression (heating/cooling degree days) to separate weather effects from true changes in usage, and presented results in an interactive Excel dashboard.

## Excel
Import `sql_outputs/*.csv` (or connect to `energy.db` via ODBC) and recreate the four visuals: monthly line, hourly weekday/weekend line, annual bars, seasonal bars, with a household slicer.
