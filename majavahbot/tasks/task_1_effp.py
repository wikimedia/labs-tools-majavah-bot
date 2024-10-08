import datetime
import logging
from re import compile, search, sub

from dateutil import parser
from pywikibot.exceptions import InvalidTitleError

from majavahbot.api import MediawikiApi
from majavahbot.api.manual_run import confirm_edit
from majavahbot.tasks import Task, task_registry

LOGGER = logging.getLogger(__name__)


class EffpTask(Task):
    """
    Task 1 patrols the Edit Filter false positive report page.

    Subtasks are:
     a) If page name is missing, fill it in if possible, notify otherwise
     b) If page name is wrong in a very obvious way (eg. lowercase), correct it
     c) If filter is private, add a notification about that
     d) If user is blocked, add a notification about that
     e) Archive
    """

    def __init__(self, task_id: str, name: str, site: str, family: str) -> None:
        super().__init__(task_id, name, site, family)
        self.is_continuous = True
        self.supports_manual_run = True
        self.stream = None
        self.register_task_configuration("User:MajavahBot/EFFP Helper Configuration")

    def locate_page_name(self, section):
        """Used to locate page name from a section"""
        results = search(self.get_task_configuration("page_title_regex"), section)

        if results is None:
            return None

        page_name = results.group(1)

        if page_name == "Page not specified":
            return None
        return page_name

    def is_closed(self, section):
        return any(
            string.lower() in section.lower()
            for string in self.get_task_configuration("section_closed_strings")
        )

    def process_new_report(self, section: str, user_name: str, api: MediawikiApi):
        """Used to process a new section added to the page"""
        page_title = self.locate_page_name(section)

        if not section.endswith("\n"):
            section += "\n"

        new_section = section
        edit_summary = []

        matching_hits = api.get_last_filter_hits(user_name)

        # get a single log entry for most operations
        last_hit = None if len(matching_hits) == 0 else matching_hits[0]

        # If filter was triggered more than 3 hours ago, assume it is not the one being reported
        if last_hit is not None:
            last_hit_timestamp = last_hit["timestamp"]
            last_hit_datetime = parser.parse(last_hit_timestamp)
            if (
                datetime.datetime.now(tz=datetime.timezone.utc) - last_hit_datetime
            ).total_seconds() > 3600 * 3:
                last_hit = None

        if last_hit is None:
            if page_title is None:
                new_section += ":{{EFFP|nofilterstriggered|bot=1}} ~~~~\n"
                edit_summary.append("Notify that no filters were triggered (task 1a)")
        else:
            last_hit_page_title = last_hit["title"]

            # subtask a: if page title is missing, add it
            # subtask b: correct very obvious spelling mistakes in page titles (currently only case)
            page_title_missing = page_title is None or len(page_title) == 0
            page_title_obviously_wrong = False

            if last_hit_page_title != page_title and not page_title_missing:
                if last_hit_page_title is not None and page_title is not None:
                    if api.compare_page_titles(last_hit_page_title, page_title):
                        page_title_obviously_wrong = True

                for pattern in self.get_task_configuration("page_title_wrong_formats"):
                    wrong_spelling = search(pattern, page_title)
                    if wrong_spelling is not None:
                        if api.compare_page_titles(
                            wrong_spelling.group(1), last_hit_page_title
                        ):
                            page_title_obviously_wrong = True

            if page_title_missing or page_title_obviously_wrong:
                last_hit_filter_log = self.get_task_configuration(
                    "abuse_log_format"
                ) % api.get_page(last_hit_page_title).title(as_url=True)

                section_pre_subst = new_section
                new_section = sub(
                    self.get_task_configuration("page_title_regex"),
                    ";Page you were editing\n: [["
                    + last_hit_page_title
                    + ']] (<span class="plainlinks">['
                    + last_hit_filter_log
                    + " filter log]</span>)\n",
                    new_section,
                )

                if section_pre_subst == new_section:
                    # Unable to replace, probably malformed requests
                    pass
                elif page_title_missing:
                    new_section += ":{{EFFP|pagenameadded|bot=1}} ~~~~\n"
                    edit_summary.append("Add affected page name (task 1a)")
                elif page_title_obviously_wrong:
                    new_section += ":{{EFFP|pagenamefixed|bot=1}} ~~~~\n"
                    edit_summary.append("Fix affected page name (task 1b)")

            # subtask c: notify if filter is private
            private = 0
            for hit in matching_hits:
                # filter id seems to be empty when a filter is private
                if hit["filter_id"] == "" and hit["result"] in ("disallow", "warn"):
                    private = hit["id"]
                    break

            if private != 0:
                new_section += ":{{EFFP|p|bot=1}}<!-- " + str(private) + " --> ~~~~\n"
                edit_summary.append("Add private filter notice (task 1c)")

        if new_section != section:
            return new_section, edit_summary
        return section, []

    def process_existing_report(self, section: str, user_name: str, api: MediawikiApi):
        """Used to process an existing section"""
        if not section.endswith("\n"):
            section += "\n"

        new_section = section
        edit_summary = []

        try:
            user = api.get_user(user_name)
        except InvalidTitleError:
            if "{{EFFP|" not in section and "<" not in user_name:
                new_section += (
                    ":{{EFFP|note|bot=1}} Failed to retrieve details about user <code><nowiki>%s</nowiki></code>! ~~~~\n"
                    % user_name
                )
                edit_summary.append("Failed to load user details")
                return new_section, edit_summary

            return section, []

        # subtask d: notify if blocked
        if user.isBlocked():
            blocked_by = user.getprops()["blockedby"]
            new_section += ":{{EFFP|b|%s|%s|bot=1}} ~~~~\n" % (
                user.username,
                blocked_by,
            )
            edit_summary.append("Notify if user is blocked. (task 1d)")

        if new_section != section:
            return new_section, edit_summary
        return section, []

    def get_sections(self, page: str) -> tuple:
        """Parses a page and returns all sections in it"""
        section_header_pattern = compile(self.get_task_configuration("section_header"))
        sections = []

        # add a \n to beginning, since the regex needs one
        page = "\n" + page
        matches = list(section_header_pattern.finditer(page))

        if len(matches) == 0:
            return page, []

        for i in range(len(matches)):
            match = matches[i]
            end = matches[i + 1].start() - 1 if i < (len(matches) - 1) else len(page)
            sections.append((match.group(1).strip(), page[match.start() : end] + "\n"))

        header = page[: matches[0].start() - 1]
        # cut out the first line ending added when passing the page text to the regex
        header = header[1:]

        return header + "\n", sections

    def create_edit_summary(
        self, archived_sections: list, given_summaries: dict
    ) -> str:
        processed_sections = list(given_summaries.keys())
        process_reasons = {}

        for section_name, actions in given_summaries.items():
            for action in actions:
                if action not in process_reasons:
                    process_reasons[action] = [section_name]
                else:
                    process_reasons[action].append(section_name)

        summary = []

        if len(processed_sections) == 1:
            if len(process_reasons.keys()) <= 3:
                summary.append(
                    "Processed a section: " + (", ".join(process_reasons.keys()))
                )
            else:
                summary.append("Processed a section")
        elif len(processed_sections) > 1:
            if len(process_reasons.keys()) == 1:
                reason = list(process_reasons.keys())[0]
                summary.append(
                    "Process "
                    + str(len(processed_sections))
                    + " sections ("
                    + reason
                    + ")"
                )
            else:
                summary.append("Process " + str(len(processed_sections)) + " sections")

        if len(archived_sections) > 1:
            summary.append("Archive " + str(len(archived_sections)) + " sections")
        elif len(archived_sections) > 0:
            summary.append("Archive one section")

        return "Bot clerking: " + ", ".join(summary)

    def process_page(self, page_name: str, api: MediawikiApi):
        LOGGER.info("Processing page %s", page_name)

        """Processes the EFFPR page"""
        page = api.get_page(page_name)
        page.get(force=True)

        rev_iterator = page.revisions(content=True, total=2)
        current_text = next(rev_iterator)["text"]
        old_text = next(rev_iterator)["text"]

        old_preface, old_sections = self.get_sections(old_text)
        current_preface, current_sections = self.get_sections(current_text)

        if len(old_sections) > len(current_sections):
            # assuming something was just archived or un-done, not doing anything
            LOGGER.warning(
                "Assuming something was just archived or un-done, not doing anything"
            )
            return

        save = False
        summaries = {}

        archived_sections = []
        archive_section_titles = []
        section_texts = []

        for i in range(len(current_sections)):
            section_user = current_sections[i][0]
            section_text = current_sections[i][1]

            if not self.is_closed(section_text):
                LOGGER.info("Processing section by %s", section_user)

                new_text = section_text
                new_summaries = []
                if i >= len(old_sections):
                    new_text, new_summaries = self.process_new_report(
                        new_text, section_user, api
                    )
                new_text, existing_summaries = self.process_existing_report(
                    new_text, section_user, api
                )

                if self.should_archive(new_text, api):
                    archived_sections.append(new_text)
                    archive_section_titles.append(section_user)
                    LOGGER.info("Will archive open section %s", section_user)
                    save = True
                elif new_text != section_text:
                    section_texts.append(new_text)
                    LOGGER.info("Modified open section %s", section_user)
                    summaries[section_user] = new_summaries + existing_summaries
                    save = True
                else:
                    LOGGER.info("Didn't modify open section %s", section_user)
                    section_texts.append(new_text)
            elif self.should_archive(section_text, api):
                LOGGER.info("Will archive closed section %s", section_user)
                archived_sections.append(section_text)
                archive_section_titles.append(section_user)
                save = True
            else:
                section_texts.append(section_text)

        if save:
            if self.is_manual_run and (not confirm_edit()):
                LOGGER.warning("Not saving!")
                return

            if len(archived_sections) > 0:
                LOGGER.info(
                    "Saving archived sections, len = %s", len(archived_sections)
                )
                self.add_to_archive_page(
                    self.get_task_configuration("rolling_archive_page_name"),
                    self.get_task_configuration("rolling_archive_max_sections"),
                    archived_sections,
                    api,
                )

            write_page_name = self.get_task_configuration("page_to_write_reports")
            if isinstance(write_page_name, str) and write_page_name != "":
                LOGGER.warning(
                    "Writing to page %s instead of reports page", write_page_name
                )
                page = api.get_page(write_page_name)

            summary = self.create_edit_summary(archive_section_titles, summaries)
            LOGGER.info("Saving, edit summary = %s", summary)
            new_text = current_preface + "".join(section_texts)
            page.text = new_text
            page.save(summary, minor=False, botflag=self.should_use_bot_flag())
        else:
            LOGGER.warning("Not saving.")

    def add_to_archive_page(
        self,
        archive_page_name: str,
        max_threads: int,
        new_sections: list,
        api: MediawikiApi,
    ):
        archive_page = api.get_page(archive_page_name)
        header, sections = self.get_sections(archive_page.text)

        for section in new_sections:
            sections.append(("", section))

        if len(sections) > max_threads:
            sections = sections[0 - max_threads :]

        section_texts = []
        for section in sections:
            section_texts.append(section[1])

        summary = "Add %s archived sections (task 1e)" % len(new_sections)
        archive_page.text = header + "".join(section_texts)
        archive_page.save(summary, minor=False, botflag=self.should_use_bot_flag())

    def run(self):
        api = self.get_mediawiki_api()

        LOGGER.info("Processing page once")
        self.process_page(self.get_task_configuration("reports_page"), api)

        if self.is_manual_run:
            return

        # if change streams are available for that page, use it; otherwise just process it once
        try:
            self.stream = api.get_page_change_stream(
                self.get_task_configuration("reports_page")
            )
        except:
            LOGGER.error("Can't subscribe to EFFPR report page")
            return

        LOGGER.info("Now listening for EFFPR edits")
        for change in self.stream:
            if (
                "!nobot!" in change["comment"]
                or "Reverted " in change["comment"]
                or "Reverting " in change["comment"]
                or "Undid revision " in change["comment"]
            ):
                continue
            self.process_page(self.get_task_configuration("reports_page"), api)

        LOGGER.error("EventStream dried")  # auto restart?

    def task_configuration_reloaded(self, old, new):
        if "reports_page" in old and old["reports_page"] != new["reports_page"]:
            self.stream = []  # dry stream

    def should_archive(self, text: str, api: MediawikiApi) -> bool:
        # if there is a signature in text, do not archive as it was modified in this round.
        if "~~~~" in text:
            return False

        last_reply = api.get_last_reply(text)

        # if no replies found, return false instead of processing (and crashing)
        if last_reply is None:
            return False

        no_resolution_time = self.get_task_configuration("no_resolution_archive_time")
        lowertext = text.lower()

        keep_texts = self.get_task_configuration("archive_blockers")
        for value in keep_texts:
            if value.lower() in lowertext:
                return False

        delay_found = False
        shortest_found_delay = 2419200  # 4 weeks, should be long enough
        delays = self.get_task_configuration("archive_delays")

        for key, value in delays.items():
            if key.lower() in lowertext:
                delay_found = True
                shortest_found_delay = (
                    value if value < shortest_found_delay else shortest_found_delay
                )

        seconds_to_wait = shortest_found_delay if delay_found else no_resolution_time
        last_reply_seconds = (
            datetime.datetime.now(tz=datetime.timezone.utc) - last_reply
        ).total_seconds()
        LOGGER.info(
            "Archive seconds_to_wait %s, last reply was %s, archive: %s",
            seconds_to_wait,
            last_reply_seconds,
            last_reply_seconds > seconds_to_wait,
        )
        return last_reply_seconds > seconds_to_wait


task_registry.add_task(EffpTask("1", "EFFP helper", "en", "wikipedia"))
