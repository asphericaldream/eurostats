import pandas as pd
import pytest

from eurostats.trends import results_trends, season_label, team_trends


def test_season_label():
    assert season_label(2007) == "2007-08"
    assert season_label(2099) == "2099-00"


def test_results_trends_per_season():
    results = pd.DataFrame({
        "season":    [2007, 2007, 2007, 2008],
        "played":    [True, True, False, True],
        "homescore": [80, 70, 0, 90],
        "awayscore": [70, 76, 0, 60],
    })
    trends = results_trends(results).set_index("season")

    assert trends.loc[2007, "games"] == 2
    assert trends.loc[2007, "points_per_game"] == pytest.approx((150 + 146) / 4)
    assert trends.loc[2007, "home_win_pct"] == pytest.approx(50.0)
    assert trends.loc[2008, "home_win_pct"] == pytest.approx(100.0)
    assert trends.loc[2008, "label"] == "2008-09"


def test_team_trends_uses_league_totals():
    traditional = pd.DataFrame({
        "season": [2007, 2007],
        "minutesPlayed": [400, 400],
        "pointsScored": [800, 760],
        "twoPointersMade": [200, 180],
        "twoPointersAttempted": [400, 380],
        "threePointersMade": [80, 70],
        "threePointersAttempted": [220, 200],
        "freeThrowsAttempted": [200, 180],
        "offensiveRebounds": [100, 90],
        "turnovers": [150, 140],
    })
    row = team_trends(traditional).iloc[0]

    possessions = 1200 + 0.44 * 380 - 190 + 290
    assert row["pace"] == pytest.approx(possessions / 800 * 40)
    assert row["offensive_rating"] == pytest.approx(1560 / possessions * 100)
    assert row["three_point_rate"] == pytest.approx(420 / 1200 * 100)
    assert row["three_point_pct"] == pytest.approx(150 / 420 * 100)
    assert row["effective_fg_pct"] == pytest.approx((530 + 75) / 1200 * 100)
    assert row["label"] == "2007-08"


def test_box_score_rows_split_players_and_teams():
    from eurostats.flatten_games import box_score_rows

    def side(club, player):
        return {
            "coach": {"code": "C" + club, "name": "COACH"},
            "team": {"totalRebounds": 2},
            "total": {"points": 80},
            "players": [{
                "player": {"person": {"code": player, "name": "NAME"},
                           "club": {"code": club}, "positionName": "Guard"},
                "stats": {"points": 10, "dorsal": "4", "startFive": True},
            }],
        }

    tables = {"team_games": [], "player_games": [], "players": {}, "coaches": {}}
    box_score_rows(2007, 1, {"local": side("OLY", "P1"), "road": side("BAS", "P2")}, tables)

    assert [t["club_code"] for t in tables["team_games"]] == ["OLY", "BAS"]
    assert tables["team_games"][0]["points"] == 80
    assert tables["team_games"][0]["team_only_totalRebounds"] == 2
    assert tables["player_games"][1]["player_code"] == "P2"
    assert tables["player_games"][1]["is_home"] is False
    assert set(tables["players"]) == {"P1", "P2"}
