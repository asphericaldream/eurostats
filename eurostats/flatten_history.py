"""Turn the history downloads into CSV tables ready for a data model.

Usage:
    python -m eurostats.flatten_history --out data/csv \
        --results data/raw/results.csv

Tables from the EuroLeague feed (2000-01 on), one row per ...:
    season_phases.csv          phase of a season: regular season, Top 16,
                               play-in, playoffs, Final Four; dates, rounds,
                               number of groups and teams
    season_rounds.csv          round of a season: phase, name, dates
    standings.csv              club in a group phase: final position, record,
                               points for and against, home and away record
    season_finish.csv          club in a season: last phase and round played,
                               final place (1 to 4 where known), who knocked
                               it out
    final_four_games.csv       Final Four game: semifinal, third place or final
    player_bios.csv            player: name, birth date and country,
                               nationality, height, weight, latest position
    player_registrations.csv   player on a club's roster in a season: shirt
                               number, position, height and weight then,
                               registration dates

Tables from Wikipedia and Wikidata (all years, 1957-58 on), one row per ...:
    titles.csv                 final: champion, runner-up, the score of each
                               game (* marks the home team), host city;
                               2000-01 has two (SuproLeague and Euroleague)
    final_four_places.csv      club in a Final Four tournament: place 1 to 4
                               (1966-67 to 1967-68, then 1987-88 on)
    awards.csv                 award to a player or coach in a season:
                               mvp, final_four_mvp, all_euroleague (detail
                               says first or second team), coach_of_the_year,
                               rising_star, and from the finals list
                               finals_mvp, finals_top_scorer (detail: points)
                               and champion_coach
    wiki_tables.csv            every cell of every table on those pages, as
                               downloaded, for anything the tables above miss
    wikidata_codes.csv         Wikidata item to EuroLeague player or coach code

Club and player codes are the feed's, the same as in the box score tables.
Wikipedia rows carry the linked page's Wikidata ID (QID) and, for players,
the feed player code when Wikidata records it. Clubs before 2000 have no feed
code; match them on QID.

Seasons are named by the year they start (2000 = 2000-01), like the feed.
"""
import argparse
import csv
import gzip
import json
import re
from collections import Counter, defaultdict
from pathlib import Path

import pandas as pd

from eurostats.fetch_history import (COMPETITION, HISTORY_DIR, PEOPLE_DIRS,
                                     WIKI_PAGES, items, load)

FEED_DIR = HISTORY_DIR / "feed"
WIKI_DIR = HISTORY_DIR / "wikipedia"
WIKIDATA_DIR = HISTORY_DIR / "wikidata"


def feed_file(season: int, kind: str):
    for directory in (FEED_DIR, *PEOPLE_DIRS):
        path = directory / f"{COMPETITION}{season}_{kind}.json.gz"
        if path.exists():
            return load(path)
    return None


def feed_seasons() -> list:
    return sorted(int(p.name[len(COMPETITION):len(COMPETITION) + 4])
                  for p in FEED_DIR.glob(f"{COMPETITION}*_phases.json.gz"))


# ---------------------------------------------------------------- feed ---

def standings_files(season: int) -> dict:
    """{phase code: standings} for the last round of each group phase."""
    found = {}
    for path in FEED_DIR.glob(f"{COMPETITION}{season}_standings_*.json.gz"):
        phase = path.name.split("_")[2]
        found[phase] = load(path)
    return found


