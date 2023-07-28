import datetime
import logging
import re
import traceback
from functools import lru_cache

import mwparserfromhell
from pywikibot import Page
from pywikibot.exceptions import PageRelatedError

from majavahbot.api.database import ReplicaDatabase
from majavahbot.api.manual_run import confirm_edit
from majavahbot.tasks import Task, task_registry

LOGGER = logging.getLogger(__name__)

MOVED_REGEX = re.compile(
    r"(?:[a-zA-Z0-9 .]+ )?moved (?:page )?\[\[([^]]+)]] to \[\[([^]]+)]]"
)


QUERY = """
select
    page_id,
    page_title
from page
where
    page_namespace = 1
    and exists (
        select 1
        from categorylinks
        where cl_from = page_id
        and cl_to = "Pages_with_a_missing_DYK_entry"
    )
    and exists (
        select 1
        from templatelinks
        where tl_from = page_id
    )
order by page_title
limit 1000;
"""


MONTH_REPLACEMENTS = {
    "Jan": "January",
    "Feb": "February",
    "Mar": "March",
    "Apr": "April",
    "May": "May",
    "Jun": "June",
    "Jul": "July",
    "Aug": "August",
    "Sep": "September",
    "Oct": "October",
    "Nov": "November",
    "Dec": "December",
}


NAME_REPLACEMENTS = {
    re.compile(
        r"{{(?:ship|warship)\|([a-zA-Z0-9\- ]+)\|([a-zA-Z0-9\- ]+)}}"
    ): r"[[\g<1> \g<2>]]",
    re.compile(
        r"{{(?:ship|warship)\|([a-zA-Z0-9\- ]+)\|([a-zA-Z0-9\- ]+)\|([a-zA-Z0-9\- ]+)}}"
    ): r"[[\g<1> \g<2> (\g<3>)]]",
    re.compile(
        r"{{sclass\|([a-zA-Z0-9\- ]+)\|([a-zA-Z0-9\- ]+)(?:\|\d)?}}"
    ): r"[[\g<1> class \g<2>]]",
}

for name in ["hms", "hmas", "hmt", "sms", "ss", "usat", "uss"]:
    NAME_REPLACEMENTS[re.compile(r"{{" + name + r"\|([a-zA-Z0-9\- ]+)}}")] = (
        r"[[" + name + r" \g<1>]]"
    )
    NAME_REPLACEMENTS[
        re.compile(
            r"{{" + name + r"\|([a-zA-Z0-9\- ]+)\|([a-zA-Z0-9\- ]+)(\|[0-9]+)?}}"
        )
    ] = (r"[[" + name + r" \g<1> (\g<2>)]]")


ARTICLE_HISTORY_PARAMS = {
    "dykdate": "dykentry",
    "dyk1date": "dyk1entry",
    "dyk2date": "dyk2entry",
}


