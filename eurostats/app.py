"""The website. Run with: python -m eurostats.app"""
import plotly.graph_objects as go
from nicegui import ui

from eurostats.fetch import load_raw
from eurostats.trends import results_trends, team_trends

LINE_COLOR = "#2a78d6"
GRID_COLOR = "#e4e3dc"


def line_chart(x, y, title: str, y_title: str, value_format: str) -> go.Figure:
    fig = go.Figure(go.Scatter(
        x=x, y=y, mode="lines+markers",
        line=dict(color=LINE_COLOR, width=2),
        marker=dict(color=LINE_COLOR, size=8),
        hovertemplate=f"%{{x}}<br>%{{y:{value_format}}}<extra></extra>",
    ))
    fig.update_layout(
        title=title,
        yaxis_title=y_title,
        margin=dict(l=50, r=20, t=50, b=40),
        height=320,
        plot_bgcolor="white",
        hovermode="x",
    )
    # Labels like "2007-08" would otherwise be read as dates (August 2007).
    fig.update_xaxes(type="category", showgrid=False, tickangle=-45, nticks=13)
    fig.update_yaxes(gridcolor=GRID_COLOR, zeroline=False)
    return fig


def chart_card(fig: go.Figure, note: str) -> None:
    with ui.column().classes("w-full md:w-[48%] gap-0"):
        ui.plotly(fig).classes("w-full")
        ui.label(note).classes("text-sm text-gray-600 px-2")


@ui.page("/")
def home() -> None:
    results = load_raw("results")
    traditional = load_raw("team_traditional")
    if results.empty or traditional.empty:
        ui.label("How EuroLeague changed").classes("text-3xl font-bold")
        ui.label("No data yet. Run `python -m eurostats.fetch` first.")
        return

    games = results_trends(results)
    teams = team_trends(traditional)
    first, last = games["label"].iloc[0], games["label"].iloc[-1]

    ui.label(f"How EuroLeague changed since {first[:4]}").classes("text-3xl font-bold")
    ui.label(
        f"League-wide trends for every season from {first} to {last}, "
        "counting every game played in all phases. 2019-20 was stopped "
        "after the regular season."
    ).classes("text-gray-700")

    with ui.row().classes("w-full"):
        chart_card(
            line_chart(games["label"], games["points_per_game"],
                       "Points per team per game", "Points", ".1f"),
            "Average points each team scores in a game.",
        )
        chart_card(
            line_chart(teams["label"], teams["pace"],
                       "Pace", "Possessions per 40 min", ".1f"),
            "Estimated possessions per team per 40 minutes "
            "(FGA + 0.44 FTA - offensive rebounds + turnovers).",
        )
        chart_card(
            line_chart(teams["label"], teams["three_point_rate"],
                       "Share of shots from three", "3PA / FGA (%)", ".1f"),
            "Three-point attempts as a share of all field-goal attempts.",
        )
        chart_card(
            line_chart(teams["label"], teams["offensive_rating"],
                       "Offensive efficiency", "Points per 100 possessions", ".1f"),
            "Points scored per 100 estimated possessions, league-wide.",
        )
        chart_card(
            line_chart(teams["label"], teams["three_point_pct"],
                       "Three-point accuracy", "3P%", ".1f"),
            "Made threes divided by attempted threes.",
        )
        chart_card(
            line_chart(games["label"], games["home_win_pct"],
                       "Home-court advantage", "Home wins (%)", ".1f"),
            "Share of games the home team won. Final Four games count as home "
            "games for the team listed first.",
        )

    ui.label(
        "Statistics: Euroleague Basketball public stats feed. "
        "A free, non-commercial fan project."
    ).classes("text-xs text-gray-500 mt-4")


if __name__ in {"__main__", "__mp_main__"}:
    ui.run(title="EuroLeague History & Trends")
