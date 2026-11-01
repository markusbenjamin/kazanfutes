"""Render saved aggregate evidence; never reads production logs or downloads weather."""

from datetime import date
import json
from pathlib import Path

import matplotlib
matplotlib.use("Agg")
import matplotlib.dates as mdates
import matplotlib.pyplot as plt
from matplotlib.ticker import PercentFormatter


def main():
    root = Path(__file__).resolve().parent
    result = json.loads((root / "pv_accumulation_seasonal_validation_2026.json").read_text(encoding="utf-8"))
    period = result["periods"]["event_year_2026"]
    fig, axes = plt.subplots(3, 1, figsize=(12, 10), gridspec_kw={"height_ratios": [1.35, 1, 1]})
    colors = {"array": "#bf4839", "pv1": "#226ca7", "pv2": "#29966a", "pv3": "#9560ad", "pv4": "#bd8927"}
    for target, records in period["daily"].items():
        selected = [r for r in records if "2026-02-20" <= r["day"] < "2026-04-05" and r["qualified"]]
        ax = axes[0] if target == "array" else axes[1]
        ax.plot([date.fromisoformat(r["day"]) for r in selected],
                [r["corrected_deficit"] for r in selected], marker="o", markersize=4,
                linewidth=1.3, label="Whole array" if target == "array" else target.upper(), color=colors[target])
    for ax in axes[:2]:
        ax.axhline(0, color="#777777", lw=.8)
        ax.axvline(date(2026, 3, 13), color="#444444", linestyle="--", lw=1, label="Panels repaired")
        ax.axvline(date(2026, 3, 17), color="#888888", linestyle=":", lw=1, label="Cleaning")
        ax.set_xlim(date(2026, 2, 20), date(2026, 4, 4))
        ax.xaxis.set_major_formatter(mdates.DateFormatter("%d %b"))
        ax.yaxis.set_major_formatter(PercentFormatter(1))
        ax.grid(alpha=.2)
        ax.set_ylabel("Corrected shortfall\npositive = below reference")
    axes[0].set_title("Array and relative-input evidence around the known event", loc="left", fontsize=14)
    axes[0].legend(loc="upper right", fontsize=9)
    axes[1].legend(loc="upper right", ncol=3, fontsize=9)
    axes[1].axhline(.03, color="#555555", linestyle=":", lw=1)
    axes[1].set_title("Relative inputs: a 3% accumulated loss can request inspection", loc="left", fontsize=11)
    for index, (target, records) in enumerate(period["daily"].items()):
        active = [r for r in records if r["inspection_open"]]
        axes[2].scatter([date.fromisoformat(r["day"]) for r in active], [index] * len(active),
                        marker="|", s=170, color=colors[target])
    axes[2].set_yticks(range(len(period["daily"])), [t.upper() for t in period["daily"]])
    axes[2].set_xlim(date(2026, 1, 1), date(2026, 10, 27))
    axes[2].xaxis.set_major_formatter(mdates.DateFormatter("%b"))
    axes[2].set_title("Open inspections through the year (unlabelled background; not confirmed faults)", loc="left", fontsize=11)
    axes[2].grid(axis="x", alpha=.2)
    fig.suptitle("PV watchdog · frozen pre-2026 calibration", fontsize=18, x=.08, ha="left")
    fig.text(.08, .025, "Only qualifying days shown above. Missing evidence is unknown. March influenced development.\n"
             "Array evidence uses delayed regional weather; these are evidence dates, not historical notification dates.", fontsize=10, color="#555555")
    fig.tight_layout(rect=(.02, .065, .98, .95))
    destination = root / "pv_accumulation_validation_2026.png"
    fig.savefig(destination, dpi=150)
    plt.close(fig)
    print(destination)


if __name__ == "__main__":
    main()