class DykEntryTalkTask(Task):
    def __init__(self, number, name, site, family):
        super().__init__(number, name, site, family)
        self.supports_manual_run = True
        self.register_task_configuration("User:MajavahBot/DYK options")

    @lru_cache()
    def get_archive_page(self, year, month):
        archive_page_name = "Wikipedia:Recent additions/" + str(year) + "/" + str(month)
        try:
            return self.get_mediawiki_api().get_page(archive_page_name).get()
        except PageRelatedError:
            LOGGER.info("Failed getting page for %s %s", year, month)
            traceback.print_exc()
            return ""

    def get_entry_for_page(self, year, month, day, page: Page):
        # for weird syntax
        if month.endswith(","):
            month = month[:-1]
        if day.endswith(","):
            day = day[:-1]
        if str(month).isdecimal() and not str(day).isdecimal():
            # swap out month and day if necessary
            month, day = day, month
        if len(day) == 4:
            day, year = year, day
        if month in MONTH_REPLACEMENTS.keys():
            month = MONTH_REPLACEMENTS[month]

        main_page = page.toggleTalkPage()
        search_entries = [
            f"'''[[{main_page.title().lower()}",
            f"[[{main_page.title().lower()}|'''",
        ]

        if main_page.exists():
            for revision in main_page.revisions():
                result = MOVED_REGEX.match(revision.comment)
                if result is not None:
                    old_name = result.group(1)
                    old_page = self.get_mediawiki_api().get_page(old_name)
                    search_entries.append(f"'''[[{old_page.title().lower()}")
                    search_entries.append(f"[[{old_page.title().lower()}|'''")

            for incoming_redirect in main_page.backlinks(
                filter_redirects=True, follow_redirects=False, namespaces=[0]
            ):
                search_entries.append(f"'''[[{incoming_redirect.title().lower()}")
                search_entries.append(f"[[{incoming_redirect.title().lower()}|'''")

        archive_text = self.get_archive_page(year, month)
        if archive_text == "":
            LOGGER.warning(
                "Could not load archive page (%s, %s) for %s", year, month, page
            )
            return False

        for row in str(archive_text).split("\n"):
            row_to_search = row.lower()
            for regex in NAME_REPLACEMENTS:
                row_to_search = regex.sub(NAME_REPLACEMENTS[regex], row_to_search)
            for search_entry in search_entries:
                if search_entry in row_to_search:
                    text = row[1:]  # remove * from beginning
                    # you could check dates here, if wanted - please don't for now, see BRFA for more details
                    return text
        return False

    def process_page(self, page: Page):
        page_text = page.get(force=True)
        parsed = mwparserfromhell.parse(page_text)

        save = False

        for template in parsed.filter_templates():
            if (
                (template.name.matches("Dyktalk") or template.name.matches("DYK talk"))
                and (
                    not template.has("entry")
                    or len(template.get("entry").value.strip()) == 0
                )
                and (template.has(1) and template.has(2))
            ):
                year = template.get(2).value.strip()
                day, month = template.get(1).value.strip().split(" ")
                entry = self.get_entry_for_page(year, month, day, page)

                if entry:
                    LOGGER.info("Adding entry %s to {{DYK talk}} on %s", entry, page)
                    template.add("entry", entry)
                    save = True
            elif template.name.matches("ArticleHistory") or template.name.matches(
                "Article history"
            ):
                param_date = None
                param_entry = None
                for p_date, p_entry in ARTICLE_HISTORY_PARAMS.items():
                    if not template.has(p_date):
                        continue
                    if (
                        template.has(p_entry)
                        and len(template.get(p_entry).value.strip()) > 0
                    ):
                        continue

                    param_date, param_entry = p_date, p_entry

                if not param_date:
                    LOGGER.info(
                        "Skipping {{ArticleHistory}} on page %s, no missing entries found",
                        page,
                    )
                    continue

                date = template.get(param_date).value.strip()

                if " " in date:
                    # monthName YYYY
                    if date.count(" ") == 1:
                        date = "1 " + date
                    day, month, year = date.split(" ")[:3]
                elif "-" in date:
                    year, month, day = date.split("-")[:3]
                    month = datetime.date(1900, int(month), 1).strftime("%B")
                else:
                    LOGGER.info(
                        "Skipping {{ArticleHistory|%s=}} on page %s, can't parse date %s",
                        param_date,
                        page,
                        date,
                    )
                    continue

                entry = self.get_entry_for_page(year, month, day, page)

                if entry:
                    LOGGER.info(
                        "Adding entry %s to {{ArticleHistory|%s=}} on %s",
                        entry,
                        param_date,
                        page,
                    )
                    template.add(param_entry, entry, before=param_date)
                    save = True

        if save:
            new_text = str(parsed)
            if new_text != page.text and (not self.is_manual_run or confirm_edit()):
                self.get_mediawiki_api().get_site().login()
                page.text = str(parsed)

                page.save(
                    self.get_task_configuration("missing_blurb_edit_summary"),
                    botflag=self.should_use_bot_flag(),
                )
                return True
        return False

    def run(self):
        self.merge_task_configuration(
            missing_blurb_enable=True,
            missing_blurb_edit_summary="[[WP:Bots/Requests for approval/MajavahBot 4|Bot]]: Fill missing DYK blurb",
        )

        if self.get_task_configuration("missing_blurb_enable") is not True:
            LOGGER.error("Disabled in configuration")
            return

        api = self.get_mediawiki_api()
        site = api.get_site()

        replicadb = ReplicaDatabase(site.dbName())

        replag = replicadb.get_replag()
        if replag > 10:
            LOGGER.error("Replag is over 10 seconds, not processing! (%s)", replag)
            return

        results = replicadb.get_all(QUERY)
        LOGGER.info("-- Got %s pages", len(results))
        for page_from_db in results:
            page_id = page_from_db["page_id"]
            page_name = page_from_db["page_title"].decode("utf-8")

            page = api.get_page("Talk:" + page_name)
            assert page.pageid == page_id

            self.process_page(page)


task_registry.add_task(DykEntryTalkTask(6, "DYK entry filler", "en", "wikipedia"))
