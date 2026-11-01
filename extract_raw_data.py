#!/usr/bin/env python3
"""
Extract player-level physical data from FIFA World Cup post-match summary PDFs.

Designed for the FIFA 2022 and 2026 post-match report layouts, including:
- group-stage matches,
- knockout matches ending in 90 minutes,
- knockout matches going to 120 minutes.

Output:
    One CSV row per player-match appearance.

Dependency:
    pip install pymupdf

Usage:
    1. Place 2022 reports in ./2022_match_reports
    2. Place 2026 reports in ./2026_match_reports
    3. Run: python extract_raw_data.py

The input directories and output CSV path are configured as constants below.

Notes:
- "minutes_played" ignores stoppage time. A substitution at 90+2
  is treated as minute 90, and a substitution at 120+1 as minute 120.
- Substitution times are identified from the up/down arrow icons drawn next
  to timestamps on the lineup page.
- Dismissals are identified from red card icons, or from two yellow card
  icons, and end a player's minutes_played at "sent_off_minute".
- FIFA's definitions of "High Speed Runs" and "Sprints" differ across some
  report editions, so the source definitions are stored alongside the values.
"""

from __future__ import annotations

import csv
import re
import sys
import unicodedata
from datetime import datetime
from pathlib import Path

import fitz  # PyMuPDF


POSITIONS = {"GK", "DF", "MF", "FW"}

# ---------------------------------------------------------------------------
# Configuration
# ---------------------------------------------------------------------------
# These paths are interpreted relative to the directory from which you run
# this script. Change them here if you move the report folders or want a
# different output filename.
MATCH_REPORT_DIRS = (
    Path("./2022_match_reports"),
    Path("./2026_match_reports"),
)
OUTPUT_FILE = Path("./raw_data.csv")

# Set to True only if your PDFs are stored in nested subdirectories.
RECURSIVE = False

# If True, stop at the first PDF that cannot be parsed. If False, continue
# processing the remaining PDFs and print a summary of failures at the end.
STRICT = False

OUTPUT_COLUMNS = [
    "tournament_year",
    "match_id",
    "fifa_match_number",
    "stage",
    "stage_type",
    "group",
    "match_date",
    "kickoff_time_local",
    "stadium",
    "team",
    "opponent",
    "team_goals",
    "opponent_goals",
    "team_tournament_id",
    "player_name",
    "player_tournament_id",
    "shirt_number",
    "position",
    "starter",
    "sub_on_minute",
    "sub_off_minute",
    "sent_off_minute",
    "match_duration_min",
    "minutes_played",
    "total_distance_m",
    "zone1_distance_m",
    "zone2_distance_m",
    "zone3_distance_m",
    "zone4_distance_m",
    "zone5_distance_m",
    "high_speed_runs",
    "sprints",
    "top_speed_kmh",
    "high_speed_runs_definition",
    "sprints_definition",
    "tackles_made",
    "tackles_won",
    "blocks",
    "interceptions",
    "pressing_direct",
    "pressing_indirect",
    "aerial_duels_won",
    "physical_duels_won",
    "possession_contests_won",
    "clearances",
    "loose_ball_receptions",
    "pushing_on",
    "pushing_on_into_pressing",
    "possession_regains",
    "possession_interrupted",
    "source_pdf",
    "lineup_page",
    "physical_page",
    "oop_page",
    "qc_flag",
]

# Out-of-possession table columns, each located by a header word that is
# unique to that column (the nth occurrence, for words that repeat). Header
# positions differ between report editions, and "Forced Turnovers" is absent
# from some reports, so columns are found by header rather than fixed x-ranges.
# "tackles" holds the combined "Made / Won" cell and is split when parsed.
# "forced_turnovers" is located only so its values are not assigned to a
# neighboring column; it is always 0 where present and is not output.
OOP_HEADERS = [
    ("tackles", "Tackles", 0),
    ("blocks", "Blocks", 0),
    ("interceptions", "Interceptions", 0),
    ("pressing_direct", "Direct", 0),
    ("pressing_indirect", "Indirect", 0),
    ("forced_turnovers", "Turnovers", 0),
    ("aerial_duels_won", "Aerial", 0),
    ("physical_duels_won", "Physical", 0),
    ("possession_contests_won", "Contests", 0),
    ("clearances", "Clearances", 0),
    ("loose_ball_receptions", "Receptions", 0),
    ("pushing_on", "Pushing", 0),
    ("pushing_on_into_pressing", "Pushing", 1),
    ("possession_regains", "Regains", 0),
    ("possession_interrupted", "Interrupted", 0),
]

