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


def team_trends(traditional: pd.DataFrame) -> pd.DataFrame:
    """Pace, shot mix and efficiency for each season, league-wide.

    Expects the accumulated team totals (all phases) the fetch step saves as
    team_traditional. Rates are computed from league totals rather than by
    averaging team percentages, so every possession counts the same.
    """
    totals = traditional.groupby("season")[[
        "minutesPlayed", "pointsScored",
        "twoPointersMade", "twoPointersAttempted",
        "threePointersMade", "threePointersAttempted",
        "freeThrowsAttempted", "offensiveRebounds", "turnovers",
    ]].sum()

    fga = totals["twoPointersAttempted"] + totals["threePointersAttempted"]
    fgm = totals["twoPointersMade"] + totals["threePointersMade"]
    # Standard possession estimate (Oliver): FGA + 0.44 FTA - OREB + TOV.
    possessions = (fga + 0.44 * totals["freeThrowsAttempted"]
                   - totals["offensiveRebounds"] + totals["turnovers"])

    trends = pd.DataFrame({
        # minutesPlayed is team minutes (40 per regulation game), so this is
        # possessions per team per 40 minutes and handles overtime.
        "pace": possessions / totals["minutesPlayed"] * 40,
        "offensive_rating": totals["pointsScored"] / possessions * 100,
        "three_point_rate": totals["threePointersAttempted"] / fga * 100,
        "three_point_pct": totals["threePointersMade"] / totals["threePointersAttempted"] * 100,
        "effective_fg_pct": (fgm + 0.5 * totals["threePointersMade"]) / fga * 100,
        "free_throw_rate": totals["freeThrowsAttempted"] / fga * 100,
    }).reset_index()
    trends["label"] = trends["season"].map(season_label)
    return trends
