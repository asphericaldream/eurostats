from eurostats.flatten_history import (
    awards_from_table,
    clean,
    parse_season,
    places_from_table,
    split_header,
    table_grids,
    titles_from_table,
)

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
    awards_from_table("mvp", {"title": "EuroLeague MVP"}, names, rows, 0, qids, tables,
                      {"Q1": {"player": "ABC"}})
    got = [(a["season"], a["name"], a["player_code"], a["club_qid"]) for a in tables["awards"]]
    assert got == [(2004, "Anthony Parker", "ABC", "Q3"), (2004, "Player X", None, None)]


FINALS = """
<table class="wikitable">
<tr><th>Season</th><th>Champion</th><th>Runner-up</th><th>1st game / Final</th><th>2nd game</th></tr>
<tr><th rowspan="2"><a href="/a" title="2000–01 FIBA SuproLeague">2000–01</a>
    <a href="/b" title="2001 FIBA SuproLeague Final Four">Details</a>
    <a href="/c" title="2000–01 Euroleague">2000</a></th>
    <td><a href="/m" title="Maccabi Tel Aviv B.C.">Maccabi</a> †</td><td>Panathinaikos</td>
    <td>81 –67</td><td>–</td></tr>
<tr><td>Kinder Bologna (2×)</td><td>Tau Cerámica</td><td>*68– 85</td><td>*94–73</td></tr>
</table>
<table class="wikitable">
<tr><th>Year</th><th>Champion</th><th>Runner-up</th><th>Third place</th><th>Fourth place</th></tr>
<tr><th colspan="5">FIBA European League Final Four</th></tr>
<tr><th>1992</th><td>Partizan</td><td>Joventut</td><td>Philips Milano</td><td>Estudiantes</td></tr>
<tr><th>2020</th><td colspan="4">Cancelled due to COVID-19</td></tr>
</table>
"""


def test_titles_split_2000_01_between_both_competitions():
    finals, _ = table_grids(FINALS)
    names, rows = split_header(finals)
    tables = {"titles": []}
    titles_from_table({"title": "Finals"}, names, rows, 0, {"Maccabi Tel Aviv B.C.": "Q1"}, tables)
    got = [(t["competition"], t["champion"], t["champion_qid"], t["games"], t["final_score"])
           for t in tables["titles"]]
    assert got == [("2000–01 FIBA SuproLeague", "Maccabi", "Q1", 1, "81–67"),
                   ("2000–01 Euroleague", "Kinder Bologna", None, 2, "*68–85; *94–73")]


def test_final_four_places_keep_section_and_skip_cancelled():
    _, final_four = table_grids(FINALS)
    names, rows = split_header(final_four)
    assert names[1] == "Champion"
    tables = {"final_four_places": []}
    places_from_table({"title": "Final Four"}, names, rows, 0, {}, tables)
    got = [(p["season"], p["place"], p["club"], p["competition"]) for p in tables["final_four_places"]]
    assert got[0] == (1991, 1, "Partizan", "FIBA European League Final Four")
    assert len(got) == 4


def test_clean_drops_marks_and_counts():
    assert clean("Toni Kukoč (2x)") == "Toni Kukoč"
    assert clean("Maccabi Elite Tel Aviv ‡") == "Maccabi Elite Tel Aviv"
    assert clean("Bob McAdoo *") == "Bob McAdoo"