OOP_COLUMNS = [
    "tackles_made",
    "tackles_won",
    *(
        column
        for column, _, _ in OOP_HEADERS
        if column not in {"tackles", "forced_turnovers"}
    ),
]


def normalize_id(text: str) -> str:
    """Convert a label/name to a stable ASCII identifier fragment."""
    text = unicodedata.normalize("NFKD", text)
    text = "".join(c for c in text if not unicodedata.combining(c))
    text = re.sub(r"[^A-Za-z0-9]+", "_", text.upper()).strip("_")
    return text


def parse_cover(doc: fitz.Document) -> dict:
    """Parse teams, score, stage, date, kickoff, and stadium from page 1."""
    text = doc[0].get_text("text")
    lines = [re.sub(r"\s+", " ", x).strip() for x in text.splitlines() if x.strip()]

    score_index = None
    team1 = team2 = None
    score1 = score2 = None

    for i, line in enumerate(lines):
        m = re.match(r"^(.*?)\s+(\d+)\s*-\s*(\d+)\s+(.*?)$", line)
        if m:
            team1, a, b, team2 = m.groups()
            score1, score2 = int(a), int(b)
            score_index = i
            break

    if team1 is None:
        raise ValueError("Could not parse teams/score from cover page.")

    stage_raw = None
    match_number = None
    match_date = None
    kickoff_time = None
    stadium = None

    for line in lines[score_index + 1 :]:
        if stage_raw is None:
            m = re.match(r"^(.*?)\s*-\s*Match\s*(\d+)\s*$", line, flags=re.I)
            if m:
                stage_raw = m.group(1).strip()
                match_number = int(m.group(2))
                continue

        if match_date is None:
            for fmt in ("%d %B %Y", "%d %b %Y"):
                try:
                    match_date = datetime.strptime(line, fmt).date().isoformat()
                    break
                except ValueError:
                    pass
            if match_date:
                continue

        if kickoff_time is None and "Kick Off" in line:
            m = re.search(r"(\d{1,2}:\d{2})", line)
            if m:
                kickoff_time = m.group(1)
            continue

        if (
            match_date
            and kickoff_time
            and stadium is None
            and "POST MATCH" not in line.upper()
        ):
            stadium = line
            break

    if stage_raw and re.match(r"^Group\s+", stage_raw, flags=re.I):
        group = re.sub(r"^Group\s+", "", stage_raw, flags=re.I).strip()
        stage = "Group Stage"
        stage_type = "group"
    else:
        group = ""
        stage = stage_raw
        stage_type = "knockout"

    tournament_year = int(match_date[:4]) if match_date else None
    match_id = (
        f"{tournament_year}_M{match_number:03d}"
        if tournament_year is not None and match_number is not None
        else None
    )

    return {
        "tournament_year": tournament_year,
        "match_id": match_id,
        "fifa_match_number": match_number,
        "stage": stage,
        "stage_type": stage_type,
        "group": group,
        "match_date": match_date,
        "kickoff_time_local": kickoff_time,
        "stadium": stadium,
        "team1": team1,
        "team2": team2,
        "score1": score1,
        "score2": score2,
    }


def detect_match_duration(doc: fitz.Document) -> int:
    """
    Return 90 or 120 nominal minutes.

    Extra-time reports include "120" on the page-2 match timeline.
    """
    page2 = re.sub(r"\s+", " ", doc[1].get_text("text"))
    return 120 if re.search(r"\b120\b", page2) else 90


def group_words_into_rows(words, x_min=None, x_max=None, tolerance=2.2):
    """Group PyMuPDF words into approximate horizontal rows."""
    filtered = []

    for word in words:
        x0, y0, x1, y1, *_ = word

        if x_min is not None and x0 < x_min:
            continue
        if x_max is not None and x1 > x_max:
            continue

        filtered.append(word)

    filtered.sort(key=lambda w: (((w[1] + w[3]) / 2), w[0]))

    groups = []

    for word in filtered:
        y_center = (word[1] + word[3]) / 2

        if not groups or abs(y_center - groups[-1][0]) > tolerance:
            groups.append([y_center, [word]])
        else:
            groups[-1][1].append(word)
            groups[-1][0] = sum(
                (w[1] + w[3]) / 2 for w in groups[-1][1]
            ) / len(groups[-1][1])

    return [sorted(g[1], key=lambda w: w[0]) for g in groups]


