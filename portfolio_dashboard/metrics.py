import pandas as pd


def compute_metrics(df: pd.DataFrame) -> dict:
    total_investment = df["Value at Cost"].sum()
    current_value = df["Value at Market Price"].sum()
    total_pl = df["Total P&L"].sum()
    total_pl_pct = (total_pl / total_investment * 100) if total_investment else 0
    win_ratio = (
        (df["Total P&L"] > 0).sum() / len(df) * 100 if len(df) else 0
    )

    return {
        "Total Investment": total_investment,
        "Current Value": current_value,
        "Total P&L": total_pl,
        "Total P&L %": total_pl_pct,
        "Win Ratio": win_ratio,
    }


def format_currency(value: float) -> str:
    return f"₹{value:,.0f}"


def format_percent(value: float) -> str:
    return f"{value:.2f}%"
