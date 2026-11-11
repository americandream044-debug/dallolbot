"""Neon-on-black dashboard image rendering, executed off the event loop."""
from __future__ import annotations

import asyncio
from io import BytesIO
from typing import Any


async def render_dashboard(data: dict[str, Any]) -> BytesIO:
    """Render a terminal-style KPI, growth, and active-hours dashboard in memory."""
    return await asyncio.to_thread(_render_dashboard, data)


def _render_dashboard(data: dict[str, Any]) -> BytesIO:
    import matplotlib
    matplotlib.use("Agg")
    import matplotlib.pyplot as plt
    import numpy as np
    from matplotlib.colors import LinearSegmentedColormap
    from matplotlib.patches import FancyBboxPatch

    background = "#0D1117"
    panel = "#161B22"
    green = "#00FF9C"
    cyan = "#00D9FF"
    purple = "#B56BFF"
    muted = "#8B949E"
    grid = "#30363D"
    plt.rcParams.update({
        "font.family": "DejaVu Sans Mono",
        "text.color": "#DCE6F1",
        "axes.labelcolor": muted,
        "xtick.color": muted,
        "ytick.color": muted,
    })

    figure = plt.figure(figsize=(13, 9), dpi=150, facecolor=background)
    layout = figure.add_gridspec(3, 2, height_ratios=(0.72, 1.18, 1.05), hspace=0.38, wspace=0.25)
    metric_ax = figure.add_subplot(layout[0, :])
    growth_ax = figure.add_subplot(layout[1, 0])
    source_ax = figure.add_subplot(layout[1, 1])
    heat_ax = figure.add_subplot(layout[2, :])
    for axis in (metric_ax, growth_ax, source_ax, heat_ax):
        axis.set_facecolor(panel)

    summary = data.get("summary", {})
    metrics = [
        ("TOTAL USERS", summary.get("total_users", 0), green),
        ("NEW TODAY", summary.get("today_users", 0), cyan),
        ("OPEN TICKETS", summary.get("open_tickets", 0), purple),
        ("SCHEDULED", summary.get("scheduled_posts", 0), "#F0B429"),
        ("DAU", summary.get("dau", 0), green),
        ("WAU", summary.get("wau", 0), cyan),
        ("MAU", summary.get("mau", 0), purple),
    ]
    metric_ax.set_xlim(0, 7)
    metric_ax.set_ylim(0, 1)
    metric_ax.axis("off")
    for index, (label, value, accent) in enumerate(metrics):
        x = index + 0.06
        card = FancyBboxPatch((x, 0.12), 0.88, 0.76, boxstyle="round,pad=0.025,rounding_size=0.04", linewidth=1.0, edgecolor=grid, facecolor=background)
        metric_ax.add_patch(card)
        metric_ax.text(x + 0.44, 0.67, str(label), ha="center", va="center", fontsize=7.2, color=muted)
        metric_ax.text(x + 0.44, 0.38, f"{int(value or 0):,}", ha="center", va="center", fontsize=15, color=accent, fontweight="bold")

    growth_ax.set_title("NEW USERS + CUMULATIVE / 30D", loc="left", color=green, fontsize=9, pad=10, fontweight="bold")
    daily = data.get("users_daily", [])
    if daily:
        dates = [str(row["day"])[5:] for row in daily]
        new_users = np.array([int(row["n"]) for row in daily], dtype=float)
        cumulative = np.cumsum(new_users)
        indices = np.arange(len(dates))
        growth_ax.bar(indices, new_users, color=cyan, alpha=0.78, width=0.68, label="Yangi")
        cumulative_ax = growth_ax.twinx()
        cumulative_ax.set_facecolor("none")
        cumulative_ax.plot(indices, cumulative, color=green, linewidth=2.0, marker="o", markersize=2.6, label="Jamlanma")
        cumulative_ax.tick_params(axis="y", colors=green, labelsize=7)
        cumulative_ax.spines["right"].set_color(grid)
        cumulative_ax.set_ylabel("Jamlanma", color=green, fontsize=7)
        growth_ax.set_xticks(indices[::max(1, len(indices) // 8)], dates[::max(1, len(dates) // 8)], rotation=35, ha="right", fontsize=7)
        growth_ax.tick_params(axis="y", labelsize=7)
        growth_ax.set_ylabel("Yangi", fontsize=7)
        growth_ax.grid(axis="y", color=grid, linestyle="--", alpha=0.55)
        growth_ax.set_axisbelow(True)
        growth_ax.legend(loc="upper left", fontsize=7, facecolor=panel, edgecolor=grid)
        cumulative_ax.legend(loc="upper right", fontsize=7, facecolor=panel, edgecolor=grid)
    else:
        growth_ax.text(0.5, 0.5, "Hozircha foydalanuvchi o‘sishi yo‘q", ha="center", va="center", color=muted, transform=growth_ax.transAxes)
        growth_ax.set_xticks([])
        growth_ax.set_yticks([])

    source_ax.set_title("TOP REFERRAL SOURCES", loc="left", color=purple, fontsize=9, pad=10, fontweight="bold")
    sources = data.get("sources", [])[:8]
    if sources:
        names = [str(row.get("source", "direct"))[:18] for row in reversed(sources)]
        counts = [int(row.get("n", 0)) for row in reversed(sources)]
        positions = np.arange(len(names))
        source_ax.barh(positions, counts, color=purple, alpha=0.82, height=0.62)
        source_ax.set_yticks(positions, names, fontsize=7)
        source_ax.tick_params(axis="x", labelsize=7)
        source_ax.grid(axis="x", color=grid, linestyle="--", alpha=0.55)
        source_ax.set_axisbelow(True)
        for pos, count in zip(positions, counts):
            source_ax.text(count, pos, f"  {count}", va="center", color="#FFFFFF", fontsize=7)
    else:
        source_ax.text(0.5, 0.5, "Referral source ma'lumoti yo‘q", ha="center", va="center", color=muted, transform=source_ax.transAxes)
        source_ax.set_xticks([])
        source_ax.set_yticks([])

    heat_ax.set_title("ACTIVE HOURS / WEEKDAY × HOUR", loc="left", color=cyan, fontsize=9, pad=10, fontweight="bold")
    matrix = np.zeros((7, 24), dtype=float)
    for row in data.get("active_hours", []):
        try:
            weekday = int(row["weekday"])
            hour = int(row["hour"])
            if 0 <= weekday < 7 and 0 <= hour < 24:
                matrix[weekday, hour] = float(row["n"])
        except (KeyError, TypeError, ValueError):
            continue
    cmap = LinearSegmentedColormap.from_list("terminal_neon", [background, "#064B3B", green, cyan])
    heat_ax.imshow(matrix, aspect="auto", interpolation="nearest", cmap=cmap)
    heat_ax.set_yticks(range(7), ["Yak", "Du", "Se", "Cho", "Pay", "Ju", "Sha"], fontsize=7)
    heat_ax.set_xticks(range(0, 24, 2), [f"{x:02d}" for x in range(0, 24, 2)], fontsize=7)
    heat_ax.set_xlabel("Soat (bot timezone)", fontsize=7)
    heat_ax.tick_params(length=0)

    for axis in (growth_ax, heat_ax):
        for spine in axis.spines.values():
            spine.set_color(grid)
        axis.grid(False)
    figure.suptitle("D&A // ANALYTICS CONTROL", x=0.055, y=0.985, ha="left", color=green, fontsize=15, fontweight="bold")
    figure.text(0.055, 0.015, "root@dasturlash:~$ report --live   •   kanal views Bot API orqali berilmaydi", color=muted, fontsize=7)
    figure.subplots_adjust(top=0.92, bottom=0.08, left=0.07, right=0.96)

    raw = BytesIO()
    figure.savefig(raw, format="png", facecolor=background, bbox_inches="tight")
    plt.close(figure)
    raw.seek(0)

    # Pillow decorates the final image with a compact terminal title bar.
    from PIL import Image, ImageDraw, ImageFont
    image = Image.open(raw).convert("RGB")
    draw = ImageDraw.Draw(image)
    draw.rectangle((0, 0, image.width, 25), fill="#161B22")
    try:
        font = ImageFont.truetype("DejaVuSansMono.ttf", 10)
    except OSError:
        font = ImageFont.load_default()
    draw.ellipse((10, 8, 18, 16), fill="#FF5F56")
    draw.ellipse((24, 8, 32, 16), fill="#FFBD2E")
    draw.ellipse((38, 8, 46, 16), fill="#27C93F")
    draw.text((58, 6), "root@dasturlash:~ / analytics", fill=green, font=font)
    output = BytesIO()
    image.save(output, format="PNG", optimize=True)
    output.seek(0)
    return output
