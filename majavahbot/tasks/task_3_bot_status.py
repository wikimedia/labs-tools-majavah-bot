import sys
from datetime import datetime
from typing import List, Optional

import mwparserfromhell
from pywikibot.data.api import QueryGenerator

from majavahbot.api.consts import HUMAN_DATE_FORMAT, MEDIAWIKI_DATE_FORMAT
from majavahbot.api.utils import create_delay
from majavahbot.tasks import Task, task_registry

# Groups in this array will not be shown as additional user rights
STANDARD_GROUPS = ["bot", "*", "user", "autoconfirmed", "extendedconfirmed"]

PAGE_NAME = "User:MajavahBot/Bot status report"

TABLE_HEADER = """
{{botnav}}
{| class="wikitable sortable" style="width:100%"
|-
! style="width: 10%;" | Bot account
! style="width: 10%;" | Operator(s)
! style="width: 10%;" | Total edits
! style="width: 10%;" | Last activity (UTC)
! style="width: 10%;" | Last edit (UTC)
! style="width: 10%;" | Last logged action (UTC)
! style="width: 10%;" | Last operator activity (UTC)
! style="width: 30%;" | Extra details
"""

TABLE_ROW_FORMAT = """
|-
| {{no ping|%s}}
| %s
| %s
| %s
| %s
| %s
| %s
| %s
"""

EMPTY_COLUMN = "{{center|—}}"


class BotStatusData:
    def __init__(
        self,
        *,
        name: str,
        operators: List[str],
        last_edit_timestamp: Optional[str],
        last_log_timestamp: Optional[str],
        last_operator_activity_timestamp: Optional[str],
        edit_count: Optional[int],
        groups: Optional[List[str]],
        block_data: Optional[dict],
    ):
        self.name = name
        self.operators = set(operators)

        self.last_edit_timestamp = None
        self.last_log_timestamp = None
        self.last_activity_timestamp = None
        self.last_operator_activity_timestamp = None

        if last_edit_timestamp is not None:
            self.last_edit_timestamp = self.parse_date(last_edit_timestamp)
            self.last_activity_timestamp = self.last_edit_timestamp

        if last_log_timestamp is not None:
            self.last_log_timestamp = self.parse_date(last_log_timestamp)
            if self.last_edit_timestamp is None:
                self.last_activity_timestamp = self.last_log_timestamp
            else:
                self.last_activity_timestamp = max(
                    self.last_log_timestamp, self.last_edit_timestamp
                )

        if last_operator_activity_timestamp:
            self.last_operator_activity_timestamp = last_operator_activity_timestamp

        self.edit_count = edit_count

        if groups:
            self.groups = list(filter(lambda x: x not in STANDARD_GROUPS, groups))
        else:
            self.groups = []

        self.block_data = block_data

    @staticmethod
    def new_for_unknown(name: str) -> "BotStatusData":
        return BotStatusData(
            name=name,
            operators=[],
            last_edit_timestamp=None,
            last_log_timestamp=None,
            last_operator_activity_timestamp=None,
            edit_count=None,
            groups=None,
            block_data=None,
        )

    def format_number(self, number: Optional[int], sortkey=True):
        if not number:
            return EMPTY_COLUMN

        if sortkey:
            return 'class="nowrap" data-sort-value={} | {:,}'.format(number, number)
        return "{:,}".format(number)

    def parse_date(self, string):
        if string is None:
            return None
        return datetime.strptime(string, MEDIAWIKI_DATE_FORMAT)

    def format_date(self, date, sortkey=True):
        if date is None:
            return EMPTY_COLUMN

        if sortkey:
            return 'class="nowrap" data-sort-value={} | {}'.format(
                date.strftime(MEDIAWIKI_DATE_FORMAT), date.strftime(HUMAN_DATE_FORMAT)
            )

        return date.strftime(HUMAN_DATE_FORMAT)

    def format_block_reason(self):
        return (
            self.block_data["reason"]
            .replace("[[Category:", "[[:Category:")
            .replace("[[category:", "[[:category:")
            .replace("{", "&#123;")
            .replace("<", "&lt;")
            .replace(">", "&gt;")
        )

    def format_block(self):
        date = self.parse_date(self.block_data["at"])

        return (
            "data-sort-value=%s | %s by {{no ping|%s}} on %s%s.<br/>Block reason is '%s{{'}}"
            % (
                date.strftime(MEDIAWIKI_DATE_FORMAT),
                "Partially blocked" if self.block_data["partial"] else "Blocked",
                self.block_data["by"],
                self.format_date(date, sortkey=False),
                "to expire at {}".format(
                    self.format_date(self.block_data["expiry"], sortkey=False)
                )
                if self.block_data["expiry"] != "infinite"
                else "",
                self.format_block_reason(),
            )
        )

    def format_extra_details(self):
        details = []

        if len(self.groups) > 0:
            details.append("Extra groups: " + ", ".join(self.groups))
        if self.block_data is not None:
            details.append(self.format_block())

        return "\n----\n".join(details)

    def to_table_row(self):
        return TABLE_ROW_FORMAT % (
            self.name,
            self.format_operators(),
            self.format_number(self.edit_count),
            self.format_date(self.last_activity_timestamp),
            self.format_date(self.last_edit_timestamp),
            self.format_date(self.last_log_timestamp),
            self.format_date(self.last_operator_activity_timestamp),
            self.format_extra_details(),
        )

    def format_operators(self):
        if len(self.operators) == 0:
            return EMPTY_COLUMN
        return "{{no ping|" + "}}, {{no ping|".join(sorted(self.operators)) + "}}"


