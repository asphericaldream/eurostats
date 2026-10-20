import pandas as pd
import pytest

from eurostats.trends import results_trends, season_label


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