def extract_timestamp_events(row) -> list[dict]:
    """
    Extract timestamp text and bounding boxes from one lineup row.

    FIFA timestamps are normally stored as tokens such as ``76'`` or
    ``120+1'``. Some 2022 PDFs split a value such as ``41'`` into ``4`` and
    ``1'``; those adjacent tokens are recombined here.

    Returns dictionaries with:
        timestamp: clock text without the trailing apostrophe
        rect:      fitz.Rect covering the timestamp text
    """
    events = []
    i = 0

    while i < len(row):
        word = row[i]
        token = word[4].replace("’", "'").strip()

        # Normal token such as 76' or 120+1'.
        if re.fullmatch(r"\d{1,3}(?:\+\d{1,2})?'", token):
            events.append(
                {
                    "timestamp": token[:-1],
                    "rect": fitz.Rect(word[:4]),
                }
            )
            i += 1
            continue

        # Number followed by a standalone apostrophe token.
        if (
            re.fullmatch(r"\d{1,3}(?:\+\d{1,2})?", token)
            and i + 1 < len(row)
            and row[i + 1][4].strip() in ("'", "’")
        ):
            rect = fitz.Rect(word[:4]) | fitz.Rect(row[i + 1][:4])
            events.append({"timestamp": token, "rect": rect})
            i += 2
            continue

        # PDF tokenization sometimes turns 41' into two nearby tokens:
        # "4" and "1'". Require a very small horizontal gap so that a shirt
        # number is not accidentally combined with an unrelated timestamp.
        if re.fullmatch(r"\d{1,2}", token) and i + 1 < len(row):
            next_word = row[i + 1]
            next_token = next_word[4].replace("’", "'").strip()
            horizontal_gap = next_word[0] - word[2]

            if (
                re.fullmatch(r"\d(?:\+\d{1,2})?'", next_token)
                and horizontal_gap <= 3.0
            ):
                combined = token + next_token[:-1]
                base_minute = int(combined.split("+")[0])

                if base_minute <= 130:
                    rect = fitz.Rect(word[:4]) | fitz.Rect(next_word[:4])
                    events.append({"timestamp": combined, "rect": rect})
                    i += 2
                    continue

        i += 1

    return events


def _arrow_direction(drawing: dict) -> str | None:
    """
    Recognize FIFA's substitution-arrow vector path.

    In the supplied 2022 and 2026 reports the substitution icon is a small,
    filled, seven-segment arrow. We identify the geometry, then determine
    whether its tip points upward (substitution on) or downward
    (substitution off). This intentionally does not depend on the arrow color.
    """
    rect = fitz.Rect(drawing["rect"])
    items = drawing.get("items", [])

    if not (5.0 <= rect.width <= 10.0 and 5.0 <= rect.height <= 10.0):
        return None

    if len(items) != 7 or not all(item[0] == "l" for item in items):
        return None

    points = []
    for item in items:
        points.extend((item[1], item[2]))

    center_x = (rect.x0 + rect.x1) / 2

    # The arrow tip lies approximately at the horizontal center and at one
    # vertical extreme of the icon's bounding box.
    distance_to_top_tip = min(
        ((point.x - center_x) ** 2 + (point.y - rect.y0) ** 2) ** 0.5
        for point in points
    )
    distance_to_bottom_tip = min(
        ((point.x - center_x) ** 2 + (point.y - rect.y1) ** 2) ** 0.5
        for point in points
    )

    if abs(distance_to_top_tip - distance_to_bottom_tip) < 0.5:
        return "unrecognized"

    return "sub_on" if distance_to_top_tip < distance_to_bottom_tip else "sub_off"


def _card_color(drawing: dict) -> str | None:
    """
    Recognize FIFA's booking icon: a single filled rectangle about 6x9 pt.

    Yellow and red cards share the same geometry, so the fill color is used
    here: yellow is approximately (0.98, 0.75, 0.14) and red approximately
    (0.97, 0.44, 0.44).
    """
    rect = fitz.Rect(drawing["rect"])
    items = drawing.get("items", [])

    if not (4.0 <= rect.width <= 8.0 and 7.0 <= rect.height <= 11.0):
        return None

    if len(items) != 1 or items[0][0] != "re":
        return None

    fill = drawing.get("fill")

    if not fill or len(fill) < 3 or fill[0] < 0.8:
        return None

    return "yellow_card" if fill[1] >= 0.6 else "red_card"


