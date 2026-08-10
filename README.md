# NC Adoption Center Dashboard

Live metrics for APA!'s Shelter Pet Adoption Center (Huntersville, NC). Three tabs:

- **Overview** — general center pulse: current snapshot, adoptions, foster, volunteers
- **Petco Love** — progress against the Petco Love grant (G-2406-56741) Year 1/Year 2 adoption-count goals
- **Pedigree Foundation** — progress against the March 2026 PEDIGREE Foundation D2A (Direct to Adopt) transport capacity grant: TX&rarr;NC transport-ins, D2A outcomes, local NC shelter transfers-in, foster corps growth

**Live URL:** https://joslyncavitt01.github.io/nc-petco-dashboard/

## Data source

- `apa-data-410213.nc_shelterluv` (Animals, Outcomes, Intakes, AnimalAttributes) for adoptions, foster, current custody, transport-ins, and D2A tagging
- `apa-data-410213.betterImpact` (TimelogEntries, Users, filtered to North Carolina) for volunteer hours

## Goal framing

**Petco Love** — Year 1 / Year 2 goal measurement confirmed by Petco Love (Mary Ann Magana, 7/17/26): calendar year, separate annual goals.

- Year 1 = calendar year 2025, goal 500-750 adoptions
- Year 2 = calendar year 2026, goal 750-1,000 adoptions

**Pedigree Foundation D2A** — 2026 goals from the March 2026 proposal:

- 180+ pets transported from Texas source shelters to NC in 2026 (identified by intakeSubType `HNCSPAC - Space` / `Transport Held at APATH`)
- 100+ local NC shelter transfers-in (all other `Intake.Transfer` records) — tagging is sparse/early-stage, read as directional
- Active NC foster corps grown from 5 to 15+ caregivers ("active" = fostered 2+ times in calendar year 2026, not a point-in-time snapshot of who currently has an animal -- that undercounted, since some currently-in-foster animals have no Intake/Outcome record at all to trace a caregiver from)
- D2A outcomes tracked via the `D2A` AnimalAttributes tag, split into direct adoptions vs. foster-to-adopt

## Refreshing the data

```
python3 fetch_data.py
git add data/metrics.json
git commit -m "Refresh metrics"
git push
```

An auto-refresh LaunchAgent (`com.apa.nc-petco-dashboard`) handles this automatically. See `update.sh`.