class BotStatusTask(Task):
    def __init__(self, number, name, site, family):
        super().__init__(number, name, site, family)

    def get_bot_data(self, username):
        # get all data needed with one big query
        data = QueryGenerator(
            site=self.get_mediawiki_api().get_site(),
            prop="revisions",
            list="users|usercontribs|logevents",
            # for prop=revisions
            titles="User:" + username,
            redirects=True,
            rvprop="content",
            rvslots="main",
            rvlimit="1",
            # for list=usercontribs
            uclimit=1,
            ucuser=username,
            ucdir="older",
            ucprop="ids|timestamp",
            # for list=users
            usprop="blockinfo|groups|editcount",
            ususers=username,
            # for list=logevents
            lelimit=1,
            leuser=username,
            ledir="older",
            leprop="ids|timestamp",
        ).request.submit()
        if "query" in data:
            data = data["query"]

            block = None
            if "blockid" in data["users"][0]:
                block = {
                    "id": data["users"][0]["blockid"],
                    "by": data["users"][0]["blockedby"],
                    "reason": data["users"][0]["blockreason"],
                    "at": data["users"][0]["blockedtimestamp"],
                    "expiry": data["users"][0]["blockexpiry"],
                    "partial": "blockpartial" in data["users"][0],
                }

            operators = []
            for page_id in data["pages"]:
                if page_id == "-1":
                    continue
                page = data["pages"][page_id]
                if page["title"] == "User:" + username and "missing" not in page:
                    page_text = page["revisions"][0]["slots"]["main"]["*"]
                    parsed = mwparserfromhell.parse(page_text)
                    for template in parsed.filter_templates():
                        if template.name.matches("Bot") or template.name.matches(
                            "Bot2"
                        ):
                            for param in template.params:
                                if not param.can_hide_key(param.name):
                                    continue
                                param_text = param.value.strip_code()
                                if len(param_text) == 0:
                                    continue
                                operators.append(param_text)

            operator_activity = None
            for operator in operators:
                LOGGER.info("- Loading data for operator %s", operator)
                try:
                    operator_activity_data = QueryGenerator(
                        site=self.get_mediawiki_api().get_site(),
                        list="usercontribs|logevents",
                        # for list=usercontribs
                        uclimit=1,
                        ucuser=operator,
                        ucdir="older",
                        ucprop="ids|timestamp",
                        # for list=logevents
                        lelimit=1,
                        leuser=operator,
                        ledir="older",
                        leprop="ids|timestamp",
                    ).request.submit()
                except Exception as e:
                    # TODO: make better error handling
                    LOGGER.error("Failed to load operator data", excinfo=True)

                    continue

                if "query" in operator_activity_data:
                    if len(operator_activity_data["query"]["usercontribs"]) > 0:
                        last_edit = datetime.strptime(
                            operator_activity_data["query"]["usercontribs"][0][
                                "timestamp"
                            ],
                            MEDIAWIKI_DATE_FORMAT,
                        )

                        if operator_activity is None:
                            operator_activity = last_edit
                        else:
                            operator_activity = max(operator_activity, last_edit)

                    if len(operator_activity_data["query"]["logevents"]) > 0:
                        last_log = datetime.strptime(
                            operator_activity_data["query"]["logevents"][0][
                                "timestamp"
                            ],
                            MEDIAWIKI_DATE_FORMAT,
                        )

                        if operator_activity is None:
                            operator_activity = last_log
                        else:
                            operator_activity = max(operator_activity, last_log)

            return BotStatusData(
                name=data["users"][0]["name"],
                operators=operators,
                last_edit_timestamp=(
                    None
                    if len(data["usercontribs"]) == 0
                    else data["usercontribs"][0]["timestamp"]
                ),
                last_log_timestamp=(
                    None
                    if len(data["logevents"]) == 0
                    else data["logevents"][0]["timestamp"]
                ),
                last_operator_activity_timestamp=operator_activity,
                edit_count=data["users"][0]["editcount"],
                groups=data["users"][0]["groups"],
                block_data=block,
            )

        raise Exception("Failed loading bot data for " + username + ": " + str(data))

    def run(self):
        api = self.get_mediawiki_api()
        table = str(TABLE_HEADER)

        for user in api.get_site().allusers(group="bot"):
            delay = create_delay(5)
            username = user["name"]
            LOGGER.info("Loading data for bot %s", username)
            try:
                data = self.get_bot_data(username)
            except Exception as e:
                # TODO: make better error handling
                LOGGER.error("Failed to load bot data for %s", username, excinfo=True)

                data = BotStatusData.new_for_unknown(username)

            table += data.to_table_row()
            # to not create unnecessary lag, let's process max 1 bot in 5 seconds as speed is not needed on cronjobs
            delay.wait()

        table += "|}"

        page = api.get_page(PAGE_NAME)
        page.text = table
        page.save("Bot updating status report", botflag=self.should_use_bot_flag())


task_registry.add_task(BotStatusTask(3, "Bot status report", "en", "wikipedia"))
