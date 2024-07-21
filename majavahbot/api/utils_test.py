from majavahbot.api.utils import remove_comments


def test_remove_comments() -> None:
    assert (
        remove_comments(
            """// foo: bar
bar
baz // baz
// baz
foo
    // baz
wee
"""
        )
        == """
bar
baz // baz
foo
wee
"""
    )
