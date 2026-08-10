#!/usr/bin/env python3
"""Pulls NC Adoption Center metrics from BigQuery and writes data/metrics.json.

Data source: apa-data-410213.nc_shelterluv (live ShelterLuv sync) and
apa-data-410213.betterImpact (volunteer hours). See project memory
project_petco_love_stewardship.md for grant context.

Year 1 / Year 2 goal framing confirmed by Petco Love (Mary Ann Magana,
7/17/26): calendar year, separate annual goals, NOT cumulative.
  Year 1 = calendar year 2025, goal 500-750 adoptions
  Year 2 = calendar year 2026, goal 750-1,000 adoptions

Pedigree Foundation D2A (Direct to Adopt) section tracks the 2026 grant
goals from the March 2026 proposal: 180 pets transported TX->NC in 2026,
100 local NC shelter transfers-in, foster caregivers 5->15. D2A-tagged pets
are identified by the 'D2A' AnimalAttributes tag.

IMPORTANT: intakeSubType ('HNCSPAC - Space', 'Transport Held at APATH') is
NOT a reliable TX-vs-NC signal -- both labels are used for transfers from
Texas source shelters AND from local NC shelters (e.g. Charlotte-Mecklenburg
Animal Care & Control, Catawba County). True origin is derived from
AnimalPreviousIds.issuingShelter, backfilled by the dominant issuingShelter
seen for that record's partnerInternalID when the animal's own previous-ID
record is blank. A small residual is still unclassified ('UNKNOWN' origin).
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

# Drop the current (in-progress) month from the trend series so it doesn't
# read as a decline when it's really just a partial month. Recomputed fresh
# on every run, so the cutoff always tracks "today" automatically.
current_month = now.strftime("%Y-%m")
adoptions_by_month = [m for m in adoptions_by_month if m["month"] < current_month]

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

# --- Pedigree D2A: transfer-in origin classification (TX vs NC vs unknown) -
# See module docstring: issuingShelter is looked up directly per-animal, then
# backfilled per-partner (dominant issuingShelter for that partnerInternalID)
# for animals with no previous-ID record of their own.
TX_SHELTERS = """(
  'Austin Pets Alive, Inc.', 'Bryan Animal Center', 'Bastrop County Animal Services',
  'Bastrop Cats Anonymous TNR Society - Bastrop CATS Inc', 'City of Lufkin Animal Services',
  'Hill Country Humane Society', 'Kerrville Pets Alive!'
)"""
NC_SHELTERS = """(
  'Charlotte Mecklenburg Animal Care & Control', 'Catawba County Animal Control',
  'Catawba County Animal Shelter'
)"""

ORIGIN_CTE = f"""
    WITH prev_id_dedup AS (
      -- AnimalPreviousIds has up to one row per idType per animal (Shelterluv,
      -- PetPoint, Other, Shelter Buddy). Joining on animalInternalID alone
      -- fans out and double/triple-counts intake rows, so collapse to a
      -- single best row per animal first: prefer a populated issuingShelter,
      -- then prefer idType = 'Shelterluv' as the most reliable source.
      SELECT animalInternalID, issuingShelter
      FROM (
        SELECT animalInternalID, issuingShelter,
          ROW_NUMBER() OVER (
            PARTITION BY animalInternalID
            ORDER BY (issuingShelter IS NOT NULL AND issuingShelter != '') DESC,
                     (idType = 'Shelterluv') DESC,
                     issuingShelter
          ) AS rn
        FROM `apa-data-410213.nc_shelterluv.AnimalPreviousIds`
      )
      WHERE rn = 1
    ),
    direct AS (
      SELECT i.intakeID, i.animalInternalID, i.partnerInternalID, i.intakeDate, a.species,
        CASE
          WHEN p.issuingShelter IN {TX_SHELTERS} THEN 'TX'
          WHEN p.issuingShelter IN {NC_SHELTERS} THEN 'NC'
          WHEN p.issuingShelter IS NOT NULL AND p.issuingShelter != '' THEN 'OTHER'
          ELSE NULL
        END AS direct_origin
      FROM `apa-data-410213.nc_shelterluv.Intakes` i
      LEFT JOIN prev_id_dedup p
        ON i.animalInternalID = p.animalInternalID
      LEFT JOIN `apa-data-410213.nc_shelterluv.Animals` a
        ON i.animalInternalID = a.animalInternalID
      WHERE i.intakeType = 'Intake.Transfer'
    ),
    partner_mode AS (
      SELECT partnerInternalID, direct_origin AS mode_origin
      FROM (
        SELECT partnerInternalID, direct_origin,
          ROW_NUMBER() OVER (PARTITION BY partnerInternalID ORDER BY COUNT(*) DESC) AS rn
        FROM direct
        WHERE direct_origin IS NOT NULL AND partnerInternalID IS NOT NULL AND partnerInternalID != ''
        GROUP BY 1, 2
      )
      WHERE rn = 1
    ),
    classified AS (
      SELECT d.intakeID, d.animalInternalID, d.intakeDate, d.species,
        COALESCE(d.direct_origin, pm.mode_origin, 'UNKNOWN') AS origin
      FROM direct d
      LEFT JOIN partner_mode pm ON d.partnerInternalID = pm.partnerInternalID
    ),
    -- Grant KPI language is "transport ... AND place them in adoptive homes",
    -- so transport-in alone isn't the metric -- must also have reached an
    -- Outcome.Adoption at some point (any date, not just within the same
    -- calendar year as the transport).
    classified_with_adoption AS (
      SELECT c.*, ad.animalInternalID IS NOT NULL AS was_adopted
      FROM classified c
      LEFT JOIN (
        SELECT DISTINCT animalInternalID FROM `apa-data-410213.nc_shelterluv.Outcomes`
        WHERE outcomeType = 'Outcome.Adoption'
      ) ad ON c.animalInternalID = ad.animalInternalID
    )
