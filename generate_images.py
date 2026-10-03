#!/usr/bin/python3

import argparse
import asyncio
import datetime
import html
import math
import os
from typing import Dict, List, Optional, Tuple

import aiohttp

from github_stats import Stats, compute_streaks


ROOT = os.path.dirname(os.path.abspath(__file__))
TEMPLATES = os.path.join(ROOT, "templates")


################################################################################
# Helper Functions
################################################################################

def generate_output_folder(output_dir: str) -> None:
    """
    Create the output folder if it does not already exist
    """
    os.makedirs(output_dir, exist_ok=True)


def read_template(name: str) -> str:
    """
    Read a template and inject the shared theme stylesheet into it
    :param name: file name of the template inside the templates folder
    :return: template contents with the theme applied
    """
    with open(os.path.join(TEMPLATES, name), "r") as f:
        template = f.read()
    with open(os.path.join(TEMPLATES, "theme.css"), "r") as f:
        theme = f.read()
    return template.replace("{{ theme }}", theme)


def fill(template: str, values: Dict[str, str]) -> str:
    """
    Substitute "{{ key }}" placeholders. Plain string replacement is used so
    that values containing backslashes or regex syntax are inserted verbatim.
    """
    for key, value in values.items():
        template = template.replace("{{ " + key + " }}", value)
    return template


def write_output(output_dir: str, name: str, contents: str) -> None:
    generate_output_folder(output_dir)
    with open(os.path.join(output_dir, name), "w") as f:
        f.write(contents)


def env_int(name: str, default: int) -> int:
    value = os.getenv(name, "").strip()
    try:
        return int(value) if value else default
    except ValueError:
        print(f"Ignoring non-integer value for {name}")
        return default


################################################################################
# Individual Image Generation Functions
################################################################################

async def generate_overview(s: Stats, output_dir: str = "generated") -> None:
    """
    Generate an SVG badge with summary statistics
    :param s: Represents user's GitHub statistics
    """
    lines_changed = await s.lines_changed
    output = fill(read_template("overview.svg"), {
        "name": html.escape(await s.name),
        "stars": f"{await s.stargazers:,}",
        "forks": f"{await s.forks:,}",
        "contributions": f"{await s.total_contributions:,}",
        "lines_changed": f"{lines_changed[0] + lines_changed[1]:,}",
        "views": f"{await s.views:,}",
        "repos": f"{len(await s.repos):,}",
    })
    write_output(output_dir, "overview.svg", output)


def top_languages(languages: Dict, limit: int) -> List[Tuple[str, Dict]]:
    """
    Sort languages by size, folding everything past the limit into "Other"
    :param languages: mapping of language name to size/prop/color data
    :param limit: maximum number of languages to show (0 means no limit)
    :return: list of (language, data) pairs, largest first
    """
    ordered = sorted(languages.items(), reverse=True,
                     key=lambda t: t[1].get("size", 0))
    if limit <= 0 or len(ordered) <= limit:
        return ordered
    shown, rest = ordered[:limit], ordered[limit:]
    other = {
        "size": sum(d.get("size", 0) for _, d in rest),
        "prop": sum(d.get("prop", 0) for _, d in rest),
        "color": "#8b949e",
    }
    return shown + [("Other", other)]


async def generate_languages(s: Stats, output_dir: str = "generated") -> None:
    """
    Generate an SVG badge with summary languages used
    :param s: Represents user's GitHub statistics
    """
    progress = ""
    lang_list = ""
    languages = top_languages(await s.languages, env_int("MAX_LANGUAGES", 8))
    delay_between = 150
    for i, (lang, data) in enumerate(languages):
        color = data.get("color")
        color = html.escape(color if color is not None else "#000000")
        progress += (f'<span style="background-color: {color};'
                     f'width: {data.get("prop", 0):0.3f}%;" '
                     f'class="progress-item"></span>')
        lang_list += f"""
<li style="animation-delay: {i * delay_between}ms;">
<svg xmlns="http://www.w3.org/2000/svg" class="octicon" style="fill:{color};"
viewBox="0 0 16 16" version="1.1" width="16" height="16"><path
fill-rule="evenodd" d="M8 4a4 4 0 100 8 4 4 0 000-8z"></path></svg>
<span class="lang">{html.escape(lang)}</span>
<span class="percent">{data.get("prop", 0):0.2f}%</span>
</li>

"""

    output = fill(read_template("languages.svg"), {
        "progress": progress,
        "lang_list": lang_list,
    })
    write_output(output_dir, "languages.svg", output)


def contribution_level(count: int, maximum: int) -> int:
    """
    Bucket a day's contribution count into one of five intensity levels
    """
    if count <= 0 or maximum <= 0:
        return 0
    return min(4, math.ceil(4 * count / maximum))