def season_tables(results: pd.DataFrame, tables: dict) -> None:
    for season in feed_seasons():
        phases = items(feed_file(season, "phases"))
        rounds = items(feed_file(season, "rounds"))
        standings = standings_files(season)
        played = results[results["season"] == season]
        for r in sorted(rounds, key=lambda r: r["round"]):
            tables["season_rounds"].append({
                "season": season,
                "phase_code": r["phaseTypeCode"],
                "round": r["round"],
                "name": r["name"],
                "start_date": r["minGameStartDate"][:10],
                "end_date": r["maxGameStartDate"][:10],
            })
        for p in sorted(phases, key=lambda p: p["order"]):
            code = p["phaseType"]["code"]
            phase_rounds = [r["round"] for r in rounds if r["phaseTypeCode"] == code]
            games = played[played["Phase"] == code]
            teams = standings.get(code, {}).get("teams", [])
            tables["season_phases"].append({
                "season": season,
                "phase_code": code,
                "phase_name": p["phaseType"]["name"],
                "phase_order": p["order"],
                "is_group_phase": p["phaseType"]["isGroupPhase"],
                # The feed lists some phases that were never played, such as
                # 2000-01 eighthfinals (played inside the playoffs).
                "has_games": p["hasGames"],
                "start_date": (p.get("startDate") or "")[:10] or None,
                "end_date": (p.get("endDate") or "")[:10] or None,
                "first_round": min(phase_rounds, default=None),
                "last_round": max(phase_rounds, default=None),
                "round_count": len(phase_rounds),
                "group_count": len({t["groupName"] for t in teams}) or None,
                "team_count": len(set(games["homecode"]) | set(games["awaycode"])) or None,
                "game_count": len(games),
            })
        for phase, data in standings.items():
            for t in data["teams"]:
                tables["standings"].append({
                    "season": season,
                    "phase_code": phase,
                    "group": t["groupName"],
                    "position": t["position"],
                    "club_code": t["club"]["code"],
                    "club_name": t["club"]["name"],
                    "games_played": t["gamesPlayed"],
                    "won": t["gamesWon"],
                    "lost": t["gamesLost"],
                    "points_for": t["pointsFor"],
                    "points_against": t["pointsAgainst"],
                    "home_record": t["homeRecord"],
                    "away_record": t["awayRecord"],
                    "neutral_record": t["neutralRecord"],
                    "overtime_record": t["overtimeRecord"],
                    # Only filled in for recent seasons; false everywhere before.
                    "qualified": t["qualified"],
                })
        winner = next((d["winner"]["code"] for d in standings.values()
                       if d.get("winner")), None)
        finish_rows(season, played, phases, rounds, winner, tables)


def finish_rows(season, played, phases, rounds, champion, tables) -> None:
    order = {p["phaseType"]["code"]: p["order"] for p in phases}
    round_names = {r["round"]: r["name"] for r in rounds}
    games = played.assign(order=played["Phase"].map(order)).sort_values(
        ["order", "Round", "gameCode"])
    games = games.assign(winner=games["homecode"].where(
        games["homescore"] > games["awayscore"], games["awaycode"]))
    places = {}
    if champion is not None:
        places[champion] = 1
        final = games[(games["homecode"] == champion) | (games["awaycode"] == champion)].iloc[-1]
        runner_up = final["awaycode"] if final["homecode"] == champion else final["homecode"]
        places[runner_up] = 2
        ff = games[games["Phase"] == "FF"]
        if len(ff):
            last_round = ff[ff["Round"] == ff["Round"].max()]
            for _, game in last_round.iterrows():
                is_final = champion in (game["homecode"], game["awaycode"])
                if not is_final:
                    loser = game["awaycode"] if game["winner"] == game["homecode"] else game["homecode"]
                    places[game["winner"]], places[loser] = 3, 4
            for _, game in ff.iterrows():
                if game["Round"] == ff["Round"].max():
                    stage = "Final" if champion in (game["homecode"], game["awaycode"]) else "Third place"
                else:
                    stage = round_names.get(game["Round"], "Semifinal")
                tables["final_four_games"].append({
                    "season": season,
                    "game_code": game["gameCode"],
                    "stage": stage,
                    "home_club_code": game["homecode"],
                    "home_score": game["homescore"],
                    "away_club_code": game["awaycode"],
                    "away_score": game["awayscore"],
                    "winner_club_code": game["winner"],
                })
            # Seasons without a third-place game share third place.
            for club in set(ff["homecode"]) | set(ff["awaycode"]):
                places.setdefault(club, 3)
    for club in sorted(set(games["homecode"]) | set(games["awaycode"])):
        mine = games[(games["homecode"] == club) | (games["awaycode"] == club)]
        last = mine.iloc[-1]
        knocked_out_by = None
        if order.get(last["Phase"], 0) > 1 and last["winner"] != club:
            knocked_out_by = last["winner"]
        tables["season_finish"].append({
            "season": season,
            "club_code": club,
            "games": len(mine),
            "won": int((mine["winner"] == club).sum()),
            "last_phase_code": last["Phase"],
            "last_round": last["Round"],
            "last_round_name": round_names.get(last["Round"]),
            "final_place": places.get(club),
            "champion": club == champion,
            "knocked_out_by_club_code": knocked_out_by,
        })