"""

transport_by_month = q(f"""
    {ORIGIN_CTE}
    SELECT
      FORMAT_DATE('%Y-%m', DATE(intakeDate)) AS month,
      COUNT(*) AS total,
      COUNTIF(species = 'Cat') AS cats,
      COUNTIF(species = 'Dog') AS dogs
    FROM classified WHERE origin = 'TX'
    GROUP BY month ORDER BY month
""")
transport_by_month = [m for m in transport_by_month if m["month"] < current_month]

transport_totals = q(f"""
    {ORIGIN_CTE}
    SELECT
      COUNTIF(origin = 'TX') AS all_time,
      COUNTIF(origin = 'TX' AND species = 'Cat') AS all_time_cats,
      COUNTIF(origin = 'TX' AND species = 'Dog') AS all_time_dogs,
      COUNTIF(origin = 'TX' AND EXTRACT(YEAR FROM intakeDate) = 2026) AS cy2026,
      COUNTIF(origin = 'TX' AND species = 'Cat' AND EXTRACT(YEAR FROM intakeDate) = 2026) AS cy2026_cats,
      COUNTIF(origin = 'TX' AND species = 'Dog' AND EXTRACT(YEAR FROM intakeDate) = 2026) AS cy2026_dogs
    FROM classified
""")[0]

# The grant KPI itself: TX-transported pets placed in adoptive homes.
# Scoped by transport (intake) year, not adoption date, since the goal is
# framed as a 2026 transport-capacity target -- but only counts pets whose
# adoption has actually happened as of this run.
transport_adopted_totals = q(f"""
    {ORIGIN_CTE}
    SELECT
      COUNTIF(origin = 'TX' AND EXTRACT(YEAR FROM intakeDate) = 2026 AND was_adopted) AS cy2026_adopted,
      COUNTIF(origin = 'TX' AND EXTRACT(YEAR FROM intakeDate) = 2026 AND was_adopted AND species = 'Cat') AS cy2026_adopted_cats,
      COUNTIF(origin = 'TX' AND EXTRACT(YEAR FROM intakeDate) = 2026 AND was_adopted AND species = 'Dog') AS cy2026_adopted_dogs,
      COUNTIF(origin = 'TX' AND EXTRACT(YEAR FROM intakeDate) = 2026 AND NOT was_adopted) AS cy2026_not_yet_adopted
    FROM classified_with_adoption
""")[0]

transport_adopted_by_month = q(f"""
    {ORIGIN_CTE}
    SELECT
      FORMAT_DATE('%Y-%m', DATE(intakeDate)) AS month,
      COUNT(*) AS total,
      COUNTIF(species = 'Cat') AS cats,
      COUNTIF(species = 'Dog') AS dogs
    FROM classified_with_adoption WHERE origin = 'TX' AND was_adopted
    GROUP BY month ORDER BY month
