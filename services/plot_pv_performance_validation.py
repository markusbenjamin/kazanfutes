"""Plot saved aggregate replay results; never reads production logs.

Run with Python and matplotlib installed. The monitor itself has no plotting
dependency. This figure is a post-hoc diagnostic, not another validation test.
"""

import argparse
from datetime import datetime
import json
from pathlib import Path


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--input", type=Path,
                        default=Path(__file__).with_name("pv_performance_validation_2026.json"))
    parser.add_argument("--output", type=Path,
                        default=Path(__file__).with_name("pv_performance_validation_2026.png"))
    args = parser.parse_args()
    if args.input.resolve() == args.output.resolve():
        parser.error("The figure must not overwrite its source")
    data = json.loads(args.input.read_text(encoding="utf-8"))

    import matplotlib
    matplotlib.use("Agg")
    import matplotlib.dates as mdates
    import matplotlib.pyplot as plt

    plt.rcParams.update({"font.size": 11, "axes.spines.top": False, "axes.spines.right": False})
    fig, axes = plt.subplots(2, 1, figsize=(11, 8), sharex=True)
    fig.suptitle("March 2026: the first detector missed the known fault", fontsize=18, x=.08, ha="left")
    noon = data["posthoc_total_production_diagnostic"]["noon"]
    dates = [datetime.fromisoformat(row["day"]) for row in noon]
    axes[0].plot(dates, [row["ac_kw"] for row in noon], "o-", color="#183b56", lw=1.6, ms=4)
    axes[0].set_title("Total AC production near solar noon", loc="left", fontsize=13)
    axes[0].set_ylabel("Median power (kW)")
    axes[0].set_ylim(-.5, 24)
    axes[0].text(.02, .91, "Fixed solar-noon window; all days shown", transform=axes[0].transAxes,
                 fontsize=10, color="#425466")

    colors = ("#4361ee", "#b43757", "#16806a", "#a56813")
    for target, color in zip(("pv1", "pv2", "pv3", "pv4"), colors):
        rows = data["march"][target]
        axes[1].plot([datetime.fromisoformat(row["day"]) for row in rows],
                     [row["deficit"] * 100 if row["qualified"] else float("nan") for row in rows],
                     "o-", label=target.upper(), color=color, lw=1.3, ms=4)
    axes[1].axhline(10, color="#182b3a", linestyle="--", lw=1.1, label="10% main-input threshold")
    axes[1].axhline(0, color="#84939e", lw=.7)
    axes[1].set_title("Frozen 2025 reference: relative string shortfalls", loc="left", fontsize=13)
    axes[1].set_ylabel("Predicted shortfall (%)")
    axes[1].set_ylim(-8, 14)
    axes[1].legend(loc="upper left", ncol=3, fontsize=9, frameon=False)
    for axis in axes:
        axis.grid(axis="y", color="#dce3e9", lw=.6)
        for day, color in (("2026-03-13", "#a33b46"), ("2026-03-17", "#367f8a")):
            axis.axvline(datetime.fromisoformat(day), color=color, linestyle=":", lw=1.5)
    axes[0].annotate("Panel repair\n13 March", (datetime(2026, 3, 13), 21),
                     ha="right", fontsize=10, color="#a33b46")
    axes[0].annotate("Cleaning\n17 March", (datetime(2026, 3, 17), 21),
                     ha="left", fontsize=10, color="#367f8a")
    axes[1].xaxis.set_major_locator(mdates.DayLocator(interval=3))
    axes[1].xaxis.set_major_formatter(mdates.DateFormatter("%d Mar"))
    axes[1].set_xlim(datetime(2026, 2, 28, 12), datetime(2026, 3, 31, 12))
    fig.text(.08, .055, "Top: descriptive comparison, without weather correction. Repair and cleaning effects are not isolated.\n"
             "Bottom: only qualifying days; gaps mean insufficient evidence. Opening also requires a conservative bound\n"
             "and three qualifying days. The whole-array detector had no weather baseline and could not evaluate this event.",
             fontsize=10, color="#425466", va="bottom", linespacing=1.5)
    fig.subplots_adjust(left=.08, right=.98, top=.9, bottom=.18, hspace=.3)
    fig.savefig(args.output, dpi=160, facecolor="white")
    print(args.output.resolve())


if __name__ == "__main__":
    main()
