#!/usr/bin/python3

"""
Deterministic sample statistics with the same interface as `Stats`, used to
preview the generated images without a GitHub access token:

    python3 generate_images.py --demo
"""

import datetime
import random
from typing import Dict, List, Optional, Set, Tuple

from github_stats import compute_streaks


class DemoStats(object):
    def __init__(self, today: Optional[datetime.date] = None, seed: int = 7):
        self._today = today or datetime.date.today()
        self._rng = random.Random(seed)
        self._calendar = self._make_calendar()

    def _make_calendar(self) -> List[Tuple[datetime.date, int]]:
        # GitHub's calendar starts on the Sunday 52 weeks before this week
        start = self._today - datetime.timedelta(
            days=(self._today.weekday() + 1) % 7 + 52 * 7)
        days = []
        date = start
        while date <= self._today:
            weekend = date.weekday() >= 5
            if self._rng.random() < (0.55 if weekend else 0.15):
                count = 0
            else:
                count = int(self._rng.expovariate(1 / 6)) + 1
            days.append((date, count))
            date += datetime.timedelta(days=1)
        return days

    @property
    async def name(self) -> str:
        return "Octo Cat"

    @property
    async def stargazers(self) -> int:
        return 1284

    @property
    async def forks(self) -> int:
        return 213

    @property
    async def total_contributions(self) -> int:
        return 9876

    @property
    async def lines_changed(self) -> Tuple[int, int]:
        return (812345, 301234)

    @property
    async def views(self) -> int:
        return 4321

    @property
    async def repos(self) -> Set[str]:
        return {f"octocat/project-{i}" for i in range(42)}

    @property
    async def languages(self) -> Dict:
        raw = [
            ("TypeScript", 4200, "#3178c6"),
            ("Python", 3100, "#3572A5"),
            ("Go", 1800, "#00ADD8"),
            ("Rust", 1200, "#dea584"),
            ("JavaScript", 900, "#f1e05a"),
            ("HTML", 600, "#e34c26"),
            ("CSS", 400, "#663399"),
            ("Shell", 250, "#89e051"),
            ("Dockerfile", 120, "#384d54"),
            ("Makefile", 60, "#427819"),
        ]
        total = sum(size for _, size, _ in raw)
        return {
            name: {"size": size, "occurrences": 1, "color": color,
                   "prop": 100 * size / total}
            for name, size, color in raw
        }

    @property
    async def contribution_calendar(self) -> List[Tuple[datetime.date, int]]:
        return self._calendar

    @property
    async def streaks(self) -> Dict[str, int]:
        return compute_streaks(self._calendar)
