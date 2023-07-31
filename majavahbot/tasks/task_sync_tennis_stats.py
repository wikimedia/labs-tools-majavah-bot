import json
import logging
import os
import re
from collections import defaultdict
from dataclasses import dataclass
from tempfile import NamedTemporaryFile
from typing import Any, Dict, List, Optional, Tuple

import pypdf
import requests

from majavahbot.tasks import Task, task_registry

LOGGER = logging.getLogger(__name__)

SINGLES_PDF_URL = (
    "https://www.protennislive.com/posting/ramr/singles_entry_numerical.pdf"
)

ROW_RE = re.compile(
    r"^(?P<rank>\d+)(?P<tied> *T?) +(?P<name>[^(0-9]+)(?P<country> \([A-Z]{3}\))? (?P<points>\d+)"
)


@dataclass(frozen=True)
class Ranking:
    name: str
    country: str
    points: int
    rank: int
    tied: bool


class SyncTennisStatsTask(Task):
    def __init__(self, number, name, site, family):
        super().__init__(number, name, site, family)
        self.register_task_configuration("User:MajavahBot/ATP rankings updater")
        self.merge_task_configuration(
            enable=True,
            summary="Bot: Updating rankings data",
            singles_result="Module:ATP rankings/data/singles.json",
        )

    def remap_country(self, name: str, country: Optional[str]) -> str:
        # TODO: do something for Russia etc where the official stats don't have a country

        if not country:
            return ""

        return country.lstrip(" (").rstrip(")")

    def download_and_parse(self, url: str) -> Tuple[List[Ranking], Optional[str]]:
        f = None
        try:
            with NamedTemporaryFile(delete=False) as f:
                LOGGER.info("Downloading stats PDF from %s", url)
                response = requests.get(url)
                response.raise_for_status()
                f.write(response.content)

            LOGGER.info("Parsing the downloaded PDF")
            parser = pypdf.PdfReader(f.name)
        finally:
            if f:
                os.unlink(f.name)

        LOGGER.info("Extracting ranking data")
        update_date = ""
        players: List[Ranking] = []

        for page in parser.pages:
            text = page.extract_text()

            if update_date == "" and "Report as of" in text:
                update_date = text[
                    text.find("Report as of") + len("Report as of") :
                ].strip()

            for row in text.split("\n"):
                match = ROW_RE.match(row)
                if not match:
                    continue
                players.append(
                    Ranking(
                        name=match.group("name"),
                        country=self.remap_country(
                            match.group("name"), match.group("country")
                        ),
                        rank=int(match.group("rank")),
                        tied=match.group("tied").strip() != "",
                        points=int(match.group("points")),
                    )
                )

        return players, update_date

    def process_pdf(self, url: str, target_page: str):
        players, update_date = self.download_and_parse(url)
        LOGGER.info("Formatting rankings for the required on-wiki format")

        per_country: Dict[str, List[Dict[str, Any]]] = defaultdict(list)

        for player in sorted(players, key=lambda p: p.rank):
            if player.country == "":
                continue
            if len(per_country[player.country]) >= 15:
                # Template shows top 10, but sync top 15 to provide enough change information
                continue

            per_country[player.country].append(
                {
                    "name": player.name,
                    "rank": player.rank,
                    "tied": player.tied,
                    "points": player.points,
                }
            )

        new_data = {
            "per-country": per_country,
            "as-of": update_date,
        }

        previous_data = new_data
        page = self.get_mediawiki_api().get_page(target_page)
        if page.exists():
            current_version = json.loads(page.get())
            if current_version["current"]["as-of"] != new_data["as-of"]:
                previous_data = current_version["current"]
            else:
                previous_data = current_version["previous"]

        page.text = json.dumps(
            {
                "current": new_data,
                "previous": previous_data,
            },
            sort_keys=True,
        )

        LOGGER.info("Updating on-wiki JSON page")

        page.save(self.get_task_configuration("summary"))

    def run(self):
        if self.get_task_configuration("enable") is not True:
            LOGGER.error("Disabled in configuration")
            return

        self.process_pdf(SINGLES_PDF_URL, self.get_task_configuration("singles_result"))


task_registry.add_task(
    SyncTennisStatsTask(
        "sync-tennis-stats", "Tennis statistics sync", "en", "wikipedia"
    )
)
