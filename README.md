# NC Adoption Center Dashboard

Live metrics for APA!'s Shelter Pet Adoption Center (Huntersville, NC). Four tabs:

- **Overview** — general center pulse: current snapshot, adoptions, foster, volunteers
- **Petco Love** — progress against the Petco Love grant (G-2406-56741) Year 1/Year 2 adoption-count goals
- **Pedigree Foundation** — progress against the March 2026 PEDIGREE Foundation D2A (Direct to Adopt) transport capacity grant: TX&rarr;NC transport-ins (scored on transport + adoption, not arrival alone), D2A outcomes, local NC shelter transfers-in, foster corps growth
- **Animal Profiles** — every NC animal, all-time, searchable/filterable grid with a full-detail view per animal. For animals transferred in through Austin Pets Alive's own ShelterLuv, combines their full Austin history (photo, memos, attributes, intake/outcome timeline) with their NC record; others show NC-only data (no photo available there)

**Live URL:** https://joslyncavitt01.github.io/nc-petco-dashboard/

## Data source

- `apa-data-410213.nc_shelterluv` (Animals, Outcomes, Intakes, AnimalAttributes, AnimalMemos, AnimalPreviousIds) for adoptions, foster, current custody, transport-ins, D2A tagging, and animal profiles
- `apa-data-410213.shelterluv` (Austin's production tables: Animals, AnimalPhotos, AnimalMemos, AnimalAttributes, Intakes, Outcomes) for the Austin side of combined animal profiles
- `apa-data-410213.betterImpact` (TimelogEntries, Users, filtered to North Carolina) for volunteer hours

## Animal Profiles methodology

An NC animal is linked to its Austin ShelterLuv record via `AnimalPreviousIds` (`issuingShelter = 'Austin Pets Alive, Inc.'`, `idType = 'Shelterluv'`), whose `previousIdValue` (e.g. `APA-A-188783`) numeric suffix matches Austin's `Animals.animalAID`. About 143 of 533 all-time NC animals resolve this way (139 have a photo). Animals transferred from other TX shelters directly (Bryan, Bastrop, Lufkin, etc.) or sourced in NC don't have this link and only show NC data.

## Goal framing

**Petco Love** — Year 1 / Year 2 goal measurement confirmed by Petco Love (Mary Ann Magana, 7/17/26): calendar year, separate annual goals.

- Year 1 = calendar year 2025, goal 500-750 adoptions
- Year 2 = calendar year 2026, goal 750-1,000 adoptions

**Pedigree Foundation D2A** — 2026 goals from the March 2026 proposal:

- 180+ pets transported from Texas source shelters to NC **and placed in adoptive homes** in 2026 — scored on transport + a subsequent `Outcome.Adoption`, not arrival alone. TX vs. NC origin comes from `AnimalPreviousIds.issuingShelter` (direct match against known TX/NC shelter names), backfilled by the dominant issuingShelter seen for that transfer's partner when the animal's own previous-ID record is blank -- NOT from intakeSubType, which mixes TX and NC transfers under the same labels (`HNCSPAC - Space`, `Transport Held at APATH`)
- 100+ local NC shelter transfers-in, using the same origin classification (NC-matched shelters, e.g. Charlotte-Mecklenburg, Catawba County)
- Active NC foster corps grown from 5 to 15+ caregivers ("active" = fostered 2+ times in calendar year 2026, not a point-in-time snapshot of who currently has an animal -- that undercounted, since some currently-in-foster animals have no Intake/Outcome record at all to trace a caregiver from)
- D2A outcomes tracked via the `D2A` AnimalAttributes tag, split into direct adoptions vs. foster-to-adopt

## Refreshing the data

```
python3 fetch_data.py
git add data/metrics.json data/animal_profiles.json
git commit -m "Refresh metrics"
git push
```

An auto-refresh LaunchAgent (`com.apa.nc-petco-dashboard`) handles this automatically. See `update.sh`.
