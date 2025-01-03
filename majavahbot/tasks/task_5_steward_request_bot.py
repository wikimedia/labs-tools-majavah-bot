import collections
import ipaddress
import logging
from datetime import datetime, timezone
from typing import Any, Dict, List, Optional

import mwparserfromhell
import pywikibot
from mwparserfromhell.wikicode import Wikicode
from pywikibot.data.api import QueryGenerator

from majavahbot.api.manual_run import confirm_edit
from majavahbot.api.mediawiki import MediawikiApi
from majavahbot.api.utils import remove_empty_lines_before_replies, was_enough_time_ago
from majavahbot.tasks import Task, task_registry

LOGGER = logging.getLogger(__name__)

OPEN_STATUSES = ("", "hold", "onhold", "on hold", "in progress", "inprogress")


def add_archived_sections(
    original_page: str, add_sections: dict[str, list[str]]
) -> str:
    parsed = mwparserfromhell.parse(original_page)
    top_level_sections = parsed.get_sections(levels=[2])

    for tls in top_level_sections:
        tls_header = tls.filter_headings()[0]
        if not tls_header:
            continue
        tls_header_text = tls_header.title.strip()
        if tls_header_text in add_sections:
            tls.append("\n" + "\n".join(add_sections[tls_header_text]) + "\n")
            del add_sections[tls_header_text]

    for title, section in add_sections.items():
        data = "\n".join(section)
        parsed.append(f"\n== {title} ==\n{data}\n")

    return str(parsed)


def is_closed(section: Wikicode, custom_templates: list[str]) -> bool:
    templates = [
        template
        for template in section.filter_templates()
        if (
            any([template.name.matches(name) for name in custom_templates])
            if custom_templates
            else template.name.matches("status")
        )
    ]

    if not templates:
        return False

    template = templates[0]
    param = "status" if custom_templates else 1

    if not template.has(param):
        return False

    return (
        "".join([str(t) for t in template.get(param).value.filter_text()])
        .lower()
        .strip()
        not in OPEN_STATUSES
    )


def create_archive_page_name(*, template: str, base: str, time: datetime) -> str:
    year = str(time.year)
    week = time.strftime("%W")

    return template.format(
        page=base,
        year=year,
        month=str(time.month).zfill(2),
        week=week,
    )


