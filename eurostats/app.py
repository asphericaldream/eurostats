"""The website. Run with: python -m eurostats.app"""
import plotly.graph_objects as go
from nicegui import ui

from eurostats.fetch import load_raw
from eurostats.trends import results_trends


def line_chart(x, y, title: str, y_title: str) -> go.Figure:
    fig = go.Figure(go.Scatter(x=x, y=y, mode="lines+markers"))
    fig.update_layout(
        title=title,
        yaxis_title=y_title,
        margin=dict(l=40, r=20, t=50, b=40),
        height=320,
    )
    return fig


@ui.page("/")
def home() -> None:
    ui.label("How EuroLeague changed since 2007").classes("text-3xl font-bold")

    results = load_raw("results")
    if results.empty:
        ui.label("No data yet. Run `python -m eurostats.fetch` first.")
        return

    trends = results_trends(results)
    with ui.row().classes("w-full"):
        ui.plotly(line_chart(
            trends["label"], trends["points_per_game"],
            "Points per team per game", "Points",
        )).classes("w-full md:w-[48%]")
        ui.plotly(line_chart(
            trends["label"], trends["home_win_pct"],
            "Home-court advantage", "Home wins (%)",
        )).classes("w-full md:w-[48%]")


if __name__ in {"__main__", "__mp_main__"}:
    ui.run(title="EuroLeague History & Trends")
