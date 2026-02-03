# Added Smart Exit Plan and reallocation panel outputs.
from pathlib import Path
import logging

import pandas as pd
import plotly.express as px
import streamlit as st

from portfolio_dashboard.charts import (
    allocation_pie,
    cost_performance_pie,
    cost_market_waterfall,
    cost_market_waterfall_for_df,
    top_holdings_bar,
    unrealized_bucket_bar,
    unrealized_bucket_stacked,
    unrealized_heatmap,
    unrealized_heatmap_negative,
    unrealized_heatmap_positive,
)
from portfolio_dashboard.data import (
    add_exit_fields,
    add_unrealized_bucket,
    load_portfolio,
    normalize_numeric_columns,
)
from portfolio_dashboard.db import clear_table, load_table, upsert_holdings
from portfolio_dashboard.metrics import compute_metrics, format_currency, format_percent


# Added smart exit plan and reallocation outputs.
def configure_logging() -> logging.Logger:
    log_dir = Path("data")
    log_dir.mkdir(parents=True, exist_ok=True)
    log_path = log_dir / "streamlit.log"

    logging.basicConfig(
        level=logging.INFO,
        format="%(asctime)s %(levelname)s %(name)s: %(message)s",
        handlers=[logging.FileHandler(log_path), logging.StreamHandler()],
    )
    return logging.getLogger("portfolio_dashboard")