def classify_timestamp_icon(page: fitz.Page, timestamp_rect: fitz.Rect) -> str:
    """
    Inspect the vector icon immediately to the left of a timestamp.

    Returns one of:
        "sub_on"       - upward substitution arrow
        "sub_off"      - downward substitution arrow
        "yellow_card"  - yellow booking icon
        "red_card"     - red booking icon
        "other"        - a timestamp with another icon (e.g. goal)
        "unrecognized" - an arrow-like icon was found but orientation could
                         not be determined
        "none"         - no recognized icon geometry was found

    The page's text extraction omits the icons, but ``page.get_drawings()``
    retains their vector paths. This lets us distinguish substitution times
    from goal/card timestamps without matching equal minute values.
    """
    arrow_like_found = False
    nearby_graphic_found = False

    for drawing in page.get_drawings():
        rect = fitz.Rect(drawing["rect"])

        # FIFA places the event icon just to the left of the timestamp.
        horizontal_gap = timestamp_rect.x0 - rect.x1
        vertical_difference = abs(
            (rect.y0 + rect.y1) / 2
            - (timestamp_rect.y0 + timestamp_rect.y1) / 2
        )

        if not (-0.5 <= horizontal_gap <= 12.0):
            continue
        if vertical_difference > 4.0:
            continue
        if rect.width > 15.0 or rect.height > 15.0:
            continue

        nearby_graphic_found = True
        direction = _arrow_direction(drawing)

        if direction in {"sub_on", "sub_off"}:
            return direction
        if direction == "unrecognized":
            arrow_like_found = True

        card = _card_color(drawing)

        if card is not None:
            return card

    if arrow_like_found:
        return "unrecognized"
    if nearby_graphic_found:
        return "other"
    return "none"

def nominal_minute(timestamp: str, duration: int) -> int:
    """
    Convert a FIFA clock timestamp to nominal playing time.

    Examples:
        76    -> 76
        90+2  -> 90
        102   -> 102
        120+1 -> 120
    """
    base = int(timestamp.split("+")[0])

    if "+" in timestamp and base in {45, 90, 105, 120}:
        value = base
    else:
        value = base

    return max(0, min(value, duration))


