# NC Adoption Center Dashboard

Live metrics for APA!'s Shelter Pet Adoption Center (Huntersville, NC), tracking progress against the Petco Love grant (G-2406-56741).

**Live URL:** https://joslyncavitt01.github.io/nc-petco-dashboard/

## Data source

- `apa-data-410213.nc_shelterluv` (Animals, Outcomes, Intakes) for adoptions, foster, and current custody
- `apa-data-410213.betterImpact` (TimelogEntries, Users, filtered to North Carolina) for volunteer hours

## Goal framing

Year 1 / Year 2 goal measurement confirmed by Petco Love (Mary Ann Magana, 7/17/26): calendar year, separate annual goals.

- Year 1 = calendar year 2025, goal 500-750 adoptions
- Year 2 = calendar year 2026, goal 750-1,000 adoptions

## Refreshing the data

```
python3 fetch_data.py
git add data/metrics.json
git commit -m "Refresh metrics"
git push
```

An auto-refresh LaunchAgent (`com.apa.nc-petco-dashboard`) handles this automatically. See `update.sh`.
