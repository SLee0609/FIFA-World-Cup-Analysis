# FIFA World Cup Player Physical Performance Analysis

Analysis of how recovery and prior match workload affect player physical performance at the 2022 and 2026 FIFA World Cups. The data comes from FIFA's official post-match summary reports (PDFs from the [FIFA Training Centre](https://www.fifatrainingcentre.com)).

## Repository contents

| File | Purpose |
|---|---|
| `download_2022_match_reports.py` | Downloads the 64 FIFA World Cup 2022 post-match reports into `2022_match_reports/`. |
| `download_2026_match_reports.py` | Downloads the 104 FIFA World Cup 2026 post-match reports into `2026_match_reports/`. |
| `extract_raw_data.py` | Parses every report PDF into `raw_data.csv`, with one row per player per match. |
| `raw_data.csv` | The extracted player-match dataset (schema below). |
| `project.Rmd` / `project.pdf` | Analysis and write-up. |
| `Proposal.pdf` | Project proposal. |

## Reproducing the data

```bash
pip install requests beautifulsoup4 pymupdf
python download_2022_match_reports.py
python download_2026_match_reports.py
python extract_raw_data.py              # writes raw_data.csv
```

Run the scripts from the repository root, because all paths are relative.

## `raw_data.csv` schema

Each row is one player's appearance in one match. A player is included only if they appear in the report's Physical Data table, which normally means they played. A row is uniquely identified by (`match_id`, `player_tournament_id`). Blank cells mean missing values. Columns are listed below by the report page they come from.

### Match information (cover page)

| Column | Type | Description |
|---|---|---|
| `tournament_year` | int | 2022 or 2026. |
| `match_id` | str | Unique match key, `<year>_M<number>` (e.g. `2022_M001`). |
| `fifa_match_number` | int | FIFA's official match number within the tournament. |
| `stage` | str | `Group Stage`, `Round of 32`, `Round of 16`, `Quarter-final`, `Semi-final`, `Play-off for third place` / `Bronze final`, or `Final`. The third-place match is named differently in the two tournaments. |
| `stage_type` | str | `group` or `knockout`. |
| `group` | str | Group letter (A–H in 2022, A–L in 2026). Blank for knockout matches. |
| `match_date` | date | Match date (YYYY-MM-DD). |
| `kickoff_time_local` | str | Local kickoff time (HH:MM). |
| `stadium` | str | Stadium name. |
| `team` | str | The player's team. |
| `opponent` | str | The opposing team. |
| `team_goals` | int | Goals scored by `team`. Penalty shootouts are not included. |
| `opponent_goals` | int | Goals scored by `opponent`. |

### Player and playing time (lineup page)

| Column | Type | Description |
|---|---|---|
| `team_tournament_id` | str | Team key within a tournament, `<year>_<TEAM>` (e.g. `2022_QATAR`). |
| `player_name` | str | Player name exactly as printed in the Physical Data table. Formatting differs between years (2022: `SURNAME Given`; 2026: `Given SURNAME`). |
| `player_tournament_id` | str | Player key within a tournament, `<year>_<TEAM>_<NAME>_<shirt>`. Use it to link one player's matches. |
| `shirt_number` | int | Shirt number. |
| `position` | str | `GK`, `DF`, `MF`, or `FW`, as listed on the lineup page. |
| `starter` | int | 1 if the player started, 0 if they were on the bench. |
| `sub_on_minute` | int | Minute the player came on. Blank for starters. |
| `sub_off_minute` | int | Minute the player was substituted off. Blank if they were not substituted off. |
| `sent_off_minute` | int | Minute of a red card, or of a second yellow card. Blank if not sent off. |
| `match_duration_min` | int | 90, or 120 if the match went to extra time. |
| `minutes_played` | int | Minutes on the pitch, from coming on until the end of the match, being substituted off or being sent off. Stoppage time is ignored: a minute of 90+2 counts as 90. As a result, a substitute who came on in stoppage time at the end of the match has 0 minutes. |

### Physical data (Physical Data page)

| Column | Type | Description |
|---|---|---|
| `total_distance_m` | float | Total distance covered (m). |
| `zone1_distance_m` | float | Distance at 0–7 km/h (m). |
| `zone2_distance_m` | float | Distance at 7–15 km/h (m). |
| `zone3_distance_m` | float | Distance at 15–20 km/h (m). |
| `zone4_distance_m` | float | Distance at 20–25 km/h (m). |
| `zone5_distance_m` | float | Distance at 25+ km/h (m). |
| `high_speed_runs` | int | Number of high-speed runs (definition in `high_speed_runs_definition`). |
| `sprints` | int | Number of sprints (definition in `sprints_definition`). |
| `top_speed_kmh` | float | Top speed reached (km/h). |
| `high_speed_runs_definition` | str | Speed zone that counts as a high-speed run in this report: `Zone 3`, `Zone 4`, or `Not specified on table`. |
| `sprints_definition` | str | Speed zone(s) that count as a sprint in this report: `Zone 4 & 5`, `Zone 5`, or `Not specified on table`. |

The definitions of high-speed runs and sprints differ between report editions. Check the two definition columns before comparing these counts across matches.

### Out of possession data (Out of Possession page)

All counts are integers.

| Column | Description |
|---|---|
| `tackles_made` | Tackles attempted. |
| `tackles_won` | Tackles won. |
| `blocks` | Blocks. |
| `interceptions` | Interceptions. |
| `pressing_direct` | Direct pressures on the ball carrier. |
| `pressing_indirect` | Indirect pressures (closing down passing options rather than the ball carrier). |
| `aerial_duels_won` | Aerial duels won. |
| `physical_duels_won` | Physical (ground) duels won. |
| `possession_contests_won` | Contests for possession won. |
| `clearances` | Clearances. |
| `loose_ball_receptions` | Loose balls gathered. |
| `pushing_on` | Times the player pushed forward to close space while the team was out of possession. |
| `pushing_on_into_pressing` | Times pushing forward led directly into a press. |
| `possession_regains` | Times the player won the ball back for their team. |
| `possession_interrupted` | Times the player stopped the opponent's possession without winning the ball back. |

The 2022 reports also include a Forced Turnovers column. It is 0 for every player and absent from 2026, so it is not extracted.

### Data lineage and quality

| Column | Type | Description |
|---|---|---|
| `source_pdf` | str | Filename of the source report. |
| `lineup_page` | int | Report page of the lineup (always 2). |
| `physical_page` | int | Report page of the player's Physical Data table. |
| `oop_page` | int | Report page of the player's Out of Possession table. |
| `qc_flag` | str | Quality-check flags, separated by `;`. Blank if none. See below. |

### `qc_flag` values

| Flag | Meaning |
|---|---|
| `nonpositive_minutes_played` | `minutes_played` is 0 or negative. In practice these are substitutes who came on in stoppage time at the end of the match, so the flag usually marks real but very short appearances. |
| `substitute_entry_not_inferred` | A bench player with no detected substitution-on time, so `sub_on_minute` and `minutes_played` are blank. Usually a listed substitute who didn't play (0 m distance). Otherwise the script failed to read the entry time. |
| `lineup_not_matched` | The player's shirt number was not found in the lineup on page 2. Lineup fields are blank. |
| `substitution_icon_unrecognized` | A substitution arrow's direction couldn't be determined, or more than one arrow in the same direction was found. Check the substitution times by hand. |
| `oop_not_matched` | The player has no row in the Out of Possession table. Those columns are blank. |