def parse_lineup_side(page: fitz.Page, side: str, duration: int) -> list[dict]:
    """
    Parse one team's page-2 roster and read substitution arrows directly.

    FIFA places an upward arrow next to a substitute's entry time and a
    downward arrow next to the outgoing player's exit time. Because goals,
    cards, and substitutions can all have timestamps, event type is determined
    from the nearby vector icon rather than from the timestamp alone.
    """
    words = page.get_text("words")

    # The player lists live at the far left/right of page 2. A player with
    # several events can have a fourth timestamp reaching x=314 on the left
    # or starting at x=658 on the right, so the bounds stop just short of the
    # central formation graphic (x>=320) and right-hand header text (x<=630).
    if side == "left":
        rows = group_words_into_rows(words, x_min=20, x_max=318)
    else:
        rows = group_words_into_rows(words, x_min=645, x_max=940)

    markers = {}

    for row in rows:
        texts = [w[4] for w in row]
        row_text = " ".join(texts).upper()
        y_center = sum((w[1] + w[3]) / 2 for w in row) / len(row)

        if "STARTING" in row_text and "starting" not in markers:
            markers["starting"] = y_center

        if "SUBSTITUTES" in row_text and "substitutes" not in markers:
            markers["substitutes"] = y_center

    if "starting" not in markers or "substitutes" not in markers:
        raise ValueError(f"Could not identify {side} lineup sections on page 2.")

    players = []

    for row in rows:
        texts = [w[4] for w in row]
        y_center = sum((w[1] + w[3]) / 2 for w in row) / len(row)

        if y_center < markers["starting"] - 3:
            continue

        position = None
        shirt_number = None
        pos_index = None

        for i, token in enumerate(texts):
            if token in POSITIONS:
                position = token
                pos_index = i

                adjacent = (
                    texts[i - 1]
                    if side == "left" and i > 0
                    else texts[i + 1]
                    if side == "right" and i + 1 < len(texts)
                    else ""
                )

                if re.fullmatch(r"\d{1,2}", adjacent):
                    shirt_number = int(adjacent)

                break

            # Sometimes right-side PDF text combines position and number: FW15.
            m = re.fullmatch(r"(GK|DF|MF|FW)(\d{1,2})", token)

            if m:
                position = m.group(1)
                shirt_number = int(m.group(2))
                pos_index = i
                break

        if position is None:
            continue

        if shirt_number is None:
            nearby = [
                (abs(i - pos_index), int(token))
                for i, token in enumerate(texts)
                if re.fullmatch(r"\d{1,2}", token)
            ]

            if nearby:
                shirt_number = min(nearby)[1]

        if shirt_number is None:
            continue

        starter = y_center < markers["substitutes"]

        timestamp_events = extract_timestamp_events(row)
        sub_on_events = []
        sub_off_events = []
        yellow_card_events = []
        red_card_events = []
        substitution_icon_unrecognized = False

        for event in timestamp_events:
            icon_type = classify_timestamp_icon(page, event["rect"])

            if icon_type == "sub_on":
                sub_on_events.append(event["timestamp"])
            elif icon_type == "sub_off":
                sub_off_events.append(event["timestamp"])
            elif icon_type == "yellow_card":
                yellow_card_events.append(event["timestamp"])
            elif icon_type == "red_card":
                red_card_events.append(event["timestamp"])
            elif icon_type == "unrecognized":
                substitution_icon_unrecognized = True

        # A player can only enter once and leave once. If icon recognition
        # somehow yields multiple arrows of the same direction, keep the
        # chronologically appropriate one and flag the row for review.
        if len(sub_on_events) > 1 or len(sub_off_events) > 1:
            substitution_icon_unrecognized = True

        sub_on_time_raw = (
            min(sub_on_events, key=lambda x: nominal_minute(x, duration))
            if sub_on_events
            else None
        )
        sub_off_time_raw = (
            max(sub_off_events, key=lambda x: nominal_minute(x, duration))
            if sub_off_events
            else None
        )

        if starter:
            on = 0
            sub_on_minute = None
        elif sub_on_time_raw is not None:
            on = nominal_minute(sub_on_time_raw, duration)
            sub_on_minute = on
        else:
            on = None
            sub_on_minute = None

        # FIFA marks a straight red with a red card icon, and a second yellow
        # with two yellow card icons rather than a red one. Booking times may
        # be written as absolute minutes (e.g. 93'), which nominal_minute()
        # caps at the match duration.
        sent_off_candidates = [
            nominal_minute(t, duration) for t in red_card_events
        ]

        if len(yellow_card_events) >= 2:
            yellow_minutes = sorted(
                nominal_minute(t, duration) for t in yellow_card_events
            )
            sent_off_candidates.append(yellow_minutes[1])

        sent_off_minute = min(sent_off_candidates) if sent_off_candidates else None

        if sub_off_time_raw is not None:
            off = nominal_minute(sub_off_time_raw, duration)
            sub_off_minute = off
        elif on is not None:
            off = duration
            sub_off_minute = None
        else:
            off = None
            sub_off_minute = None

        # A dismissal ends the player's time on the pitch, unless they had
        # already been substituted off (e.g. a red card on the bench).
        if off is not None and sent_off_minute is not None:
            off = min(off, sent_off_minute)

        minutes_played = (
            off - on if on is not None and off is not None else None
        )

        players.append(
            {
                "shirt_number": shirt_number,
                "position": position,
                "starter": starter,
                "sub_on_time_raw": sub_on_time_raw,
                "sub_off_time_raw": sub_off_time_raw,
                "sub_on_minute": sub_on_minute,
                "sub_off_minute": sub_off_minute,
                "sent_off_minute": sent_off_minute,
                "minutes_played": minutes_played,
                "substitution_icon_unrecognized": substitution_icon_unrecognized,
            }
        )

    return players

