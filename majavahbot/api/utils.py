import datetime
import re
import subprocess
import time

import dateparser

multiline_reply_regex = re.compile("\n+([^\n]+~~~~)")
comment_regex = re.compile(r"(^|\n) *//.*")


def remove_comments(content: str) -> str:
    return comment_regex.sub("", content)


def remove_empty_lines_before_replies(text: str) -> str:
    return multiline_reply_regex.sub("\n\\1", text)


def get_revision() -> str:
    try:
        output = (
            subprocess.check_output(
                ["git", "describe", "--always"], stderr=subprocess.STDOUT
            )
            .strip()
            .decode()
        )
        assert "fatal" not in output
        return output
    except Exception:
        # if somehow git version retrieving command failed, just return
        return ""


class Delay:
    def __init__(self, seconds: float) -> None:
        self.seconds = seconds
        self.started = time.time()

    def get_remaining(self) -> float:
        return self.seconds - (time.time() - self.started)

    def wait(self) -> None:
        delay = self.get_remaining()
        if delay > 0:
            time.sleep(delay)


def create_delay(seconds: float) -> Delay:
    return Delay(seconds)


def was_enough_time_ago(time_text: str, seconds: int) -> bool:
    parsed_time = dateparser.parse(time_text)
    if not parsed_time:
        return False

    diff = datetime.datetime.now(tz=datetime.timezone.utc) - parsed_time
    return diff.total_seconds() > seconds
