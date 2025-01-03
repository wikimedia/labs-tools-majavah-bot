from datetime import datetime

import mwparserfromhell
import pytest

from majavahbot.tasks.task_5_steward_request_bot import (
    add_archived_sections,
    create_archive_page_name,
    is_closed,
)


def test_add_archived_sections() -> None:
    assert (
        add_archived_sections(
            """== First ==
=== Foo ===
foo

=== Bar ===
Bar.

== Second ==
=== Baz ===
Baz.
""",
            {
                "First": [
                    """=== Another ===
Another
"""
                ],
                "More": [
                    """=== One ===
one.
""",
                    """=== Example ===
example
""",
                ],
            },
        )
        == """== First ==
=== Foo ===
foo

=== Bar ===
Bar.


=== Another ===
Another

== Second ==
=== Baz ===
Baz.

== More ==
=== One ===
one.

=== Example ===
example

"""
    )


@pytest.mark.parametrize(
    "text, custom_templates, closed",
    [
        ["nope", [], False],
        ["{{not status}}", [], False],
        ["{{status}}", [], False],
        ["{{status|}}", [], False],
        ["{{status|onhold}}", [], False],
        ["{{status|ONHOLD}}", [], False],
        ["{{status|closed}}", [], True],
        ["{{srgp|status=done}}", [], False],
        ["{{srgp|status=done}}", ["foo"], False],
        ["{{srgp}}", ["srgp"], False],
        ["{{srgp|status=in progress}}", ["srgp"], False],
        ["{{srgp|status=}}", ["srgp"], False],
        ["{{srgp|status=on hold<!--don't change this line-->}}", ["srgp"], False],
        ["{{srgp|status=done}}", ["srgp"], True],
        ["{{status|closed}}", ["srgp"], False],
    ],
)
def test_is_closed(text: str, custom_templates: list[str], closed: bool) -> None:
    assert is_closed(mwparserfromhell.parse(text), custom_templates) == closed


def test_create_archive_page_name():
    assert (
        create_archive_page_name(
            template="{page}/{year}-{month}-{week}",
            base="b@se",
            time=datetime(year=2024, month=12, day=30),
        )
        == "b@se/2024-12-53"
    )