def parse_physical_page(page: fitz.Page) -> tuple[str, list[dict]]:
    """
    Parse one FIFA "Physical Data <Team>" page.

    Uses the table's stable horizontal geometry instead of depending on
    line-oriented text extraction.
    """
    text = page.get_text("text")
    lines = [re.sub(r"\s+", " ", x).strip() for x in text.splitlines() if x.strip()]

    team = None

    for i, line in enumerate(lines):
        if line == "Physical Data" and i + 1 < len(lines):
            team = lines[i + 1]
            break

    if team is None:
        m = re.search(r"Physical Data\s+([^\n]+)", text)
        team = m.group(1).strip() if m else ""

    words = page.get_text("words")

    # Preserve FIFA's edition-specific definitions.
    hsr_header = " ".join(
        w[4]
        for w in words
        if 730 <= ((w[0] + w[2]) / 2) < 815 and w[1] < 110
    )
    sprint_header = " ".join(
        w[4]
        for w in words
        if 815 <= ((w[0] + w[2]) / 2) < 885 and w[1] < 110
    )

    m = re.search(r"\(Zone\s*([^)]+)\)", hsr_header, flags=re.I)
    hsr_definition = f"Zone {m.group(1).strip()}" if m else "Not specified on table"

    m = re.search(r"\(Zone\s*([^)]+)\)", sprint_header, flags=re.I)
    sprint_definition = (
        f"Zone {m.group(1).strip()}" if m else "Not specified on table"
    )

    rows = group_words_into_rows(words, x_min=15, x_max=945, tolerance=2.5)

    # Column ranges are stable across the supplied 2022 and 2026 reports.
    columns = [
        ("total_distance_m", 240, 350),
        ("zone1_distance_m", 350, 425),
        ("zone2_distance_m", 425, 500),
        ("zone3_distance_m", 500, 580),
        ("zone4_distance_m", 580, 665),
        ("zone5_distance_m", 665, 735),
        ("high_speed_runs", 735, 815),
        ("sprints", 815, 885),
        ("top_speed_kmh", 885, 950),
    ]

    output = []

    for row in rows:
        shirt_words = [
            w for w in row if w[0] < 35 and re.fullmatch(r"\d{1,2}", w[4])
        ]

        if not shirt_words:
            continue

        shirt_number = int(shirt_words[0][4])

        name_tokens = [
            w[4]
            for w in row
            if 35 <= ((w[0] + w[2]) / 2) < 240
            and not re.fullmatch(r"\d+(?:\.\d+)?", w[4])
        ]

        player_name = re.sub(r"\s+", " ", " ".join(name_tokens)).strip()

        values = {}

        for column, x_min, x_max in columns:
            candidates = []

            for word in row:
                x_center = (word[0] + word[2]) / 2

                if (
                    x_min <= x_center < x_max
                    and re.fullmatch(r"\d+(?:\.\d+)?", word[4])
                ):
                    candidates.append((x_center, word[4]))

            values[column] = (
                float(candidates[0][1]) if candidates else None
            )

        # Exclude non-player/header rows.
        if (
            values["total_distance_m"] is None
            or values["top_speed_kmh"] is None
        ):
            continue

        # Blank distance cells in these FIFA tables represent zero.
        for column in (
            "zone1_distance_m",
            "zone2_distance_m",
            "zone3_distance_m",
            "zone4_distance_m",
            "zone5_distance_m",
        ):
            if values[column] is None:
                values[column] = 0.0

        for column in ("high_speed_runs", "sprints"):
            if values[column] is not None:
                values[column] = int(round(values[column]))

        output.append(
            {
                "shirt_number": shirt_number,
                "player_name": player_name,
                "high_speed_runs_definition": hsr_definition,
                "sprints_definition": sprint_definition,
                **values,
            }
        )

    return team, output


def parse_oop_page(page: fitz.Page) -> tuple[str, list[dict]]:
    """
    Parse one FIFA individual "Out of Possession <Team>" page.

    Each value is assigned to the column whose header is horizontally
    nearest, since column positions vary between report editions.
    """
    text = page.get_text("text")
    lines = [re.sub(r"\s+", " ", x).strip() for x in text.splitlines() if x.strip()]

    team = None

    for i, line in enumerate(lines):
        if line == "Out of Possession" and i + 1 < len(lines):
            team = lines[i + 1]
            break

    if team is None:
        m = re.search(r"Out of Possession\s+([^\n]+)", text)
        team = m.group(1).strip() if m else ""

    words = page.get_text("words")

    hash_words = [w for w in words if w[4] == "#"]

    if not hash_words:
        raise ValueError("Could not find out-of-possession table header.")

    header_y = (hash_words[0][1] + hash_words[0][3]) / 2
    header_words = sorted(
        (w for w in words if abs((w[1] + w[3]) / 2 - header_y) < 10),
        key=lambda w: w[0],
    )

    # Map each column to the x-center of its identifying header word.
    column_centers = {}

    for column, keyword, occurrence in OOP_HEADERS:
        matches = [w for w in header_words if w[4] == keyword]

        if len(matches) > occurrence:
            word = matches[occurrence]
            column_centers[column] = (word[0] + word[2]) / 2

    for column in ("tackles", "pressing_direct", "possession_interrupted"):
        if column not in column_centers:
            raise ValueError(f"Missing out-of-possession header for {column}.")

    rows = group_words_into_rows(words, x_min=15, x_max=945, tolerance=2.5)

    output = []

    for row in rows:
        y_center = sum((w[1] + w[3]) / 2 for w in row) / len(row)

        if y_center <= header_y + 10:
            continue

        shirt_words = [
            w for w in row if w[0] < 35 and re.fullmatch(r"\d{1,2}", w[4])
        ]

        if not shirt_words:
            continue

        shirt_number = int(shirt_words[0][4])

        cells = {column: [] for column in column_centers}

        for word in row:
            x_center = (word[0] + word[2]) / 2

            # The player name column ends before the first stat column.
            if word[0] < 35 or x_center < column_centers["tackles"] - 30:
                continue
            if not re.fullmatch(r"\d+|/", word[4]):
                continue

            column = min(
                column_centers,
                key=lambda c: abs(column_centers[c] - x_center),
            )
            cells[column].append(word[4])

        values = {column: None for column in OOP_COLUMNS}

        cells.pop("forced_turnovers", None)

        m = re.fullmatch(r"(\d+)/(\d+)", "".join(cells.pop("tackles")))

        if m:
            values["tackles_made"] = int(m.group(1))
            values["tackles_won"] = int(m.group(2))

        for column, tokens in cells.items():
            # Adjacent digit tokens are rejoined in case PDF tokenization
            # split a multi-digit value.
            if tokens:
                values[column] = int("".join(tokens))

        output.append({"shirt_number": shirt_number, **values})

    return team, output