""")
transport_adopted_by_month = [m for m in transport_adopted_by_month if m["month"] < current_month]

# --- Pedigree D2A: D2A-tagged pets and their outcomes ----------------------
d2a_tagged = q("""
    SELECT
      COUNT(DISTINCT att.animalInternalID) AS total,
      COUNT(DISTINCT IF(a.species = 'Cat', att.animalInternalID, NULL)) AS total_cats,
      COUNT(DISTINCT IF(a.species = 'Dog', att.animalInternalID, NULL)) AS total_dogs
    FROM `apa-data-410213.nc_shelterluv.AnimalAttributes` att
    LEFT JOIN `apa-data-410213.nc_shelterluv.Animals` a ON att.animalInternalID = a.animalInternalID
    WHERE att.attributeName = 'D2A'
""")[0]

d2a_outcomes = q("""
    WITH d2a AS (
      SELECT DISTINCT animalInternalID
      FROM `apa-data-410213.nc_shelterluv.AnimalAttributes`
      WHERE attributeName = 'D2A'
    )
    SELECT
      COUNTIF(o.outcomeType = 'Outcome.Adoption' AND o.outcomeSubType NOT LIKE '%(Foster)%') AS direct_adoptions,
      COUNTIF(o.outcomeType = 'Outcome.Adoption' AND o.outcomeSubType NOT LIKE '%(Foster)%' AND a.species = 'Cat') AS direct_adoptions_cats,
      COUNTIF(o.outcomeType = 'Outcome.Adoption' AND o.outcomeSubType NOT LIKE '%(Foster)%' AND a.species = 'Dog') AS direct_adoptions_dogs,
      COUNTIF(o.outcomeType = 'Outcome.Adoption' AND o.outcomeSubType LIKE '%(Foster)%') AS foster_to_adopt,
      COUNTIF(o.outcomeType = 'Outcome.Adoption' AND o.outcomeSubType LIKE '%(Foster)%' AND a.species = 'Cat') AS foster_to_adopt_cats,
      COUNTIF(o.outcomeType = 'Outcome.Adoption' AND o.outcomeSubType LIKE '%(Foster)%' AND a.species = 'Dog') AS foster_to_adopt_dogs,
      COUNT(DISTINCT o.animalInternalID) AS with_any_outcome
    FROM d2a
    JOIN `apa-data-410213.nc_shelterluv.Outcomes` o ON d2a.animalInternalID = o.animalInternalID
    LEFT JOIN `apa-data-410213.nc_shelterluv.Animals` a ON d2a.animalInternalID = a.animalInternalID
""")[0]

# --- Pedigree D2A: local NC shelter transfers-in ---------------------------
# Distinct from TX transport-ins above; goal is separate relationship-building
# with in-state NC shelters (e.g. Charlotte-Mecklenburg, Catawba County).
local_transfers = q(f"""
    {ORIGIN_CTE}
    SELECT
      COUNTIF(origin = 'NC') AS all_time,
      COUNTIF(origin = 'NC' AND species = 'Cat') AS all_time_cats,
      COUNTIF(origin = 'NC' AND species = 'Dog') AS all_time_dogs,
      COUNTIF(origin = 'NC' AND EXTRACT(YEAR FROM intakeDate) = 2026) AS cy2026,
      COUNTIF(origin = 'NC' AND species = 'Cat' AND EXTRACT(YEAR FROM intakeDate) = 2026) AS cy2026_cats,
      COUNTIF(origin = 'NC' AND species = 'Dog' AND EXTRACT(YEAR FROM intakeDate) = 2026) AS cy2026_dogs
    FROM classified
""")[0]

local_transfers_by_month = q(f"""
    {ORIGIN_CTE}
    SELECT
      FORMAT_DATE('%Y-%m', DATE(intakeDate)) AS month,
      COUNT(*) AS total,
      COUNTIF(species = 'Cat') AS cats,
      COUNTIF(species = 'Dog') AS dogs
    FROM classified WHERE origin = 'NC'
    GROUP BY month ORDER BY month
""")
local_transfers_by_month = [m for m in local_transfers_by_month if m["month"] < current_month]

unclassified_transfers = q(f"""
    {ORIGIN_CTE}
    SELECT COUNTIF(origin = 'UNKNOWN') AS all_time
    FROM classified