PERSON_FIELDS = {
    "name": lambda p: p["name"],
    "passport_name": lambda p: p.get("passportName"),
    "passport_surname": lambda p: p.get("passportSurname"),
    "birth_date": lambda p: (p.get("birthDate") or "")[:10] or None,
    "birth_country_code": lambda p: (p.get("birthCountry") or {}).get("code"),
    "country_code": lambda p: (p.get("country") or {}).get("code"),
    "country_name": lambda p: (p.get("country") or {}).get("name"),
    "height_cm": lambda p: p.get("height") or None,
    "weight_kg": lambda p: p.get("weight") or None,
}


def player_tables(tables: dict) -> None:
    """Bios from each season's people list; type J is a player."""
    bios = {}
    for season in feed_seasons():
        for entry in items(feed_file(season, "people")):
            if entry["type"] != "J":
                continue
            person = entry["person"]
            code = person["code"]
            tables["player_registrations"].append({
                "season": season,
                "player_code": code,
                "club_code": entry["club"]["code"],
                "dorsal": entry.get("dorsal"),
                "position": entry.get("positionName"),
                "height_cm": person.get("height") or None,
                "weight_kg": person.get("weight") or None,
                "start_date": (entry.get("startDate") or "")[:10] or None,
                "end_date": (entry.get("endDate") or "")[:10] or None,
                "active": entry.get("active"),
            })
            bio = bios.setdefault(code, {"player_code": code, "first_season": season})
            bio["last_season"] = season
            # Later seasons win, but a missing value never hides a known one.
            for field, get in PERSON_FIELDS.items():
                value = get(person)
                if value not in (None, ""):
                    bio[field] = value
            if entry.get("positionName"):
                bio["position"] = entry["positionName"]
    for bio in bios.values():
        tables["player_bios"].append({
            "player_code": bio["player_code"],
            **{field: bio.get(field) for field in PERSON_FIELDS},
            "position": bio.get("position"),
            "first_season": bio["first_season"],
            "last_season": bio["last_season"],
        })


# ---------------------------------------------------------- wikipedia ---

def wiki_page(key: str):
    path = WIKI_DIR / f"{key}.json.gz"
    if not path.exists():
        return None
    data = load(path)
    return data.get("parse")


def table_grids(html: str) -> list:
    """Each wikitable as a grid of cells, with rowspan and colspan filled in.

    A cell is {"text", "links", "header"}; links are linked page titles.
    """
    from bs4 import BeautifulSoup

    soup = BeautifulSoup(html, "lxml")
    grids = []
    for table in soup.select("table.wikitable"):
        grid, pending = [], {}
        for tr in table.find_all("tr"):
            row, col = [], 0
            cells = tr.find_all(["th", "td"], recursive=False)
            while cells or col in pending:
                if col in pending:
                    cell, left = pending[col]
                    row.append(cell)
                    if left > 1:
                        pending[col] = (cell, left - 1)
                    else:
                        del pending[col]
                    col += 1
                    continue
                tag = cells.pop(0)
                for sup in tag.select("sup.reference"):
                    sup.decompose()
                cell = {
                    "text": " ".join(tag.get_text(" ", strip=True).split()),
                    "links": [a["title"] for a in tag.select("a[title]")
                              if not a.get("href", "").startswith("#")
                              and "redlink=1" not in a.get("href", "")],
                    "header": tag.name == "th",
                }
                span = int(re.sub(r"\D", "", tag.get("colspan", "1")) or 1)
                down = int(re.sub(r"\D", "", tag.get("rowspan", "1")) or 1)
                for _ in range(span):
                    row.append(cell)
                    if down > 1:
                        pending[col] = (cell, down - 1)
                    col += 1
            if row:
                grid.append(row)
        grids.append(grid)
    return grids


