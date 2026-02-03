import pandas as pd
import plotly.express as px
import plotly.graph_objects as go

from portfolio_dashboard.metrics import format_currency


POS_COLOR = "#4C956C"
NEG_COLOR = "#D97A6A"
NEUTRAL_COLOR = "#7A7A7A"


def allocation_pie(df: pd.DataFrame, top_n: int) -> go.Figure:
    allocation_df = df.nlargest(top_n, "Value at Market Price")
    fig = px.pie(
        allocation_df,
        values="Value at Market Price",
        names="Stock Symbol",
        hole=0.55,
    )
    fig.update_traces(textposition="inside", textinfo="percent+label")
    fig.update_layout(showlegend=False, margin=dict(t=10, l=10, r=10, b=10))
    return fig


def top_holdings_bar(df: pd.DataFrame, top_n: int) -> go.Figure:
    top_holdings = df.nlargest(top_n, "Value at Market Price")
    fig = px.bar(
        top_holdings,
        x="Stock Symbol",
        y="Value at Market Price",
        color="Total P&L",
        color_continuous_scale=[NEG_COLOR, POS_COLOR],
    )
    fig.update_layout(
        xaxis_title="",
        yaxis_title="Value at Market Price",
        coloraxis_showscale=False,
        margin=dict(t=10, l=10, r=10, b=10),
    )
    return fig


def cost_market_waterfall(metrics: dict) -> go.Figure:
    fig = go.Figure(
        go.Waterfall(
            orientation="v",
            measure=["absolute", "relative", "total"],
            x=["Cost", "P&L", "Market"],
            y=[
                metrics["Total Investment"],
                metrics["Current Value"] - metrics["Total Investment"],
                metrics["Current Value"],
            ],
            text=[
                format_currency(metrics["Total Investment"]),
                "",
                format_currency(metrics["Current Value"]),
            ],
            textposition="outside",
            connector={"line": {"color": NEUTRAL_COLOR}},
        )
    )
    fig.update_layout(
        showlegend=False,
        yaxis_title="₹",
        margin=dict(t=10, l=10, r=10, b=10),
    )
    return fig


def cost_market_waterfall_for_df(df: pd.DataFrame) -> go.Figure:
    total_cost = df["Value at Cost"].sum()
    total_market = df["Value at Market Price"].sum()
    delta = total_market - total_cost
    metrics = {
        "Total Investment": total_cost,
        "Current Value": total_market,
        "Delta": delta,
    }
    fig = go.Figure(
        go.Waterfall(
            orientation="v",
            measure=["absolute", "relative", "total"],
            x=["Cost", "P&L", "Market"],
            y=[
                metrics["Total Investment"],
                metrics["Delta"],
                metrics["Current Value"],
            ],
            text=[
                format_currency(metrics["Total Investment"]),
                "",
                format_currency(metrics["Current Value"]),
            ],
            textposition="outside",
            connector={"line": {"color": NEUTRAL_COLOR}},
        )
    )
    fig.update_layout(
        showlegend=False,
        yaxis_title="₹",
        margin=dict(t=10, l=10, r=10, b=10),
    )
    return fig


def unrealized_bucket_bar(df: pd.DataFrame) -> go.Figure:
    bucket_order = [
        "<= -20%",
        "-20% to -10%",
        "-10% to 0%",
        "0% to 10%",
        "10% to 20%",
        "> 20%",
    ]
    bucket_totals = (
        df.groupby("Unrealized P&L % Bucket", dropna=False, observed=False)[
            "Value at Market Price"
        ]
        .sum()
        .reindex(bucket_order, fill_value=0)
        .reset_index()
    )
    bucket_totals.columns = ["Bucket", "Market Value"]
    fig = px.bar(bucket_totals, x="Bucket", y="Market Value")
    fig.update_layout(
        xaxis_title="",
        yaxis_title="Market Value",
        margin=dict(t=10, l=10, r=10, b=10),
    )
    return fig


def unrealized_bucket_stacked(df: pd.DataFrame) -> go.Figure:
    bucket_order = [
        "<= -20%",
        "-20% to -10%",
        "-10% to 0%",
        "0% to 10%",
        "10% to 20%",
        "> 20%",
    ]
    category = pd.Series("Flat", index=df.index)
    category[df["Total P&L"] > 0] = "Profit"
    category[df["Total P&L"] < 0] = "Loss"

    grouped = (
        df.assign(Profit_Loss=category)
        .groupby(
            ["Unrealized P&L % Bucket", "Profit_Loss"], dropna=False, observed=False
        )[
            "Value at Market Price"
        ]
        .sum()
        .reset_index()
    )
    grouped["Unrealized P&L % Bucket"] = pd.Categorical(
        grouped["Unrealized P&L % Bucket"], categories=bucket_order, ordered=True
    )
    grouped = grouped.sort_values("Unrealized P&L % Bucket")

    fig = px.bar(
        grouped,
        x="Unrealized P&L % Bucket",
        y="Value at Market Price",
        color="Profit_Loss",
        color_discrete_map={
            "Profit": POS_COLOR,
            "Loss": NEG_COLOR,
            "Flat": NEUTRAL_COLOR,
        },
    )
    fig.update_layout(
        xaxis_title="",
        yaxis_title="Market Value",
        legend_title="",
        margin=dict(t=10, l=10, r=10, b=10),
    )
    return fig


def cost_performance_pie(df: pd.DataFrame) -> go.Figure:
    category = pd.Series("Flat", index=df.index)
    category[df["Total P&L"] > 0] = "Positive"
    category[df["Total P&L"] < 0] = "Negative"

    df = df.copy()
    df["Value at Cost"] = pd.to_numeric(
        df["Value at Cost"], errors="coerce"
    ).fillna(0)
    df["Unrealized P&L"] = pd.to_numeric(
        df["Unrealized P&L"], errors="coerce"
    ).fillna(0)

    grouped = df.assign(Performance=category).groupby(
        "Performance", dropna=False, observed=False
    )
    totals = grouped[["Value at Cost", "Unrealized P&L"]].sum().reset_index()
    totals["Holdings"] = grouped.size().values
    total_unrealized_abs = totals["Unrealized P&L"].abs().sum()
    totals["Unrealized P&L % Share"] = (
        totals["Unrealized P&L"].abs() / total_unrealized_abs * 100
        if total_unrealized_abs
        else 0
    )
    fig = px.pie(
        totals,
        values="Value at Cost",
        names="Performance",
        hole=0.55,
        color="Performance",
        color_discrete_map={
            "Positive": POS_COLOR,
            "Negative": NEG_COLOR,
            "Flat": NEUTRAL_COLOR,
        },
        custom_data=["Holdings", "Unrealized P&L", "Unrealized P&L % Share"],
    )
    fig.update_traces(
        textposition="inside",
        textinfo="percent+label",
        hovertemplate=(
            "%{label}<br>Value at Cost: ₹%{value:,.0f}"
            "<br>Holdings: %{customdata[0]}"
            "<br>Unrealized P&L: ₹%{customdata[1]:,.0f}"
            "<br>Unrealized P&L Share: %{customdata[2]:.2f}%"
            "<br>Cost Share: %{percent}<extra></extra>"
        ),
    )
    fig.update_layout(showlegend=False, margin=dict(t=10, l=10, r=10, b=10))
    return fig