def parse_pdf(path: Path) -> list[dict]:
    """Parse one match-report PDF into player-match rows."""
    doc = fitz.open(path)

    metadata = parse_cover(doc)
    duration = detect_match_duration(doc)

    left_players = parse_lineup_side(doc[1], "left", duration)
    right_players = parse_lineup_side(doc[1], "right", duration)

    lineup = {
        metadata["team1"]: {p["shirt_number"]: p for p in left_players},
        metadata["team2"]: {p["shirt_number"]: p for p in right_players},
    }

    physical_pages = []

    for page_index, page in enumerate(doc):
        if "Physical Data" not in page.get_text("text"):
            continue

        team_name, physical_rows = parse_physical_page(page)

        if physical_rows:
            physical_pages.append((page_index + 1, team_name, physical_rows))

    if len(physical_pages) != 2:
        raise ValueError(
            f"Expected 2 physical-data pages; found {len(physical_pages)}."
        )

    teams = [metadata["team1"], metadata["team2"]]

    def match_team(extracted_team: str, index: int) -> str:
        normalized_extracted = normalize_id(extracted_team)
        return next(
            (t for t in teams if normalize_id(t) == normalized_extracted),
            teams[index],
        )

    oop = {}

    for page_index, page in enumerate(doc):
        if not page.get_text("text").lstrip().startswith("Out of Possession"):
            continue

        team_name, oop_rows = parse_oop_page(page)
        team = match_team(team_name, len(oop))
        oop[team] = (
            page_index + 1,
            {r["shirt_number"]: r for r in oop_rows},
        )

    if len(oop) != 2:
        raise ValueError(
            f"Expected 2 out-of-possession pages; found {len(oop)}."
        )

    output = []

    for index, (page_number, extracted_team, physical_rows) in enumerate(
        physical_pages
    ):
        team = match_team(extracted_team, index)
        oop_page, oop_by_shirt = oop.get(team, (None, {}))

        opponent = (
            metadata["team2"]
            if team == metadata["team1"]
            else metadata["team1"]
        )

        if team == metadata["team1"]:
            team_goals = metadata["score1"]
            opponent_goals = metadata["score2"]
        else:
            team_goals = metadata["score2"]
            opponent_goals = metadata["score1"]

        lineup_by_shirt = lineup.get(team, {})

        for physical in physical_rows:
            lineup_player = lineup_by_shirt.get(physical["shirt_number"])
            qc = []

            if lineup_player is None:
                position = None
                starter = None
                sub_on = None
                sub_off = None
                sent_off = None
                minutes_played = None
                qc.append("lineup_not_matched")
            else:
                position = lineup_player["position"]
                starter = lineup_player["starter"]
                sub_on = lineup_player["sub_on_minute"]
                sub_off = lineup_player["sub_off_minute"]
                sent_off = lineup_player["sent_off_minute"]
                minutes_played = lineup_player["minutes_played"]

                if lineup_player["substitution_icon_unrecognized"]:
                    qc.append("substitution_icon_unrecognized")

                if not starter and sub_on is None:
                    qc.append("substitute_entry_not_inferred")

                if minutes_played is not None and minutes_played <= 0:
                    qc.append("nonpositive_minutes_played")

            oop_player = oop_by_shirt.get(physical["shirt_number"])

            if oop_player is None:
                oop_player = {column: None for column in OOP_COLUMNS}
                qc.append("oop_not_matched")

            # Keep the FIFA physical-table name exactly as extracted apart
            # from whitespace normalization; no duplicate/canonical name field.
            player_name = physical["player_name"]

            row = {
                "tournament_year": metadata["tournament_year"],
                "match_id": metadata["match_id"],
                "fifa_match_number": metadata["fifa_match_number"],
                "stage": metadata["stage"],
                "stage_type": metadata["stage_type"],
                "group": metadata["group"],
                "match_date": metadata["match_date"],
                "kickoff_time_local": metadata["kickoff_time_local"],
                "stadium": metadata["stadium"],
                "team": team,
                "opponent": opponent,
                "team_goals": team_goals,
                "opponent_goals": opponent_goals,
                "team_tournament_id": (
                    f"{metadata['tournament_year']}_{normalize_id(team)}"
                ),
                "player_name": player_name,
                "player_tournament_id": (
                    f"{metadata['tournament_year']}_"
                    f"{normalize_id(team)}_{normalize_id(player_name)}_"
                    f"{physical['shirt_number']}"
                ),
                "shirt_number": physical["shirt_number"],
                "position": position,
                "starter": int(starter) if starter is not None else None,
                "sub_on_minute": sub_on,
                "sub_off_minute": sub_off,
                "sent_off_minute": sent_off,
                "match_duration_min": duration,
                "minutes_played": minutes_played,
                "total_distance_m": physical["total_distance_m"],
                "zone1_distance_m": physical["zone1_distance_m"],
                "zone2_distance_m": physical["zone2_distance_m"],
                "zone3_distance_m": physical["zone3_distance_m"],
                "zone4_distance_m": physical["zone4_distance_m"],
                "zone5_distance_m": physical["zone5_distance_m"],
                "high_speed_runs": physical["high_speed_runs"],
                "sprints": physical["sprints"],
                "top_speed_kmh": physical["top_speed_kmh"],
                "high_speed_runs_definition": physical[
                    "high_speed_runs_definition"
                ],
                "sprints_definition": physical["sprints_definition"],
                **{column: oop_player[column] for column in OOP_COLUMNS},
                "source_pdf": path.name,
                "lineup_page": 2,
                "physical_page": page_number,
                "oop_page": oop_page,
                "qc_flag": ";".join(qc),
            }

            output.append(row)

    doc.close()
    return output


