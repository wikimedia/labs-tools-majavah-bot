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


def remap_country(
    name: str, country: Optional[str], overrides: Dict[str, Dict[str, Any]]
) -> str:
    # Turn 'Bar, Foo' into 'Foo Bar'
    overrides_key = " ".join(name.split(", ", 1)[::-1])
    if overrides_key in overrides and "country" in overrides[overrides_key]:
        return overrides[overrides_key]["country"]

    if not country:
        return ""

    return country.lstrip(" (").rstrip(")")


class SyncTennisStatsTask(Task):
    def __init__(self, number, name, site, family):
        super().__init__(number, name, site, family)
        self.register_task_configuration("User:MajavahBot/ATP rankings updater")
        self.merge_task_configuration(
            enable=True,
            summary="Bot: Updating rankings data",
            overrides_page="Module:ATP rankings/data/overrides.json",
            singles_result="Module:ATP rankings/data/singles.json",
        )

    def download_and_parse(
        self, url: str, overrides: Dict[str, Dict[str, Any]]
    ) -> Tuple[List[Ranking], Optional[str]]:
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
                        country=remap_country(
                            match.group("name"), match.group("country"), overrides
                        ),
                        rank=int(match.group("rank")),
                        tied=match.group("tied").strip() != "",
                        points=int(match.group("points")),
                    )
                )

        LOGGER.info("Got data for %s players on %s", len(players), update_date)
        return players, update_date

    def process_pdf(
        self, url: str, target_page: str, overrides: Dict[str, Dict[str, Any]]
    ):
        players, update_date = self.download_and_parse(url, overrides)

        if len(players) < 100:
            raise Exception("Got data for suspiciously few players!")

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

        overrides = json.loads(
            self.get_mediawiki_api()
            .get_page(self.get_task_configuration("overrides_page"))
            .get()
        )

        self.process_pdf(
            SINGLES_PDF_URL, self.get_task_configuration("singles_result"), overrides
        )


task_registry.add_task(
    SyncTennisStatsTask(
        "sync-tennis-stats", "Tennis statistics sync", "en", "wikipedia"
    )
)
