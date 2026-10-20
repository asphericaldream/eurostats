from eurostats.flatten_history import awards_from_table, parse_season, split_header, table_grids

HTML = """
<table class="wikitable">
<tr><th>Season</th><th>Player</th><th>Nationality</th><th>Team</th></tr>
<tr><td rowspan="2"><a href="/wiki/2004%E2%80%9305_Euroleague" title="2004–05 Euroleague">2004–05</a></td>
    <td><a href="/wiki/Anthony_Parker" title="Anthony Parker">Anthony Parker</a><sup class="reference">[1]</sup></td>
    <td><a href="/wiki/Flag" title="Flag of the United States">US</a></td>
    <td><a href="/wiki/Maccabi" title="Maccabi Tel Aviv B.C.">Maccabi Tel Aviv</a></td></tr>
<tr><td><a href="/wiki/X" title="Player X">Player X</a></td><td>ESP</td><td>Club Y</td></tr>
</table>
<table class="other"><tr><td>skip</td></tr></table>
"""


def test_table_grids_fill_rowspan_and_drop_footnotes():
    [grid] = table_grids(HTML)
    names, rows = split_header(grid)
    assert names == ["Season", "Player", "Nationality", "Team"]
    assert [r[0]["text"] for r in rows] == ["2004–05", "2004–05"]
    assert rows[0][1]["text"] == "Anthony Parker"


def test_parse_season():
    assert parse_season("1957–58") == 1957
    assert parse_season("2004-05 Euroleague") == 2004
    assert parse_season("1958") == 1957
    assert parse_season("—") is None


def test_awards_take_linked_people_not_flags_or_nationality():
    [grid] = table_grids(HTML)
    names, rows = split_header(grid)
    qids = {"Anthony Parker": "Q1", "Player X": "Q2", "Maccabi Tel Aviv B.C.": "Q3",
            "Flag of the United States": "Q4", "2004–05 Euroleague": "Q5"}
    tables = {"awards": []}
    awards_from_table("mvp", {"title": "EuroLeague MVP"}, names, rows, qids,
                      {"Q1": "ABC"}, tables)
    got = [(a["season"], a["name"], a["player_code"], a["club_qid"]) for a in tables["awards"]]
    assert got == [(2004, "Anthony Parker", "ABC", "Q3"), (2004, "Player X", None, None)]