def section_row(row: list) -> bool:
    """A row that is one cell across the whole table, naming what follows."""
    return len(row) > 1 and len({id(c) for c in row}) == 1


def split_header(grid: list) -> tuple:
    """Header names (joined across header rows) and the data rows.

    Section rows stay in the data rows; see section_row.
    """
    head = []
    while grid and all(c["header"] for c in grid[0]) and not (head and section_row(grid[0])):
        head.append(grid[0])
        grid = grid[1:]
    width = max((len(r) for r in head + grid), default=0)
    names = []
    for i in range(width):
        parts = [r[i]["text"] for r in head if i < len(r) and r[i]["text"]]
        names.append(" / ".join(dict.fromkeys(parts)))
    return names, grid


SEASON = re.compile(r"\b(19[5-9]\d|20\d\d)\s*[–\-/]\s*(\d{2,4})\b")
YEAR = re.compile(r"\b(19[5-9]\d|20\d\d)\b")


def parse_season(text: str):
    """1957–58 -> 1957. A bare year is the year the season ended."""
    if not text:
        return None
    match = SEASON.search(text)
    if match:
        return int(match.group(1))
    match = YEAR.search(text)
    return int(match.group(1)) - 1 if match else None


def wiki_link_titles() -> set:
    titles = set()
    for key in WIKI_PAGES:
        page = wiki_page(key)
        if page:
            for grid in table_grids(page["text"]):
                titles.update(t for row in grid for c in row for t in c["links"])
    return titles


def qid_map() -> dict:
    """Linked page title -> Wikidata ID, following redirects."""
    qids = {}
    for path in sorted(WIKIDATA_DIR.glob("article_qids_*.json.gz")):
        for row in load(path)["results"]["bindings"]:
            qids[row["title"]["value"]] = row["item"]["value"].rsplit("/", 1)[-1]
    for path in sorted((WIKI_DIR / "links").glob("*.json.gz")):
        link = load(path)
        if link.get("wikibase_item"):
            qids.setdefault(link["link"], link["wikibase_item"])
    return {t: q for t, q in qids.items() if q and q.startswith("Q")}


def wikidata_codes(tables: dict) -> dict:
    """QID -> {"player": feed code, "coach": feed code}, from Wikidata's
    euroleague.net player and coach IDs."""
    path = WIKIDATA_DIR / "euroleague_properties.json.gz"
    if not path.exists():
        return {}
    codes = defaultdict(dict)
    for prop in load(path)["results"]["bindings"]:
        pid = prop["property"]["value"].rsplit("/", 1)[-1]
        label = prop["label"]["value"].lower()
        kind = "player" if "player" in label else "coach" if "coach" in label else None
        values = WIKIDATA_DIR / f"{pid}_values.json.gz"
        if not kind or not values.exists():
            continue
        for row in load(values)["results"]["bindings"]:
            qid = row["item"]["value"].rsplit("/", 1)[-1]
            # euroleague.net IDs are the feed code in lower case, sometimes
            # with the live feed's leading "P".
            value = row["value"]["value"].strip()
            code = value[1:] if re.fullmatch(r"P\w+", value) and len(value) > 3 else value
            code = code.upper()
            tables["wikidata_codes"].append({
                "qid": qid, "name": row.get("itemLabel", {}).get("value"),
                "kind": kind, "code": code, "wikidata_property": pid,
                "wikidata_value": value})
            codes[qid].setdefault(kind, code)
    return codes


def column(names: list, *words, avoid=()) -> int | None:
    for i, name in enumerate(names):
        low = name.lower()
        if any(w in low for w in words) and not any(a in low for a in avoid):
            return i
    return None