def render_activity(name: str,
                    days: List[Tuple[datetime.date, int]]) -> str:
    """
    Render the contribution activity card: headline stats and a heatmap
    :param name: display name of the user
    :param days: chronological list of (date, contribution count) pairs
    :return: SVG contents
    """
    cell, gap = 10, 2
    step = cell + gap
    left = 42
    top = 104

    streaks = compute_streaks(days)
    total = sum(count for _, count in days)
    best = max(days, key=lambda d: d[1], default=None)
    active = sum(1 for _, count in days if count > 0)

    def plural(n: int, word: str) -> str:
        return f"{n:,} {word}{'' if n == 1 else 's'}"

    stats = [
        (f"{total:,}", "past year total"),
        (plural(streaks["current"], "day"), "current streak"),
        (plural(streaks["longest"], "day"), "longest streak"),
        (f"{best[1]:,}" if best else "0",
         f"best day ({best[0]:%b} {best[0].day})" if best and best[1] else "best day"),
        (plural(active, "day"), "with contributions"),
    ]
    stat_width = (53 * step) / len(stats)
    stats_svg = "\n".join(
        f'<text x="{left + i * stat_width:.0f}" y="62">'
        f'<tspan class="stat-value">{html.escape(value)}</tspan>'
        f'<tspan x="{left + i * stat_width:.0f}" dy="16" class="stat-label">'
        f'{html.escape(label)}</tspan></text>'
        for i, (value, label) in enumerate(stats)
    )

    maximum = max((count for _, count in days), default=0)
    heatmap = []
    months = []
    if days:
        # Columns are weeks starting on Sunday, matching the GitHub profile
        first = days[0][0]
        start = first - datetime.timedelta(days=(first.weekday() + 1) % 7)
        columns: Dict[int, List[str]] = {}
        last_month = None
        month_starts: List[Tuple[int, str]] = []
        for date, count in days:
            offset = (date - start).days
            col, row = divmod(offset, 7)
            level = contribution_level(count, maximum)
            label = (f"{plural(count, 'contribution')} on "
                     f"{date:%b} {date.day}, {date.year}")
            columns.setdefault(col, []).append(
                f'<rect class="day level-{level}" x="{left + col * step}" '
                f'y="{top + row * step}" width="{cell}" height="{cell}">'
                f'<title>{label}</title></rect>'
            )
            # Label a month above the first week that starts inside it
            if (row == 0 or date == first) and date.month != last_month:
                last_month = date.month
                month_starts.append((col, f"{date:%b}"))
        # Drop a label when the next one starts too close to fit both
        for i, (col, month) in enumerate(month_starts):
            following = month_starts[i + 1:i + 2]
            if following and following[0][0] - col < 3:
                continue
            months.append(f'<text x="{left + col * step}" y="{top - 6}" '
                          f'class="label">{month}</text>')
        for col, cells in sorted(columns.items()):
            heatmap.append(
                f'<g class="week" style="animation-delay: {col * 12}ms">'
                + "".join(cells) + "</g>"
            )

    weekday_labels = "".join(
        f'<text x="{left - 8}" y="{top + row * step + cell - 1}" '
        f'class="label" text-anchor="end">{day}</text>'
        for row, day in ((1, "Mon"), (3, "Wed"), (5, "Fri"))
    )

    # Right-align the legend ("Less ■■■■■ More") with the heatmap
    legend_x = left + 53 * step - gap - 5 * step - 30
    legend_y = top + 7 * step + 8
    legend = (
        f'<text x="{legend_x - 6}" y="{legend_y + cell - 1}" class="label" '
        f'text-anchor="end">Less</text>'
        + "".join(
            f'<rect class="day level-{lvl}" x="{legend_x + lvl * step}" '
            f'y="{legend_y}" width="{cell}" height="{cell}" />'
            for lvl in range(5)
        )
        + f'<text x="{legend_x + 5 * step + 4}" y="{legend_y + cell - 1}" '
        f'class="label">More</text>'
    )

    return fill(read_template("activity.svg"), {
        "name": html.escape(name),
        "left": str(left),
        "stats": stats_svg,
        "months": "\n".join(months) + "\n" + weekday_labels,
        "heatmap": "\n".join(heatmap),
        "legend": legend,
    })


async def generate_activity(s: Stats, output_dir: str = "generated") -> None:
    """
    Generate an SVG card with contribution streaks and a heatmap of the past
    year of activity
    :param s: Represents user's GitHub statistics
    """
    output = render_activity(await s.name, await s.contribution_calendar)
    write_output(output_dir, "activity.svg", output)


async def generate_all(s: Stats, output_dir: str) -> None:
    await asyncio.gather(generate_languages(s, output_dir),
                         generate_overview(s, output_dir),
                         generate_activity(s, output_dir))


################################################################################
# Main Function
################################################################################

def parse_args(argv: Optional[List[str]] = None) -> argparse.Namespace:
    parser = argparse.ArgumentParser(description="Generate GitHub stats images")
    parser.add_argument("--demo", action="store_true",
                        help="render the images from built-in sample data, "
                             "without calling the GitHub API")
    parser.add_argument("--output", default=None,
                        help="directory to write images to (default: "
                             "'generated', or 'preview' with --demo)")
    return parser.parse_args(argv)


async def main(argv: Optional[List[str]] = None) -> None:
    """
    Generate all badges
    """
    args = parse_args(argv)

    if args.demo:
        from demo_data import DemoStats
        await generate_all(DemoStats(), args.output or "preview")
        return

    access_token = os.getenv("ACCESS_TOKEN")
    if not access_token:
        # access_token = os.getenv("GITHUB_TOKEN")
        raise Exception("A personal access token is required to proceed!")
    user = os.getenv("GITHUB_ACTOR")
    exclude_repos = os.getenv("EXCLUDED")
    exclude_repos = ({x.strip() for x in exclude_repos.split(",")}
                     if exclude_repos else None)
    exclude_langs = os.getenv("EXCLUDED_LANGS")
    exclude_langs = ({x.strip() for x in exclude_langs.split(",")}
                     if exclude_langs else None)
    # Convert a truthy value to a Boolean
    ignore_forked_repos = os.getenv("EXCLUDE_FORKED_REPOS")
    ignore_forked_repos = (not not ignore_forked_repos
                           and ignore_forked_repos.strip().lower() != "false")
    async with aiohttp.ClientSession() as session:
        s = Stats(user, access_token, session, exclude_repos=exclude_repos,
                  exclude_langs=exclude_langs,
                  ignore_forked_repos=ignore_forked_repos)
        await generate_all(s, args.output or "generated")

if __name__ == "__main__":
    asyncio.run(main())
