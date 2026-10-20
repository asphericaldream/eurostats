"""Turn the per-game JSON files into CSV tables ready for a data model.

Usage:
    python -m eurostats.flatten_games --out data/csv

Tables (one row per ...):
    games.csv          game: phase, round, date, teams, score by quarter,
                       attendance, venue and referee codes
    team_games.csv     team in a game: box score totals, team-only stats
                       (such as team rebounds) and the coach
    player_games.csv   player in a game: full box score line
    players.csv        player: name, birth date, height, country
    clubs.csv          club in a season: the name it played under that season
    venues.csv         venue: name, capacity, address
    referees.csv       referee: name, country
    coaches.csv        coach: name
"""
import argparse
import csv
from pathlib import Path

from eurostats.fetch import COMPETITION
from eurostats.fetch_games import GAMES_DIR, load_game

STAT_FIELDS = [
    "timePlayed", "valuation", "points",
    "fieldGoalsMade2", "fieldGoalsAttempted2",
    "fieldGoalsMade3", "fieldGoalsAttempted3",
    "freeThrowsMade", "freeThrowsAttempted",
    "fieldGoalsMadeTotal", "fieldGoalsAttemptedTotal",
    "totalRebounds", "defensiveRebounds", "offensiveRebounds",
    "assistances", "steals", "turnovers", "blocksFavour", "blocksAgainst",
    "foulsCommited", "foulsReceived", "plusMinus",
]


def stats_columns(stats: dict, prefix: str = "") -> dict:
    return {prefix + field: (stats or {}).get(field) for field in STAT_FIELDS}


def game_rows(season: int, code: int, game: dict, tables: dict) -> None:
    row = {
        "season": season,
        "game_code": code,
        "phase": game["phaseType"]["code"],
        "group": game["group"]["rawName"],
        "round": game["round"],
        "local_date": game["localDate"],
        "utc_date": game["utcDate"],
        "neutral_venue": game.get("isNeutralVenue"),
        "audience": game.get("audience"),
        "venue_code": (game.get("venue") or {}).get("code"),
    }
    for side, prefix in (("local", "home"), ("road", "away")):
        team = game[side]
        row[f"{prefix}_club_code"] = team["club"]["code"]
        row[f"{prefix}_score"] = team["score"]
        partials = team.get("partials") or {}
        for quarter in range(1, 5):
            row[f"{prefix}_q{quarter}"] = partials.get(f"partials{quarter}")
        extra = partials.get("extraPeriods") or {}
        row[f"{prefix}_overtime"] = sum(extra.values()) if extra else None
        tables["clubs"][(season, team["club"]["code"])] = {
            "season": season,
            "club_code": team["club"]["code"],
            "name": team["club"]["name"],
            "editorial_name": team["club"].get("editorialName"),
            "tv_code": team["club"].get("tvCode"),
        }
    for n in range(1, 5):
        referee = game.get(f"referee{n}")
        row[f"referee{n}_code"] = referee["code"] if referee else None
        if referee:
            tables["referees"][referee["code"]] = {
                "referee_code": referee["code"],
                "name": referee["name"],
                "country_code": (referee.get("country") or {}).get("code"),
            }
    venue = game.get("venue")
    if venue and venue.get("code"):
        tables["venues"][venue["code"]] = {
            "venue_code": venue["code"],
            "name": venue["name"],
            "capacity": venue.get("capacity"),
            "address": venue.get("address"),
        }
    tables["games"].append(row)


def box_score_rows(season: int, code: int, box: dict, tables: dict) -> None:
    for side in ("local", "road"):
        team = box[side]
        players = team["players"]
        club = players[0]["player"]["club"]["code"] if players else None
        coach = team.get("coach") or {}
        if coach.get("code"):
            tables["coaches"][coach["code"]] = {
                "coach_code": coach["code"], "name": coach["name"]}
        tables["team_games"].append({
            "season": season,
            "game_code": code,
            "club_code": club,
            "is_home": side == "local",
            "coach_code": coach.get("code"),
            **stats_columns(team["total"]),
            # Stats credited to the team rather than a player (team rebounds,
            # shot-clock turnovers and so on).
            **stats_columns(team.get("team"), prefix="team_only_"),
        })
        for entry in players:
            player = entry["player"]
            person = player["person"]
            stats = entry["stats"]
            tables["player_games"].append({
                "season": season,
                "game_code": code,
                "club_code": player["club"]["code"],
                "is_home": side == "local",
                "player_code": person["code"],
                "dorsal": stats.get("dorsal"),
                "starter": stats.get("startFive"),
                "position": player.get("positionName"),
                **stats_columns(stats),
            })
            tables["players"][person["code"]] = {
                "player_code": person["code"],
                "name": person["name"],
                "birth_date": (person.get("birthDate") or "")[:10] or None,
                "height_cm": person.get("height"),
                "country_code": (person.get("country") or {}).get("code"),
                "birth_country_code": (person.get("birthCountry") or {}).get("code"),
            }


def write_csv(path: Path, rows: list) -> None:
    columns = list(dict.fromkeys(key for row in rows for key in row))
    with path.open("w", newline="", encoding="utf-8") as f:
        writer = csv.DictWriter(f, fieldnames=columns)
        writer.writeheader()
        writer.writerows(rows)
    print(f"wrote {path.name} ({len(rows)} rows)")


def main() -> None:
    parser = argparse.ArgumentParser(description=__doc__,
                                     formatter_class=argparse.RawDescriptionHelpFormatter)
    parser.add_argument("--out", type=Path,
                        default=Path(__file__).resolve().parent.parent / "data" / "csv")
    args = parser.parse_args()

    tables = {name: [] for name in ("games", "team_games", "player_games")}
    tables |= {name: {} for name in ("players", "clubs", "venues", "referees", "coaches")}
    for season_dir in sorted(GAMES_DIR.glob(f"{COMPETITION}*")):
        season = int(season_dir.name[len(COMPETITION):])
        codes = sorted({int(p.name[:4]) for p in season_dir.glob("*.json.gz")})
        for code in codes:
            if (season_dir / f"{code:04d}_game.json.gz").exists():
                game_rows(season, code, load_game("game", season, code), tables)
            if (season_dir / f"{code:04d}_stats.json.gz").exists():
                box_score_rows(season, code, load_game("stats", season, code), tables)

    args.out.mkdir(parents=True, exist_ok=True)
    for name, rows in tables.items():
        write_csv(args.out / f"{name}.csv",
                  list(rows.values()) if isinstance(rows, dict) else rows)


if __name__ == "__main__":
    main()