class StewardRequestTask(Task):
    def __init__(self, task_id: str, name: str, site: str, family: str) -> None:
        super().__init__(task_id, name, site, family)
        self.register_task_configuration(
            "User:MajavahBot/Steward Request Helper Configuration"
        )
        self.supports_manual_run = True

    def get_steward_who_gblocked_ip(
        self, api: MediawikiApi, ip_or_range: str
    ) -> str | None:
        try:
            data = QueryGenerator(
                site=api.get_site(),
                list="globalblocks",
                bgip=ip_or_range,
            ).request.submit()["query"]["globalblocks"]
        except pywikibot.exceptions.APIError as e:
            if e.code == "cidrtoobroad":
                return None
            raise

        if len(data) == 0:
            return None

        if not was_enough_time_ago(
            data[0]["timestamp"], self.get_task_configuration("mark_done_min_time")
        ):
            return None

        return data[0]["by"]

    def _get_steward_who_blocked_account_global_block(
        self, entry: Dict[str, Any]
    ) -> str | None:
        if not was_enough_time_ago(
            entry["timestamp"], self.get_task_configuration("mark_done_min_time")
        ):
            return None
        return entry["by"]

    def _get_steward_who_blocked_account_lock(
        self, entry: Dict[str, Any]
    ) -> Optional[str]:
        params = entry["params"]

        if entry["action"] == "delete":
            return None

        if "added" in params:
            if "locked" not in params["added"]:
                return None
        else:
            # B/C for old log entries
            if "locked" not in params["0"]:
                return None

        if not was_enough_time_ago(
            entry["timestamp"], self.get_task_configuration("mark_done_min_time")
        ):
            return None

        return entry["user"]

    def get_steward_who_blocked_account(
        self, api: MediawikiApi, account_name: str
    ) -> str | None:
        data = QueryGenerator(
            site=api.get_site(),
            list="globalblocks|logevents",
            bgtargets=account_name,
            letype="globalauth",
            letitle="User:" + account_name + "@global",
        ).request.submit()["query"]

        if len(data["globalblocks"]) >= 1:
            user = self._get_steward_who_blocked_account_global_block(
                data["globalblocks"][0]
            )
            if user:
                return user

        if len(data["logevents"]) >= 1:
            user = self._get_steward_who_blocked_account_lock(data["logevents"][0])
            if user:
                return user

        return None

    def process_srp_section(self, api: MediawikiApi, section: Wikicode) -> bool:
        header = section.filter_headings()[0]
        if not header:
            return False  # ???

        status = None

        accounts = set()
        ips = set()

        awesome_people = set()

        for template in section.filter_templates():
            if template.name.matches("status"):
                status = template
            elif (
                template.name.matches("LockHide")
                or template.name.matches("MultiLock")
                or template.name.matches("Multilock")
                or template.name.matches("Luxotool")
                or template.name.matches("MultiLockHide")
            ):
                for param in template.params:
                    if not param.can_hide_key(param.name):
                        continue
                    param_text = param.value.strip_code().strip()
                    if len(param_text) == 0:
                        continue

                    validate_text = param_text
                    if validate_text.count("/") == 1:
                        first, second = validate_text.split("/")

                        # if the part after the slash is numeric, check if the part before is an ip
                        # so CIDR ranges are checked if they are globally blocked instead of locked
                        if second.isdigit():
                            # since some people suggest blocking ranges larger than /16, don't crash
                            second = int(second)
                            if second > 16:
                                validate_text = first

                    try:
                        ipaddress.ip_address(validate_text)
                        ips.add(param_text)
                    except ValueError:
                        accounts.add(param_text)

        if not status:
            return False
        if status.has(1) and status.get(1).value != "":
            return status.get(1).value.lower() not in OPEN_STATUSES

        if ("unlock" in header and "/unlock" not in header) or (
            "unblock" in header and "/unblock" not in header
        ):
            LOGGER.info(
                "Assuming section '%s' is a un(b)lock request, skipping", header
            )
            return False

        mark_done = True

        for ip in ips:
            steward = self.get_steward_who_gblocked_ip(api, ip)
            if steward is None:
                mark_done = False
            else:
                awesome_people.add(steward)

        for account in accounts:
            steward = self.get_steward_who_blocked_account(api, account)
            if steward is None:
                mark_done = False
            else:
                awesome_people.add(steward)

        if not mark_done or len(awesome_people) == 0:
            return False

        # remove duplicates
        awesome_people_str = ", ".join(sorted(awesome_people))

        if mark_done:
            status.add(1, "done")
            section.append(
                ": '''Robot clerk note:''' {{done}} by "
                + awesome_people_str
                + ". ~~~~\n"
            )

        return False

    def process_page(
        self,
        *,
        api: MediawikiApi,
        page: str,
        archive_format: str,
        archive_header: str,
        is_srg: bool,
        custom_templates: list[str],
    ) -> None:
        LOGGER.info("processing page %s", page)
        request_page = api.get_page(page)
        request_original_text = request_page.get(force=True)

        parsed = mwparserfromhell.parse(request_page.get(force=True))
        top_level_sections = parsed.get_sections(levels=[2])

        to_archive = collections.defaultdict(list)

        for tls in top_level_sections:
            sections = tls.get_sections(levels=[3])

            tls_header = tls.filter_headings()[0]
            if not tls_header:
                return
            tls_header_text = tls_header.title.strip()

            for section in sections:
                if is_srg:
                    is_complete = self.process_srp_section(api, section)
                else:
                    is_complete = is_closed(section, custom_templates)

                if not is_complete:
                    continue

                last_reply = api.get_last_reply(str(section))
                if last_reply is None:
                    continue
                if (
                    datetime.now(tz=timezone.utc) - last_reply
                ).total_seconds() <= self.get_task_configuration("archive_min_time"):
                    continue

                LOGGER.info("Archiving section %s", section)
                to_archive[tls_header_text].append(str(section).strip())
                parsed.replace(section, "")

        new_text = str(parsed)
        new_text = remove_empty_lines_before_replies(new_text)

        if new_text != request_original_text and (
            not self.is_manual_run or confirm_edit()
        ):
            api.site.login()

            if len(to_archive.keys()) > 0:
                archive_page_name = create_archive_page_name(
                    template=archive_format, base=page, time=datetime.now()
                )
                archive_page = api.get_page(archive_page_name)
                if archive_page.exists():
                    archive_page_original_text = archive_page.get(force=True)
                else:
                    archive_page_original_text = archive_header

                archive_page.text = add_archived_sections(
                    archive_page_original_text, to_archive
                )

                archive_page.save(
                    self.get_task_configuration("summary"),
                    botflag=self.should_use_bot_flag(),
                )

            request_page.text = new_text
            request_page.save(
                self.get_task_configuration("summary"),
                botflag=self.should_use_bot_flag(),
            )

    def run(self) -> None:
        self.merge_task_configuration(
            run=True,
            srg_page="Steward requests/Global",
            srg_archive_page_format="{page}/{year}-w{week}",
            archive_pages=[
                {
                    "page": "Steward requests/Bot status",
                    "archive_format": "{page}/{year}-{month}",
                    "custom_templates": ["sr-request"],
                },
                {
                    "page": "Steward requests/Checkuser",
                    "archive_format": "{page}/{year}-{month}",
                    "custom_templates": ["CU request"],
                },
                {
                    "page": "Steward requests/Global permissions",
                    "archive_format": "{page}/{year}-{month}",
                    "custom_templates": ["sr-request"],
                },
                {
                    "page": "Steward requests/Miscellaneous",
                    "archive_format": "{page}/{year}-{month}",
                },
                # TODO: different header levels
                # {
                #     "page": "Steward requests/Permissions",
                #     "archive_format": "{page}/{year}-{month}",
                # },
                {
                    "page": "Steward requests/Username changes",
                    "archive_format": "{page}/{year}-{month}",
                    "custom_templates": ["SRUC"],
                },
            ],
            summary="Bot clerking",
            mark_done_min_time=5 * 60,
            archive_min_time=8 * 60 * 60,
        )

        if self.get_task_configuration("run") is not True:
            LOGGER.error("Disabled in configuration")
            return

        api = self.get_mediawiki_api()

        self.process_page(
            api=api,
            page=self.get_task_configuration("srg_page"),
            archive_format=self.get_task_configuration("srg_archive_page_format"),
            archive_header="{{Steward request archive header}}\n",
            is_srg=True,
            custom_templates=[],
        )

        for page in self.get_task_configuration("archive_pages"):
            self.process_page(
                api=api,
                page=page["page"],
                archive_format=page["archive_format"],
                archive_header=page.get(
                    "archive_header", "{{Steward request archive header}}\n"
                ),
                is_srg=False,
                custom_templates=page.get("custom_templates"),
            )


task_registry.add_task(StewardRequestTask("5", "Steward request bot", "meta", "meta"))
