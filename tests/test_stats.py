import asyncio
import datetime
import os
import sys
import xml.dom.minidom

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

import generate_images  # noqa: E402
from demo_data import DemoStats  # noqa: E402
from github_stats import Stats, compute_streaks  # noqa: E402


def calendar(counts, end=datetime.date(2026, 10, 3)):
    start = end - datetime.timedelta(days=len(counts) - 1)
    return [(start + datetime.timedelta(days=i), c)
            for i, c in enumerate(counts)]


class FakeQueries:
    """Stands in for `Queries` so `Stats` can be tested without the network"""

    def __init__(self, graphql=None, rest=None):
        self.graphql = graphql or []
        self.rest = rest or {}

    async def query(self, generated_query):
        return self.graphql.pop(0)

    async def query_rest(self, path, params=None):
        return self.rest.get(path, {})


def make_stats(username="octocat", **fake):
    s = Stats(username, "token", session=None)
    s.queries = FakeQueries(**fake)
    return s


def repo(name, stars=0, forks=0, langs=()):
    return {
        "nameWithOwner": name,
        "stargazers": {"totalCount": stars},
        "forkCount": forks,
        "languages": {"edges": [
            {"size": size, "node": {"name": lang, "color": "#123456"}}
            for lang, size in langs
        ]},
    }


def overview(owned, contributed=()):
    page = {"hasNextPage": False, "endCursor": None}
    return {"data": {"viewer": {
        "login": "octocat", "name": "Octo Cat",
        "repositories": {"pageInfo": page, "nodes": list(owned)},
        "repositoriesContributedTo": {"pageInfo": page,
                                      "nodes": list(contributed)},
    }}}


# Streaks ######################################################################

def test_streaks_basic():
    assert compute_streaks(calendar([1, 1, 0, 1, 1, 1, 0, 2])) == \
        {"current": 1, "longest": 3}


def test_quiet_today_does_not_break_current_streak():
    assert compute_streaks(calendar([0, 3, 4, 5, 0])) == \
        {"current": 3, "longest": 3}


def test_streak_broken_by_quiet_yesterday():
    assert compute_streaks(calendar([5, 5, 0, 0]))["current"] == 0


def test_streaks_empty():
    assert compute_streaks([]) == {"current": 0, "longest": 0}


# Stats ########################################################################

def test_get_stats_aggregates_and_dedupes_repos():
    s = make_stats(graphql=[overview(
        [repo("me/a", 3, 1, [("Python", 300)]),
         repo("me/b", 2, 0, [("Python", 100), ("Go", 100)])],
        [repo("me/a", 3, 1), repo("org/c", 10, 5, [("Go", 500)])],
    )])
    asyncio.run(s.get_stats())
    assert asyncio.run(s.name) == "Octo Cat"
    assert asyncio.run(s.stargazers) == 15
    assert asyncio.run(s.forks) == 6
    assert asyncio.run(s.repos) == {"me/a", "me/b", "org/c"}
    langs = asyncio.run(s.languages)
    assert langs["Go"]["size"] == 600
    assert round(langs["Python"]["prop"], 6) == 40


def test_get_stats_without_languages_does_not_divide_by_zero():
    s = make_stats(graphql=[overview([repo("me/empty")])])
    asyncio.run(s.get_stats())
    assert asyncio.run(s.languages) == {}


def test_lines_changed_matches_username_case_insensitively():
    contributors = [
        {"author": {"login": "OctoCat"}, "weeks": [{"a": 10, "d": 2}]},
        {"author": {"login": "someone"}, "weeks": [{"a": 99, "d": 99}]},
        "malformed",
    ]
    s = make_stats(rest={"/repos/me/a/stats/contributors": contributors,
                         "/repos/me/b/stats/contributors": {}})
    s._repos = {"me/a", "me/b"}
    assert asyncio.run(s.lines_changed) == (10, 2)


def test_views_sums_across_repos():
    s = make_stats(rest={
        "/repos/me/a/traffic/views": {"views": [{"count": 3}, {"count": 4}]},
        "/repos/me/b/traffic/views": {"message": "Not Found"},
    })
    s._repos = {"me/a", "me/b"}
    assert asyncio.run(s.views) == 7


def test_contribution_calendar_is_flattened_and_sorted():
    weeks = [
        {"contributionDays": [{"date": "2026-09-28", "contributionCount": 2},
                              {"date": "2026-09-27", "contributionCount": 1}]},
        {"contributionDays": [{"date": "2026-10-01", "contributionCount": 0}]},
    ]
    s = make_stats(graphql=[{"data": {"viewer": {"contributionsCollection": {
        "contributionCalendar": {"weeks": weeks}}}}}])
    days = asyncio.run(s.contribution_calendar)
    assert [d.isoformat() for d, _ in days] == \
        ["2026-09-27", "2026-09-28", "2026-10-01"]


# Image generation #############################################################

def test_fill_inserts_values_verbatim():
    assert generate_images.fill("hi {{ name }}", {"name": r"a\1 $b"}) == \
        r"hi a\1 $b"


def test_top_languages_folds_tail_into_other():
    langs = {f"L{i}": {"size": 10 - i, "prop": 10.0 - i} for i in range(5)}
    result = generate_images.top_languages(langs, 3)
    assert [name for name, _ in result] == ["L0", "L1", "L2", "Other"]
    assert result[-1][1]["prop"] == 7 + 6
    assert len(generate_images.top_languages(langs, 0)) == 5


def test_contribution_levels():
    level = generate_images.contribution_level
    assert [level(c, 8) for c in (0, 1, 2, 3, 4, 6, 8, 20)] == \
        [0, 1, 1, 2, 2, 3, 4, 4]
    assert level(5, 0) == 0


def test_demo_render_produces_valid_svgs(tmp_path):
    stats = DemoStats(today=datetime.date(2026, 10, 3))
    asyncio.run(generate_images.generate_all(stats, str(tmp_path)))
    for name in ("overview.svg", "languages.svg", "activity.svg"):
        contents = (tmp_path / name).read_text()
        assert "{{" not in contents, name
        xml.dom.minidom.parseString(contents)
    activity = (tmp_path / "activity.svg").read_text()
    # 2026-10-03 is a Saturday, so all 53 weeks are full, plus 5 legend cells
    assert activity.count('class="day level-') == 53 * 7 + 5


def test_names_are_escaped(tmp_path):
    svg = generate_images.render_activity("<b>&</b>", calendar([1, 2]))
    assert "&lt;b&gt;&amp;&lt;/b&gt;" in svg
    xml.dom.minidom.parseString(svg)


def test_concurrent_callers_share_one_overview_query():
    s = make_stats(graphql=[overview([repo("me/a", 4, 1, [("Go", 10)])])])

    async def run():
        return await asyncio.gather(s.stargazers, s.forks, s.languages, s.name)

    stars, forks, _, name = asyncio.run(run())
    assert (stars, forks, name) == (4, 1, "Octo Cat")
