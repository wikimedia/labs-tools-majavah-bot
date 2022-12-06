import ipaddress
from datetime import datetime, timezone

import mwparserfromhell
from pywikibot.data.api import QueryGenerator

from majavahbot.api.manual_run import confirm_edit
from majavahbot.api.mediawiki import MediawikiApi
from majavahbot.api.utils import remove_empty_lines_before_replies, was_enough_time_ago
from majavahbot.config import steward_request_bot_config_page
from majavahbot.tasks import Task, task_registry


class StewardRequestTask(Task):
    def __init__(self, number, name, site, family):
        super().__init__(number, name, site, family)
        self.register_task_configuration(steward_request_bot_config_page)
        self.supports_manual_run = True

    def get_steward_who_gblocked_ip(self, api: MediawikiApi, ip_or_range):
        data = QueryGenerator(
            site=api.get_site(),
            list="globalblocks",
            bgip=ip_or_range,
        ).request.submit()["query"]["globalblocks"]
        if len(data) == 0:
            return None

        if not was_enough_time_ago(
            data[0]["timestamp"], self.get_task_configuration("mark_done_min_time")
        ):
            return None

        return data[0]["by"]

    def get_steward_who_locked_account(self, api: MediawikiApi, account_name):
        data = QueryGenerator(
            site=api.get_site(),
            list="logevents",
            letype="globalauth",
            letitle="User:" + account_name + "@global",
        ).request.submit()["query"]["logevents"]

        if len(data) == 0:
            return None

        entry = data[0]
        params = entry["params"]

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

        return data[0]["user"]

    def process_srp_section(self, api, section):
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
        if status.has(1):
            return len(status.get(1).value) > 0 and status.get(1).value != "onhold"

        if ("unlock" in header and "/unlock" not in header) or (
            "unblock" in header and "/unblock" not in header
        ):
            print(f"Assuming section {header} is a un(b)lock request, skipping")
            return False

        mark_done = True

        for ip in ips:
            steward = self.get_steward_who_gblocked_ip(api, ip)
            if steward is None:
                mark_done = False
            else:
                awesome_people.add(steward)

        for account in accounts:
            steward = self.get_steward_who_locked_account(api, account)
            if steward is None:
                mark_done = False
            else:
                awesome_people.add(steward)

        print(accounts, ips, awesome_people, mark_done)
        if not mark_done or len(awesome_people) == 0:
            return False

        # remove duplicates
        awesome_people = ", ".join(sorted(awesome_people))

        if mark_done:
            status.add(1, "done")
            section.append(
                ": '''Robot clerk note:''' {{done}} by " + awesome_people + ". ~~~~\n"
            )
            print("Marking as done", awesome_people, status, ips, accounts)

        return False

    def run(self):
        self.merge_task_configuration(
            run=True,
            srg_page="Steward requests/Global",
            summary="Bot clerking",
            mark_done_min_time=5 * 60,
            archive_page_format="Steward requests/Global/{year}-w{week}",
            archive_min_time=60 * 60,
        )

        if self.get_task_configuration("run") is not True:
            print("Disabled in configuration")
            return

        api = self.get_mediawiki_api()

        request_page = api.get_page(self.get_task_configuration("srg_page"))
        request_original_text = request_page.get(force=True)

        parsed = mwparserfromhell.parse(request_page.get(force=True))
        sections = parsed.get_sections(levels=[3])

        to_archive = ""

        for section in sections:
            is_complete = self.process_srp_section(api, section)

            if not is_complete:
                continue

            last_reply = api.get_last_reply(str(section))
            if last_reply is None:
                continue
            if (
                datetime.now(tz=timezone.utc) - last_reply
            ).total_seconds() <= self.get_task_configuration("archive_min_time"):
                continue

            print(f"Archiving section {section}")
            to_archive += "\n" + str(section)
            parsed.replace(section, "")

        new_text = str(parsed)
        new_text = remove_empty_lines_before_replies(new_text)

        if (
            new_text != request_original_text
            and self.should_edit()
            and (not self.is_manual_run or confirm_edit())
        ):
            api.site.login()
            request_page.text = new_text
            request_page.save(
                self.get_task_configuration("summary"),
                botflag=self.should_use_bot_flag(),
            )
            self.record_trial_edit()

            if to_archive != "":
                now = datetime.now()
                archive_page_name = self.get_task_configuration(
                    "archive_page_format"
                ).format(
                    year=now.year,
                    week=now.isocalendar().week,
                )

                archive_page = api.get_page(archive_page_name)
                if archive_page.exists():
                    archive_page.text = archive_page.get(force=True) + "\n" + to_archive
                else:
                    archive_page.text = to_archive

                archive_page.save(
                    self.get_task_configuration("summary"),
                    botflag=self.should_use_bot_flag(),
                )


task_registry.add_task(StewardRequestTask(5, "Steward request bot", "meta", "meta"))
