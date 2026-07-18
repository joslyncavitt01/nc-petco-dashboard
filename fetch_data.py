#!/usr/bin/env python3
"""Pulls NC Adoption Center metrics from BigQuery and writes data/metrics.json.

Data source: apa-data-410213.nc_shelterluv (live ShelterLuv sync) and
apa-data-410213.betterImpact (volunteer hours). See project memory
project_petco_love_stewardship.md for grant context.

Year 1 / Year 2 goal framing confirmed by Petco Love (Mary Ann Magana,
7/17/26): calendar year, separate annual goals, NOT cumulative.
  Year 1 = calendar year 2025, goal 500-750 adoptions
  Year 2 = calendar year 2026, goal 750-1,000 adoptions
"""

import json
import datetime
from google.cloud import bigquery

client = bigquery.Client(project="apa-data-410213")

def q(sql):
    return [dict(row) for row in client.query(sql).result()]

now = datetime.datetime.now(datetime.timezone.utc)

# --- Adoptions: totals + monthly trend ---------------------------------
adoptions_by_month = q("""
    SELECT
      FORMAT_DATE('%Y-%m', DATE(o.outcomeDate)) AS month,
      COUNT(*) AS total,
      COUNTIF(a.species = 'Cat') AS cats,
      COUNTIF(a.species = 'Dog') AS dogs
    FROM `apa-data-410213.nc_shelterluv.Outcomes` o
    JOIN `apa-data-410213.nc_shelterluv.Animals` a
      ON o.animalInternalID = a.animalInternalID
    WHERE o.outcomeType = 'Outcome.Adoption'
    GROUP BY month
    ORDER BY month
""")

adoptions_by_cal_year = q("""
    SELECT
      EXTRACT(YEAR FROM o.outcomeDate) AS cal_year,
      COUNT(*) AS total,
      COUNTIF(a.species = 'Cat') AS cats,
      COUNTIF(a.species = 'Dog') AS dogs
    FROM `apa-data-410213.nc_shelterluv.Outcomes` o
    JOIN `apa-data-410213.nc_shelterluv.Animals` a
      ON o.animalInternalID = a.animalInternalID
    WHERE o.outcomeType = 'Outcome.Adoption'
    GROUP BY cal_year
    ORDER BY cal_year
""")

totals = q("""
    SELECT
      COUNT(*) AS total,
      COUNTIF(a.species = 'Cat') AS cats,
      COUNTIF(a.species = 'Dog') AS dogs
    FROM `apa-data-410213.nc_shelterluv.Outcomes` o
    JOIN `apa-data-410213.nc_shelterluv.Animals` a
      ON o.animalInternalID = a.animalInternalID
    WHERE o.outcomeType = 'Outcome.Adoption'
""")[0]

# --- Foster program -------------------------------------------------------
foster_totals = q("""
    SELECT
      COUNT(*) AS total_placements,
      COUNT(DISTINCT personInternalID) AS unique_families
    FROM `apa-data-410213.nc_shelterluv.Outcomes`
    WHERE outcomeType = 'Outcome.Foster'
""")[0]

foster_to_adopt = q("""
    SELECT
      COUNT(*) AS total_adoptions,
      COUNTIF(outcomeSubType LIKE '%(Foster)%') AS foster_to_adopt
    FROM `apa-data-410213.nc_shelterluv.Outcomes`
    WHERE outcomeType = 'Outcome.Adoption'
""")[0]

foster_stay_length = q("""
    WITH events AS (
      SELECT animalInternalID, DATE(outcomeDate) AS event_date, 'foster_out' AS event_type
      FROM `apa-data-410213.nc_shelterluv.Outcomes`
      WHERE outcomeType = 'Outcome.Foster'
      UNION ALL
      SELECT animalInternalID, DATE(intakeDate) AS event_date, 'foster_return' AS event_type
      FROM `apa-data-410213.nc_shelterluv.Intakes`
      WHERE intakeType = 'Intake.FosterReturn'
      UNION ALL
      SELECT animalInternalID, DATE(outcomeDate) AS event_date, 'adoption' AS event_type
      FROM `apa-data-410213.nc_shelterluv.Outcomes`
      WHERE outcomeType = 'Outcome.Adoption'
    ),
    ordered AS (
      SELECT *,
        LEAD(event_date) OVER (PARTITION BY animalInternalID ORDER BY event_date) AS next_date,
        LEAD(event_type) OVER (PARTITION BY animalInternalID ORDER BY event_date) AS next_type
      FROM events
    )
    SELECT ROUND(AVG(DATE_DIFF(next_date, event_date, DAY)), 1) AS avg_days
    FROM ordered
    WHERE event_type = 'foster_out' AND next_type IN ('foster_return', 'adoption')
      AND DATE_DIFF(next_date, event_date, DAY) BETWEEN 0 AND 365
""")[0]

