import matplotlib
matplotlib.use("Agg") 
import matplotlib.pyplot as plt
from matplotlib.ticker import FuncFormatter


NAVY = "#2C3E50"
TEAL = "#16A085"
AMBER = "#E67E22"
RED = "#C0392B"
GREY = "#95A5A6"

plt.rcParams.update({
    "font.size": 11,
    "axes.spines.top": False,
    "axes.spines.right": False,
    "axes.edgecolor": "#CCCCCC",
    "figure.facecolor": "white",
    "axes.facecolor": "white",
})


def _rupee_formatter(x, _pos):
    return f"₹{x:,.0f}"


def sales_trend_chart(dates: list[str], totals: list[float], output_path: str) -> None:
    fig, ax = plt.subplots(figsize=(9, 4.5))
    ax.plot(dates, totals, color=NAVY, linewidth=2.5, marker="o", markersize=5, markerfacecolor=TEAL, markeredgecolor=TEAL)
    ax.fill_between(range(len(dates)), totals, color=TEAL, alpha=0.08)
    ax.yaxis.set_major_formatter(FuncFormatter(_rupee_formatter))
    ax.set_title("Daily Sales Trend", fontsize=14, fontweight="bold", color=NAVY, pad=12)
    ax.grid(axis="y", color="#EEEEEE", linewidth=1)
    ax.grid(axis="x", visible=False)
    plt.xticks(rotation=45, ha="right")
    fig.tight_layout()
    fig.savefig(output_path, dpi=150)
    plt.close(fig)


def top_skus_chart(names: list[str], revenues: list[float], output_path: str) -> None:
    fig, ax = plt.subplots(figsize=(9, 4.5))
    y_pos = range(len(names))
    ax.barh(y_pos, revenues, color=TEAL, height=0.6)
    ax.set_yticks(y_pos)
    ax.set_yticklabels(names)
    ax.invert_yaxis()  # highest revenue on top
    ax.xaxis.set_major_formatter(FuncFormatter(_rupee_formatter))
    ax.set_title("Top-Selling Items by Revenue", fontsize=14, fontweight="bold", color=NAVY, pad=12)
    ax.grid(axis="x", color="#EEEEEE", linewidth=1)
    ax.grid(axis="y", visible=False)
    for i, v in enumerate(revenues):
        ax.text(v, i, f"  ₹{v:,.0f}", va="center", fontsize=9, color=NAVY)
    fig.tight_layout()
    fig.savefig(output_path, dpi=150)
    plt.close(fig)


def stock_health_chart(names: list[str], qty_on_hand: list[float], thresholds: list[float], output_path: str) -> None:
    """Bars colored by health: red if at/below threshold, amber if within 2x
    threshold, teal otherwise — makes low-stock items visually obvious without
    needing a legend read closely."""
    colors_list = []
    for qty, threshold in zip(qty_on_hand, thresholds):
        if qty <= threshold:
            colors_list.append(RED)
        elif qty <= threshold * 2:
            colors_list.append(AMBER)
        else:
            colors_list.append(TEAL)

    fig, ax = plt.subplots(figsize=(9, 4.5))
    y_pos = range(len(names))
    ax.barh(y_pos, qty_on_hand, color=colors_list, height=0.6)
    ax.set_yticks(y_pos)
    ax.set_yticklabels(names)
    ax.invert_yaxis()
    ax.set_title("Stock Health (red = at/below reorder level)", fontsize=14, fontweight="bold", color=NAVY, pad=12)
    ax.grid(axis="x", color="#EEEEEE", linewidth=1)
    ax.grid(axis="y", visible=False)
    for i, v in enumerate(qty_on_hand):
        ax.text(v, i, f"  {v:g}", va="center", fontsize=9, color=NAVY)
    fig.tight_layout()
    fig.savefig(output_path, dpi=150)
    plt.close(fig)


def gst_collected_chart(slab_labels: list[str], slab_amounts: list[float], output_path: str) -> None:
    fig, ax = plt.subplots(figsize=(9, 4.5))
    colors_list = [NAVY, TEAL, AMBER, RED, GREY][: len(slab_labels)]
    bars = ax.bar(slab_labels, slab_amounts, color=colors_list, width=0.5)
    ax.yaxis.set_major_formatter(FuncFormatter(_rupee_formatter))
    ax.set_title("GST Collected by Slab", fontsize=14, fontweight="bold", color=NAVY, pad=12)
    ax.grid(axis="y", color="#EEEEEE", linewidth=1)
    ax.grid(axis="x", visible=False)
    for bar, amt in zip(bars, slab_amounts):
        ax.text(bar.get_x() + bar.get_width() / 2, bar.get_height(), f"₹{amt:,.0f}",
                ha="center", va="bottom", fontsize=9, color=NAVY)
    fig.tight_layout()
    fig.savefig(output_path, dpi=150)
    plt.close(fig)