MARKERS = re.compile(r"\s*(\(\d+(?:x|×)?\)|[*†‡§^#+]+|\(\d+×\))\s*")


def clean(text: str | None) -> str | None:
    """Drop the footnote marks and (2×) counts tables add to names."""
    if not text:
        return None
    text = MARKERS.sub(" ", text).strip(" –—")
    return " ".join(text.split()) or None


def cell_link(row, i, qids):
    """A cell's name, the page it links to and that page's Wikidata ID."""
    if i is None or i >= len(row):
        return None, None, None
    cell = row[i]
    # Flag links come first in some cells; the name is the last link.
    named = [t for t in cell["links"] if not t.lower().startswith(("flag of", "list of"))]
    title = named[-1] if named else None
    text = clean(cell["text"])
    if text and text.lower().startswith(("n/a", "cancelled", "not awarded")):
        return None, None, None
    return text, title, qids.get(title)


def wiki_tables(tables: dict) -> None:
    qids = qid_map()
    codes = wikidata_codes(tables)
    for key in WIKI_PAGES:
        page = wiki_page(key)
        if not page:
            continue
        for t, grid in enumerate(table_grids(page["text"])):
            names, rows = split_header(grid)
            for r, row in enumerate(rows):
                for c, cell in enumerate(row):
                    tables["wiki_tables"].append({
                        "page": page["title"], "revision": page["revid"],
                        "table": t, "row": r, "column": c,
                        "header": names[c] if c < len(names) else None,
                        "text": cell["text"],
                        "links": "|".join(cell["links"]) or None,
                        "qids": "|".join(filter(None, (qids.get(x) for x in cell["links"]))) or None,
                    })
            season_col = next((i for i, n in enumerate(names)
                               if n.split(" / ")[0].lower() in ("season", "seasons", "year")), None)
            if season_col is None:
                continue
            args = (page, names, rows, season_col, qids, tables)
            if key == "finals":
                if column(names, "runner") is not None:
                    titles_from_table(*args)
                else:
                    awards_from_table(key, *args, codes)
            elif key == "final_four":
                if column(names, "fourth") is not None:
                    places_from_table(*args)
            else:
                awards_from_table(key, *args, codes)


def season_rows(rows: list, season_col: int):
    """(season, section, row) for each data row; section rows set section."""
    section = None
    for row in rows:
        if section_row(row):
            section = row[0]["text"]
            continue
        season = parse_season(row[season_col]["text"]) if season_col < len(row) else None
        if season is not None:
            yield season, section, row


def titles_from_table(page, names, rows, season_col, qids, tables) -> None:
    """The champions list: one row per final (two for the split 2000-01)."""
    champ = column(names, "champion")
    runner = column(names, "runner")
    venue = column(names, "venue", "host", "location", "city")
    games = [i for i, n in enumerate(names) if "game" in n.lower() or n.lower().endswith("final")]
    shared = Counter()
    for season, section, row in season_rows(rows, season_col):
        c_text, c_title, c_qid = cell_link(row, champ, qids)
        if not c_text:
            continue
        r_text, r_title, r_qid = cell_link(row, runner, qids)
        scores = [re.sub(r"\s*([–-])\s*", "–", row[i]["text"]) for i in games if i < len(row)]
        scores = [x for x in scores if re.search(r"\d", x)]
        # 2000-01 had two competitions, so two rows share one season cell
        # that links both seasons' pages.
        season_cell = row[season_col]
        competitions = [t for t in season_cell["links"] if not re.search(r"final", t, re.IGNORECASE)]
        k = shared[id(season_cell)]
        shared[id(season_cell)] += 1
        tables["titles"].append({
            "season": season,
            "competition": competitions[min(k, len(competitions) - 1)] if competitions else section,
            "champion": c_text, "champion_wiki": c_title, "champion_qid": c_qid,
            "runner_up": r_text, "runner_up_wiki": r_title, "runner_up_qid": r_qid,
            "games": len(scores), "final_score": "; ".join(scores) or None,
            "host": cell_link(row, venue, qids)[0],
            "source": page["title"]})