# --- Volunteers (NC only, approved entries) ------------------------------
volunteers = q("""
    SELECT
      ROUND(SUM(t.hoursWorked), 1) AS total_hours,
      COUNT(DISTINCT t.userID) AS unique_volunteers,
      COUNT(*) AS total_shifts
    FROM `apa-data-410213.betterImpact.TimelogEntries` t
    JOIN `apa-data-410213.betterImpact.Users` u ON t.userID = u.userID
    WHERE u.state = 'North Carolina' AND t.approved = true
""")[0]

# --- Current snapshot (live custody counts) ------------------------------
snapshot_rows = q("""
    SELECT species, status, COUNT(*) AS n
    FROM `apa-data-410213.nc_shelterluv.Animals`
    WHERE deletedFromSL IS NOT TRUE
      AND status IN ('Available (Shelter)', 'Available (Foster)', 'Unavailable - (Foster)')
    GROUP BY species, status
""")

snapshot = {"cats_at_center": 0, "dogs_at_center": 0, "cats_in_foster": 0, "dogs_in_foster": 0}
for r in snapshot_rows:
    species = r["species"].lower()
    if r["status"] == "Available (Shelter)":
        snapshot[f"{species}s_at_center"] = snapshot.get(f"{species}s_at_center", 0) + r["n"]
    else:
        snapshot[f"{species}s_in_foster"] = snapshot.get(f"{species}s_in_foster", 0) + r["n"]
snapshot["total_in_custody"] = sum(snapshot.values())

# --- Contract goals: Year 1 = CY2025, Year 2 = CY2026 --------------------
by_year = {row["cal_year"]: row for row in adoptions_by_cal_year}
year1 = by_year.get(2025, {"total": 0, "cats": 0, "dogs": 0})
year2 = by_year.get(2026, {"total": 0, "cats": 0, "dogs": 0})

GOALS = {
    "year1": {"label": "Year 1 (Calendar Year 2025)", "min": 500, "max": 750, "closed": True},
    "year2": {"label": "Year 2 (Calendar Year 2026)", "min": 750, "max": 1000, "closed": False},
}

output = {
    "generated_at": now.isoformat(),
    "adoptions": {
        "total": totals["total"],
        "cats": totals["cats"],
        "dogs": totals["dogs"],
        "by_month": adoptions_by_month,
    },
    "foster": {
        "unique_families": foster_totals["unique_families"],
        "total_placements": foster_totals["total_placements"],
        "avg_days_per_stay": foster_stay_length["avg_days"],
        "foster_to_adopt_pct": round(
            100 * foster_to_adopt["foster_to_adopt"] / foster_to_adopt["total_adoptions"], 1
        ) if foster_to_adopt["total_adoptions"] else 0,
    },
    "volunteers": {
        "total_hours": volunteers["total_hours"],
        "unique_volunteers": volunteers["unique_volunteers"],
        "total_shifts": volunteers["total_shifts"],
    },
    "snapshot": snapshot,
    "goals": {
        "year1": {
            **GOALS["year1"],
            "actual": year1["total"],
            "cats": year1["cats"],
            "dogs": year1["dogs"],
            "pct_of_min": round(100 * year1["total"] / GOALS["year1"]["min"], 1),
        },
        "year2": {
            **GOALS["year2"],
            "actual": year2["total"],
            "cats": year2["cats"],
            "dogs": year2["dogs"],
            "pct_of_min": round(100 * year2["total"] / GOALS["year2"]["min"], 1),
        },
    },
}

with open("data/metrics.json", "w") as f:
    json.dump(output, f, indent=2)

print(f"Wrote data/metrics.json at {now.isoformat()}Z")
print(f"  Total adoptions: {totals['total']} ({totals['cats']} cats, {totals['dogs']} dogs)")
print(f"  Year 1 (CY2025): {year1['total']} / {GOALS['year1']['min']}-{GOALS['year1']['max']}")
print(f"  Year 2 (CY2026): {year2['total']} / {GOALS['year2']['min']}-{GOALS['year2']['max']}")
