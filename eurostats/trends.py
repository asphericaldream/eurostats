"""League-wide season-by-season trends."""
import pandas as pd


def season_label(season: int) -> str:
    """2007 -> '2007-08'."""
    return f"{season}-{(season + 1) % 100:02d}"


def results_trends(results: pd.DataFrame) -> pd.DataFrame:
    """Points per game and home-court win % for each season.

    Expects the per-game results the fetch step saves: season, played,
    homescore, awayscore.
    """
    games = results[results["played"].astype(bool)].copy()
    games = games[(games["homescore"] > 0) | (games["awayscore"] > 0)]
    games["total_points"] = games["homescore"] + games["awayscore"]
    games["home_win"] = games["homescore"] > games["awayscore"]

    trends = games.groupby("season").agg(
        games=("total_points", "size"),
        points_per_game=("total_points", "mean"),
        home_win_pct=("home_win", "mean"),
    ).reset_index()
    # points_per_game is for both teams combined; report it per team.
    trends["points_per_game"] = trends["points_per_game"] / 2
    trends["home_win_pct"] = trends["home_win_pct"] * 100
    trends["label"] = trends["season"].map(season_label)
    return trends