""")[0]

# --- Pedigree D2A: active foster caregivers ---------------------------------
# Grant-goal definition (confirmed 8/10/26): "active" = fostered 2+ times in
# calendar year 2026, not a point-in-time count of who currently has an
# animal. A point-in-time count was tried first but undercounted -- 6 of the
# animals currently showing an in-foster status in ShelterLuv have zero
# Intake/Outcome records at all (a sync gap, not a query bug), so there was
# no way to attribute them to a caregiver. Repeat-placement counting sidesteps
# that gap entirely since it doesn't depend on current custody status.
foster_caregivers_by_placements = q("""
    SELECT personInternalID, COUNT(*) AS placements_2026
    FROM `apa-data-410213.nc_shelterluv.Outcomes`
    WHERE outcomeType = 'Outcome.Foster' AND EXTRACT(YEAR FROM outcomeDate) = 2026
    GROUP BY personInternalID
""")

foster_caregivers_active = {
    "active_2026": sum(1 for r in foster_caregivers_by_placements if r["placements_2026"] >= 2),
    "one_time_2026": sum(1 for r in foster_caregivers_by_placements if r["placements_2026"] == 1),
}

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
    "pedigree": {
        "transport_in": {
            "all_time": transport_totals["all_time"],
            "all_time_cats": transport_totals["all_time_cats"],
            "all_time_dogs": transport_totals["all_time_dogs"],
            "cy2026": transport_totals["cy2026"],
            "cy2026_cats": transport_totals["cy2026_cats"],
            "cy2026_dogs": transport_totals["cy2026_dogs"],
            "by_month": transport_by_month,
            "cy2026_adopted": transport_adopted_totals["cy2026_adopted"],
            "cy2026_adopted_cats": transport_adopted_totals["cy2026_adopted_cats"],
            "cy2026_adopted_dogs": transport_adopted_totals["cy2026_adopted_dogs"],
            "cy2026_not_yet_adopted": transport_adopted_totals["cy2026_not_yet_adopted"],
            "by_month_adopted": transport_adopted_by_month,
            "goal_2026_min": 180,
        },
        "d2a": {
            "tagged_total": d2a_tagged["total"],
            "tagged_total_cats": d2a_tagged["total_cats"],
            "tagged_total_dogs": d2a_tagged["total_dogs"],
            "direct_adoptions": d2a_outcomes["direct_adoptions"],
            "direct_adoptions_cats": d2a_outcomes["direct_adoptions_cats"],
            "direct_adoptions_dogs": d2a_outcomes["direct_adoptions_dogs"],
            "foster_to_adopt": d2a_outcomes["foster_to_adopt"],
            "foster_to_adopt_cats": d2a_outcomes["foster_to_adopt_cats"],
            "foster_to_adopt_dogs": d2a_outcomes["foster_to_adopt_dogs"],
            "with_any_outcome": d2a_outcomes["with_any_outcome"],
        },
        "local_transfers_in": {
            "all_time": local_transfers["all_time"],
            "all_time_cats": local_transfers["all_time_cats"],
            "all_time_dogs": local_transfers["all_time_dogs"],
            "cy2026": local_transfers["cy2026"],
            "cy2026_cats": local_transfers["cy2026_cats"],
            "cy2026_dogs": local_transfers["cy2026_dogs"],
            "by_month": local_transfers_by_month,
            "goal_2026_min": 100,
        },
        "unclassified_transfers_all_time": unclassified_transfers["all_time"],
        "foster_caregivers": {
            "active_2026": foster_caregivers_active["active_2026"],
            "one_time_2026": foster_caregivers_active["one_time_2026"],
            "goal_2026_min": 15,
        },
    },
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
print(f"  TX transport-in (CY2026, arrived): {transport_totals['cy2026']}")
print(f"  TX transported & adopted (CY2026, grant KPI): {transport_adopted_totals['cy2026_adopted']} / goal 180")
print(f"  NC local transfers-in (CY2026): {local_transfers['cy2026']} / goal 100")
print(f"  Unclassified transfer origin (all-time): {unclassified_transfers['all_time']}")
print(f"  Foster caregivers, 2+ placements (CY2026): {foster_caregivers_active['active_2026']} / goal 15")