def collect_pdfs(directory: Path, recursive: bool) -> list[Path]:
    pattern = "**/*.pdf" if recursive else "*.pdf"
    return sorted(p for p in directory.glob(pattern) if p.is_file())


def main():
    missing_dirs = [directory for directory in MATCH_REPORT_DIRS if not directory.is_dir()]
    if missing_dirs:
        missing = ", ".join(str(directory) for directory in missing_dirs)
        raise FileNotFoundError(f"Input director{'y is' if len(missing_dirs) == 1 else 'ies are'} missing: {missing}")

    pdfs = []
    for directory in MATCH_REPORT_DIRS:
        found = collect_pdfs(directory, RECURSIVE)
        print(
            f"Found {len(found)} PDF(s) in {directory}",
            file=sys.stderr,
        )
        pdfs.extend(found)

    if not pdfs:
        directories = ", ".join(str(directory) for directory in MATCH_REPORT_DIRS)
        raise FileNotFoundError(f"No PDF files found in: {directories}")

    all_rows = []
    failures = []

    for i, pdf in enumerate(pdfs, start=1):
        print(f"[{i}/{len(pdfs)}] {pdf}", file=sys.stderr)

        try:
            rows = parse_pdf(pdf)
            all_rows.extend(rows)
            print(f"    extracted {len(rows)} player rows", file=sys.stderr)
        except Exception as exc:
            message = f"{pdf}: {exc}"
            failures.append(message)
            print(f"    ERROR: {exc}", file=sys.stderr)

            if STRICT:
                raise

    if not all_rows:
        raise RuntimeError("No player rows were extracted.")

    OUTPUT_FILE.parent.mkdir(parents=True, exist_ok=True)

    with OUTPUT_FILE.open("w", newline="", encoding="utf-8-sig") as f:
        writer = csv.DictWriter(f, fieldnames=OUTPUT_COLUMNS)
        writer.writeheader()
        writer.writerows(all_rows)

    qc_count = sum(bool(row["qc_flag"]) for row in all_rows)

    print(
        f"\nWrote {len(all_rows)} rows to {OUTPUT_FILE}",
        file=sys.stderr,
    )
    print(
        f"Rows with QC flags: {qc_count}",
        file=sys.stderr,
    )

    if failures:
        print(
            f"PDFs that failed: {len(failures)}",
            file=sys.stderr,
        )
        for failure in failures:
            print(f"  - {failure}", file=sys.stderr)


if __name__ == "__main__":
    main()
