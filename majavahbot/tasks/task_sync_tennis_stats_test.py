import pytest

from majavahbot.tasks.task_sync_tennis_stats import remap_country

OVERRIDES = {
    "Foo Bar": {
        "article": "Foo Bar (that Tennis player)",
    },
    "Foo Baz": {
        "country": "NO",
    },
}


@pytest.mark.parametrize(
    "country, expected",
    [
        [None, ""],
        ["", ""],
        ["YES", "YES"],
        [" (YES)", "YES"],
    ],
)
def test_remap_country_simple(country: str, expected: str):
    assert remap_country("Does Not Matter", country, {}) == expected


def test_remap_country_override():
    assert remap_country("Baz, Foo", " (YES)", OVERRIDES) == "NO"
