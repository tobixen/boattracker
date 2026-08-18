"""Tests for the hand-built chapter adder."""

from boattracker.nfl import add_chapters

## The plan files are one boat's record and left this repository on 2026-08-18. A test
## here that read them could never run — `conftest.py` pins the diary directory to a
## nonexistent path so the suite is hermetic, so it skipped on every machine including the
## author's, which is dead weight rather than a data check. The invariant it was guarding
## is below, tested against synthetic data; checking a particular plan file belongs with
## that plan file, in the journey record.


def test_two_plan_entries_at_one_instant_are_not_caught_by_the_code(tmp_path):
    """Which is why the plan itself is checked above, and why it is checked at all.

    Nothing in `build()` rejects a duplicate start - it happily emits two chapters at the
    same instant, and the collapse happens later and server-side, where it is much harder
    to see. This pins that the hazard is real rather than hypothetical.
    """
    rows = [("First", "2021-06-01", None), ("Second", "2021-06-01", None)]
    built = add_chapters.build(rows)
    assert len({c["start"] for c in built}) == 1
    assert len(built) == 2


def test_when_defaults_to_oslo_and_honours_an_explicit_zone():
    # Norway and Poland are both CEST in July, so the default is right for the 2022 legs.
    assert add_chapters.when("2022-07-07", None) == add_chapters.when("2022-07-07", "Europe/Oslo")
    # Lisbon is WEST (UTC+1) in September: 22:00 local is 21:00 UTC.
    assert add_chapters.when("2022-09-24T22:00", "Europe/Lisbon") == 1664053200000


def test_entries_get_the_period_prefix():
    rows = [("Berlenga accident and repairs", "2022-09-24T22:00", "Europe/Lisbon")]
    built = add_chapters.build(rows)
    assert built[0]["name"] == "2022-09: Berlenga accident and repairs"
    assert built[0]["id"] == 0


def test_build_gives_the_condensed_chapter_the_earliest_start():
    # Condensing keeps the earliest start, which collides with the chapter already stored
    # there — that entry has to be renamed rather than skipped as "already present".
    # The name is the 2026-08-03 condensation, split again on 2026-08-05 and kept here
    # because the rename-on-collision path it exercises is the same either way.
    rows = [("Travels between Oslo and Gothenburg - alone, with my daughter and with the family",
             "2021-05-13", None)]
    built = add_chapters.build(rows)
    assert built[0]["start"] == add_chapters.when("2021-05-13", None)
    assert built[0]["name"].startswith("2021-05: Travels between Oslo and Gothenburg")


def test_prune_only_reaches_chapters_before_the_diary_cutoff():
    cutoff = 1000
    existing = [
        {"id": 1, "name": "hand-built, still wanted", "start": 100},
        {"id": 2, "name": "hand-built, dropped from the plan", "start": 200},
        {"id": 3, "name": "a diary chapter", "start": 5000},
    ]
    doomed = add_chapters.prunable(existing, desired={100}, cutoff=cutoff)
    assert [c["id"] for c in doomed] == [2]


def test_prune_never_touches_a_diary_chapter_even_if_absent_from_the_plan():
    existing = [{"id": 9, "name": "a diary chapter", "start": 9999}]
    assert add_chapters.prunable(existing, desired=set(), cutoff=1000) == []


def test_existing_chapters_are_resent_with_their_ids():
    existing = [{"id": 7, "name": "2023-06: something", "start": 100, "boatId": add_chapters.BOAT_ID}]
    rows = [("New one", "2022-07-07", None)]
    body = add_chapters.body(existing, rows)
    assert body["deleteChapterIds"] == []
    ids = [c["id"] for c in body["chapters"]]
    assert 7 in ids and 0 in ids
    assert len(body["chapters"]) == 2