def main() -> None:
    logger = configure_logging()
    try:
        st.set_page_config(
            page_title="Equity Portfolio Dashboard",
            page_icon="📈",
            layout="wide",
            initial_sidebar_state="expanded",
        )
        st.title("Equity Portfolio Dashboard")
        st.caption(
            "Drop CSVs into the input folder and load them into the database."
        )

        with st.sidebar:
            st.header("Filters")
            pl_filter = st.selectbox("Profit/Loss", ["All", "Profit", "Loss"])
            top_n = st.slider(
                "Top N holdings", min_value=5, max_value=30, value=10, step=1
            )

        st.subheader("Data Ingestion")
        input_dir = Path("input")
        input_dir.mkdir(parents=True, exist_ok=True)
        csv_files = sorted(input_dir.glob("*.csv"))

        uploaded_csv = st.file_uploader("Upload CSV", type=["csv"])
        if uploaded_csv is not None:
            target_path = input_dir / uploaded_csv.name
            target_path.write_bytes(uploaded_csv.getbuffer())
            st.success(f"Uploaded {uploaded_csv.name} to input folder.")
            csv_files = sorted(input_dir.glob("*.csv"))

        if st.button("Clear database", type="secondary"):
            clear_table()
            st.success("Database cleared. Load a CSV to continue.")
            st.stop()

        if not csv_files:
            st.info("Add a CSV file to the input folder to begin.")
            st.stop()

        file_names = [file_path.name for file_path in csv_files]
        selected_file = st.selectbox(
            "Select CSV from input folder", file_names)

        if st.button("Load into database", type="primary"):
            raw_df = pd.read_csv(input_dir / selected_file)
            try:
                cleaned_df = load_portfolio(raw_df)
            except ValueError as exc:
                st.error(f"Exit plan fields could not be computed: {exc}")
                st.stop()
            if cleaned_df.empty:
                st.error(
                    "No usable rows found after cleaning. Check the CSV format.")
                st.stop()
            df = upsert_holdings(cleaned_df)
            st.success(
                f"Loaded {len(cleaned_df)} rows. Database now has {len(df)} rows."
            )
        else:
            df = load_table(latest_only=False)
            if "loaded_at" in df.columns and not df.empty:
                load_options = (
                    df["loaded_at"]
                    .dropna()
                    .astype(str)
                    .sort_values(ascending=False)
                    .unique()
                    .tolist()
                )
                if load_options:
                    selected_load = st.selectbox(
                        "Select load timestamp", load_options)
                    df = df[df["loaded_at"].astype(str) == selected_load]
            df = normalize_numeric_columns(df)
            df = add_unrealized_bucket(df)
            try:
                df = add_exit_fields(df)
            except ValueError as exc:
                st.error(f"Exit plan fields could not be computed: {exc}")
                st.stop()

            if df.empty:
                st.info("Database is empty. Load a CSV from the input folder.")
                st.stop()

        if pl_filter == "Profit":
            df = df[df["Total P&L"] > 0]
        elif pl_filter == "Loss":
            df = df[df["Total P&L"] < 0]

        df = df.sort_values("Value at Market Price", ascending=False)

        metrics = compute_metrics(df)

        col1, col2, col3, col4, col5, col6, col7 = st.columns(7)
        col1.metric("Total Investment", format_currency(
            metrics["Total Investment"]))
        col2.metric("Current Value", format_currency(metrics["Current Value"]))
        col3.metric("Total P&L", format_currency(metrics["Total P&L"]))
        col4.metric("Total P&L %", format_percent(metrics["Total P&L %"]))
        realized_total = df.get(
            "Realized P&L", pd.Series(0, index=df.index)).sum()
        unrealized_total = df.get(
            "Unrealized P&L", pd.Series(0, index=df.index)).sum()
        unrealized_pct = (
            unrealized_total / metrics["Total Investment"] * 100
            if metrics["Total Investment"]
            else 0
        )
        col5.metric("Realized P&L", format_currency(realized_total))
        col6.metric("Unrealized P&L", format_currency(unrealized_total))
        col7.metric("Unrealized P&L %", format_percent(unrealized_pct))

        st.markdown("---")

        left, right = st.columns((1.2, 1))
        with left:
            st.subheader("Portfolio Allocation")
            st.plotly_chart(allocation_pie(df, top_n),
                            use_container_width=True)

        with right:
            st.subheader("Top Holdings by Market Value")
            st.plotly_chart(top_holdings_bar(df, top_n),
                            use_container_width=True)

        st.subheader("Cost vs Market Value")
        st.plotly_chart(cost_market_waterfall(
            metrics), use_container_width=True)

        pos_unrealized = df[df["Unrealized P&L"] > 0]
        neg_unrealized = df[df["Unrealized P&L"] < 0]

        st.subheader("Cost vs Market Value (Unrealized P&L Positive)")
        if pos_unrealized.empty:
            st.info("No holdings with positive unrealized P&L.")
        else:
            st.plotly_chart(
                cost_market_waterfall_for_df(pos_unrealized),
                use_container_width=True,
            )

        st.subheader("Cost vs Market Value (Unrealized P&L Negative)")
        if neg_unrealized.empty:
            st.info("No holdings with negative unrealized P&L.")
        else:
            st.plotly_chart(
                cost_market_waterfall_for_df(neg_unrealized),
                use_container_width=True,
            )

        st.subheader("Cost Allocation by Performance")
        st.plotly_chart(cost_performance_pie(df), use_container_width=True)

        st.subheader("Unrealized P&L Heatmap (₹)")
        st.plotly_chart(unrealized_heatmap(df), use_container_width=True)

        st.subheader("Unrealized P&L Heatmap (₹, Positive)")
        st.plotly_chart(unrealized_heatmap_positive(df),
                        use_container_width=True)

        st.subheader("Unrealized P&L Heatmap (₹, Negative)")
        st.plotly_chart(unrealized_heatmap_negative(df),
                        use_container_width=True)

        st.subheader("Unrealized P&L % Buckets (Market Value)")
        st.plotly_chart(unrealized_bucket_bar(df), use_container_width=True)

        st.subheader("Unrealized P&L % Buckets by Profit/Loss")
        st.plotly_chart(unrealized_bucket_stacked(df),
                        use_container_width=True)

        st.subheader("Export-ready Tables")
        export_df = df.copy()
        export_df["Total P&L %"] = export_df["Total P&L %"].round(2)
        export_df["Unrealized P&L %"] = export_df["Unrealized P&L %"].round(2)

        sort_columns = st.multiselect(
            "Sort by columns",
            export_df.columns.tolist(),
            default=[
                "Stock Symbol"] if "Stock Symbol" in export_df.columns else None,
        )
        sort_order = st.radio(
            "Sort order", ["Ascending", "Descending"], horizontal=True
        )
        if sort_columns:
            sorted_df = export_df.sort_values(
                sort_columns, ascending=sort_order == "Ascending"
            )
        else:
            sorted_df = export_df

        summary_df = pd.DataFrame(
            {
                "Metric": [
                    "Total Investment",
                    "Current Value",
                    "Total P&L",
                    "Total P&L %",
                    "Win Ratio",
                ],
                "Value": [
                    metrics["Total Investment"],
                    metrics["Current Value"],
                    metrics["Total P&L"],
                    metrics["Total P&L %"],
                    metrics["Win Ratio"],
                ],
            }
        )

        st.dataframe(sorted_df, use_container_width=True, height=320)

        export_csv = sorted_df.to_csv(index=False).encode("utf-8")
        summary_csv = summary_df.to_csv(index=False).encode("utf-8")

        col_export_1, col_export_2 = st.columns(2)
        col_export_1.download_button(
            "Download Holdings CSV", export_csv, file_name="portfolio_holdings.csv"
        )
        col_export_2.download_button(
            "Download Summary CSV", summary_csv, file_name="portfolio_summary.csv"
        )

        st.markdown("---")
        st.subheader("Smart Exit Plan")

        exit_tags = st.multiselect(
            "Exit tags",
            ["EXIT", "PARTIAL EXIT", "HOLD"],
            default=["EXIT", "PARTIAL EXIT", "HOLD"],
        )
        risk_only = st.toggle("Risk flag only", value=False)
        min_exposure = st.slider("Min exposure %", 0.0, 20.0, 0.0, 0.5)

        exit_df = df.copy()
        if exit_tags:
            exit_df = exit_df[exit_df["exit_tag"].isin(exit_tags)]
        if risk_only:
            exit_df = exit_df[exit_df["risk_flag"]]
        exit_df = exit_df[exit_df["exposure_pct"] >= min_exposure]

        pnl_band = pd.cut(
            exit_df["pnl_pct"],
            bins=[-float("inf"), -50, -30, -15, 0, float("inf")],
            labels=["<=-50", "-50..-30", "-30..-15", "-15..0", ">0"],
        )
        exit_df = exit_df.assign(pnl_band=pnl_band)

        priority_df = exit_df[
            [
                "Stock Symbol",
                "Qty",
                "CMP",
                "exposure",
                "exposure_pct",
                "pnl_abs",
                "pnl_pct",
                "recovery_required_pct",
                "exit_tag",
                "risk_flag",
                "drag_score",
                "tranche_plan",
                "pnl_band",
            ]
        ].sort_values(["drag_score", "pnl_pct"], ascending=[False, True])

        total_cost = exit_df["Value at Cost"].sum()
        total_market = exit_df["Value at Market Price"].sum()
        total_pnl = exit_df["pnl_abs"].sum()
        loss_pct = (total_pnl / total_cost * 100) if total_cost else 0

        card1, card2, card3, card4 = st.columns(4)
        card1.metric("Value at Cost", format_currency(total_cost))
        card2.metric("Current Market Value", format_currency(total_market))
        card3.metric("Loss Amount", format_currency(total_pnl))
        card4.metric("% Loss", format_percent(loss_pct))

        st.subheader("Exit Priority List")
        st.dataframe(priority_df, use_container_width=True, height=320)

        st.subheader("Top Draggers")
        top_draggers = (
            priority_df.sort_values("drag_score", ascending=False)
            .head(10)
            .copy()
        )
        if top_draggers.empty:
            st.info("No holdings match the current exit filters.")
        else:
            fig = px.bar(
                top_draggers,
                x="Stock Symbol",
                y="drag_score",
                color="exit_tag",
                color_discrete_map={
                    "EXIT": "#D97A6A",
                    "PARTIAL EXIT": "#7A7A7A",
                    "HOLD": "#4C956C",
                },
            )
            fig.update_layout(
                xaxis_title="",
                yaxis_title="Drag Score",
                coloraxis_showscale=False,
                margin=dict(t=10, l=10, r=10, b=10),
            )
            st.plotly_chart(fig, use_container_width=True)

        st.subheader("Reallocation Plan")
        exit_exposure = df[df["exit_tag"] == "EXIT"]["exposure"].sum()
        partial_exposure = df[df["exit_tag"] ==
                              "PARTIAL EXIT"]["exposure"].sum()
        capital_to_free = exit_exposure + 0.35 * partial_exposure
        winners_exposure = df[df["pnl_pct"] >= 20]["exposure"].sum()

        allocation = [
            ("Index ETF / Cash proxy (parking)", 50),
            ("Add to existing winners", 30),
            ("New positions (risk-controlled)", 20),
        ]
        if winners_exposure == 0:
            allocation = [
                ("Index ETF / Cash proxy (parking)", 80),
                ("Add to existing winners", 0),
                ("New positions (risk-controlled)", 20),
            ]

        allocation_df = pd.DataFrame(
            [
                {
                    "allocation_bucket": bucket,
                    "allocation_pct": pct,
                    "amount": capital_to_free * pct / 100,
                    "rationale": (
                        "No winners > 20% P&L; redirecting to parking."
                        if winners_exposure == 0 and bucket == "Index ETF / Cash proxy (parking)"
                        else ""
                    ),
                }
                for bucket, pct in allocation
            ]
        )

        st.write(f"Capital to free: ₹{capital_to_free:,.0f}")
        st.caption(
            "Computed as 100% of EXIT exposure + 35% of PARTIAL EXIT exposure."
        )
        st.dataframe(allocation_df, use_container_width=True, height=220)

        tagged_csv = df.to_csv(index=False).encode("utf-8")
        realloc_csv = allocation_df.to_csv(index=False).encode("utf-8")
        export_tagged, export_realloc = st.columns(2)
        export_tagged.download_button(
            "Download Tagged Portfolio CSV",
            tagged_csv,
            file_name="tagged_portfolio.csv",
        )
        export_realloc.download_button(
            "Download Reallocation Plan CSV",
            realloc_csv,
            file_name="reallocation_plan.csv",
        )
    except Exception:
        logger.exception("Streamlit app error")
        raise


if __name__ == "__main__":
    main()
