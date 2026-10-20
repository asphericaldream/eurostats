"""Download EuroLeague season data and cache it under data/raw/.

Usage:
    python -m eurostats.fetch --from 2000 --to 2025

Each season costs three requests (results, traditional and advanced team
stats). Files already on disk are skipped, so re-running only fetches what
is missing.
"""
import argparse
import os
import time
from pathlib import Path

import pandas as pd
from euroleague_api.EuroLeagueData import EuroLeagueData
from euroleague_api.team_stats import TeamStats

RAW_DIR = Path(os.environ.get(
    "EUROSTATS_RAW_DIR",
    Path(__file__).resolve().parent.parent / "data" / "raw",
))
COMPETITION = "E"
PAUSE_SECONDS = 2.0


def raw_path(kind: str, season: int) -> Path:
    return RAW_DIR / f"{kind}_{COMPETITION}{season}.parquet"


def fetch_season(season: int) -> None:
    jobs = {
        "results": lambda: EuroLeagueData(COMPETITION).get_gamecodes_season(season),
        "team_traditional": lambda: TeamStats(COMPETITION).get_team_stats_single_season(
            "traditional", season, statistic_mode="Accumulated"),
        "team_advanced": lambda: TeamStats(COMPETITION).get_team_stats_single_season(
            "advanced", season, statistic_mode="Accumulated"),
    }
    for kind, job in jobs.items():
        path = raw_path(kind, season)
        if path.exists():
            continue
        df = job()
        # The feed includes club logo URLs; the site never shows logos.
        df = df.drop(columns=[c for c in df.columns if "imageUrl" in c])
        df.insert(0, "season", season)
        path.parent.mkdir(parents=True, exist_ok=True)
        df.to_parquet(path, index=False)
        print(f"saved {path.name} ({len(df)} rows)")
        time.sleep(PAUSE_SECONDS)


def load_raw(kind: str) -> pd.DataFrame:
    files = sorted(RAW_DIR.glob(f"{kind}_{COMPETITION}*.parquet"))
    if not files:
        return pd.DataFrame()
    return pd.concat((pd.read_parquet(f) for f in files), ignore_index=True)


def main() -> None:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--from", dest="start", type=int, default=2000)
    parser.add_argument("--to", dest="end", type=int, default=2025)
    args = parser.parse_args()
    for season in range(args.start, args.end + 1):
        fetch_season(season)


if __name__ == "__main__":
    main()