def places_from_table(page, names, rows, season_col, qids, tables) -> None:
    """The Final Four list: places 1 to 4 of each Final Four tournament."""
    cols = {1: column(names, "champion"), 2: column(names, "runner"),
            3: column(names, "third"), 4: column(names, "fourth")}
    host = column(names, "host", "city")
    for season, section, row in season_rows(rows, season_col):
        for place, col in cols.items():
            text, title, qid = cell_link(row, col, qids)
            if text:
                tables["final_four_places"].append({
                    "season": season, "competition": section, "place": place,
                    "club": text, "club_wiki": title, "club_qid": qid,
                    "host_city": cell_link(row, host, qids)[0],
                    "source": page["title"]})


# Column headers naming an award winner, and the award to file them under
# when it differs from the page's. The club column follows the winner.
WINNER_COLUMNS = {"player": None, "head coach": None, "final four mvp": None,
                  "rising star": None, "top scorer": "finals_top_scorer",
                  "mvp": "finals_mvp", "champion coach": "champion_coach"}


def awards_from_table(key, page, names, rows, season_col, qids, tables, codes) -> None:
    """Award pages, and the finals page's top scorer, MVP and coach list."""
    last = [n.split(" / ")[-1].strip().lower() for n in names]
    winners = [i for i, n in enumerate(last) if n in WINNER_COLUMNS]
    for season, _, row in season_rows(rows, season_col):
        for i in winners:
            name, title, qid = cell_link(row, i, qids)
            if not name:
                continue
            club = next((j for j in range(i + 1, len(last))
                         if j in winners or last[j] in ("club", "team")), None)
            club = None if club in winners else club
            club_name, club_title, club_qid = cell_link(row, club, qids)
            award = (WINNER_COLUMNS[last[i]] if key == "finals" else None) or key
            group = names[i].split(" / ")[0] if " / " in names[i] else None
            points = None
            if award == "finals_top_scorer" and i + 2 < len(row):
                points = row[i + 2]["text"]
            code = codes.get(qid, {})
            tables["awards"].append({
                "award": award, "season": season, "detail": group or points,
                "name": name, "wiki": title, "qid": qid,
                "player_code": code.get("player"), "coach_code": code.get("coach"),
                "club": club_name, "club_wiki": club_title, "club_qid": club_qid,
                "source": page["title"]})


def write_csv(path: Path, rows: list) -> None:
    if not rows:
        print(f"skipped {path.name} (nothing downloaded for it yet)")
        return
    columns = list(dict.fromkeys(key for row in rows for key in row))
    with path.open("w", newline="", encoding="utf-8") as f:
        writer = csv.DictWriter(f, fieldnames=columns)
        writer.writeheader()
        writer.writerows(rows)
    print(f"wrote {path.name} ({len(rows)} rows)")


def load_results(path: Path | None) -> pd.DataFrame:
    if path:
        return pd.read_csv(path)
    from eurostats.fetch import load_raw
    return load_raw("results")


def main() -> None:
    parser = argparse.ArgumentParser(description=__doc__,
                                     formatter_class=argparse.RawDescriptionHelpFormatter)
    parser.add_argument("--out", type=Path,
                        default=Path(__file__).resolve().parent.parent / "data" / "csv")
    parser.add_argument("--results", type=Path,
                        help="results CSV; default is the parquet files from eurostats.fetch")
    args = parser.parse_args()

    tables = defaultdict(list)
    results = load_results(args.results)
    results = results[results["played"].astype(bool)]
    season_tables(results, tables)
    player_tables(tables)
    wiki_tables(tables)

    args.out.mkdir(parents=True, exist_ok=True)
    for name in ("season_phases", "season_rounds", "standings", "season_finish",
                 "final_four_games", "player_bios", "player_registrations",
                 "titles", "final_four_places", "awards", "wiki_tables",
                 "wikidata_codes"):
        write_csv(args.out / f"{name}.csv", tables[name])


if __name__ == "__main__":
    main()
