"""Plotly chart builders sharing one visual system.

Series colours (dark surface #14141c), validated with the dataviz palette
validator — all pairs pass CVD (ΔE ≥ 9.4) and normal-vision (ΔE ≥ 24.6)
floors and ≥ 3:1 contrast: violet, orange, aqua. At most three series per
chart. Reference lines (baseline/target) use neutral ink, never a series hue.
Missing data uses neutral grey ✕ markers with a legend entry, never colour alone.
"""

from __future__ import annotations

from collections.abc import Sequence
from datetime import date
from typing import Any

import plotly.graph_objects as go

SURFACE = "#14141c"
SERIES = ("#9085e9", "#d95926", "#199e70")
INK_PRIMARY = "#ecebf5"
INK_SECONDARY = "#b4b2cc"
INK_MUTED = "#8f8daa"
GRID = "#24233a"
MISSING = "#8f8daa"
CONFIG: dict[str, Any] = {"displaylogo": False, "responsive": True,
                          "modeBarButtonsToRemove": ["lasso2d", "select2d", "autoScale2d"]}


def base_layout(fig: go.Figure, *, title: str | None = None, y_title: str | None = None, height: int = 320,
                y_range: Sequence[float] | None = None, percent: bool = False) -> go.Figure:
    has_legend = fig.layout.showlegend is not False and len(fig.data) > 1
    top = (40 if title else 12) + (30 if has_legend else 0)
    fig.update_layout(
        template="plotly_dark", paper_bgcolor=SURFACE, plot_bgcolor=SURFACE, height=height,
        margin={"l": 48, "r": 16, "t": top, "b": 40},
        title={"text": title, "font": {"family": "Rajdhani, sans-serif", "size": 18, "color": INK_PRIMARY},
               "x": 0.01, "xanchor": "left", "y": 1, "yref": "container", "yanchor": "top",
               "pad": {"t": 10}} if title else None,
        font={"family": "Inter, Segoe UI, sans-serif", "color": INK_SECONDARY, "size": 12},
        hovermode="x unified", hoverlabel={"bgcolor": "#1b1b27", "bordercolor": "#2a2840",
                                           "font": {"color": INK_PRIMARY}},
        legend={"orientation": "h", "yanchor": "bottom", "y": 1.02, "xanchor": "left", "x": 0,
                "font": {"color": INK_SECONDARY}},
    )
    fig.update_xaxes(showgrid=False, linecolor=GRID, tickfont={"color": INK_MUTED})
    fig.update_yaxes(gridcolor=GRID, gridwidth=1, zeroline=False, linecolor=GRID, tickfont={"color": INK_MUTED},
                     title={"text": y_title, "font": {"color": INK_MUTED}} if y_title else None,
                     range=list(y_range) if y_range else None, ticksuffix="%" if percent else None)
    return fig


def line_chart(
    x: Sequence[date], series: list[tuple[str, Sequence[float | None]]], *, title: str | None = None,
    y_title: str | None = None, percent: bool = False, y_range: Sequence[float] | None = None,
    missing_x: Sequence[date] = (), missing_y: float | None = None, ref_lines: Sequence[tuple[float, str]] = (),
    height: int = 320, markers: bool = True,
) -> go.Figure:
    fig = go.Figure()
    for i, (name, ys) in enumerate(series[:3]):
        color = SERIES[i]
        fig.add_trace(go.Scatter(
            x=list(x), y=list(ys), name=name, mode="lines+markers" if markers else "lines",
            line={"color": color, "width": 2}, marker={"size": 8, "color": color, "line": {"color": SURFACE, "width": 2}},
            connectgaps=False, hovertemplate="%{y:.1f}" + ("%" if percent else "") + f"<extra>{name}</extra>",
        ))
    if missing_x:
        # Sit just below the zero line so the marker is never clipped by the axis range.
        floor = missing_y if missing_y is not None else 0
        if y_range is not None:
            span = (y_range[1] - y_range[0]) or 1
            y_range = (min(y_range[0], floor - 0.08 * span), y_range[1])
            floor = floor - 0.04 * span
        fig.add_trace(go.Scatter(
            x=list(missing_x), y=[floor] * len(missing_x), name="Missing data",
            mode="markers", marker={"symbol": "x-thin", "size": 10, "line": {"color": MISSING, "width": 2}},
            hovertemplate="Missing data<extra></extra>",
        ))
    for i, (value, label) in enumerate(ref_lines):
        fig.add_hline(y=value, line={"color": INK_MUTED, "width": 1, "dash": "dot"},
                      annotation={"text": label, "font": {"color": INK_SECONDARY, "size": 11}},
                      annotation_position="top left" if i % 2 == 0 else "bottom right")
    if len(series) == 1 and not missing_x:
        fig.update_layout(showlegend=False)
    return base_layout(fig, title=title, y_title=y_title, height=height, y_range=y_range, percent=percent)


def bar_chart(x: Sequence[Any], y: Sequence[float], *, title: str | None = None, y_title: str | None = None,
              height: int = 300, horizontal: bool = False, percent: bool = False,
              hover_suffix: str = "") -> go.Figure:
    color = SERIES[0]
    if horizontal:
        trace = go.Bar(y=list(x), x=list(y), orientation="h", marker={"color": color, "cornerradius": 4},
                       hovertemplate="%{y}: %{x:.1f}" + hover_suffix + "<extra></extra>")
    else:
        trace = go.Bar(x=list(x), y=list(y), marker={"color": color, "cornerradius": 4},
                       hovertemplate="%{x}: %{y:.1f}" + hover_suffix + "<extra></extra>")
    fig = go.Figure(trace)
    fig.update_layout(bargap=0.35, showlegend=False)
    base_layout(fig, title=title, y_title=y_title, height=height, percent=percent and not horizontal)
    if horizontal:
        fig.update_yaxes(autorange="reversed", gridcolor=SURFACE)
        fig.update_xaxes(gridcolor=GRID, showgrid=True, ticksuffix="%" if percent else None)
        fig.update_layout(hovermode="closest")
    return fig
