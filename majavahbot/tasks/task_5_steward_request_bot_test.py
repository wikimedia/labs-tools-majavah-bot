import mwparserfromhell
import pytest as pytest

from majavahbot.tasks.task_5_steward_request_bot import add_archived_sections, is_closed


def test_add_archived_sections():
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
    "text, closed",
    [
        ["nope", False],
        ["{{not status}}", False],
        ["{{status}}", False],
        ["{{status|}}", False],
        ["{{status|onhold}}", False],
        ["{{status|ONHOLD}}", False],
        ["{{status|closed}}", True],
    ],
)
def test_is_closed(text, closed):
    assert is_closed(mwparserfromhell.parse(text)) == closed
