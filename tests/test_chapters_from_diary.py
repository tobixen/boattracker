"""Tests for the chapter builder.

The one that matters is `test_replace_never_touches_pre_diary_chapters`: the diaries only
exist in this format from 2023-06, and the earlier chapters are hand-built and not
reproducible from any file. A `--replace` that removed them would destroy work with no
source to regenerate it from.
"""

from boattracker.nfl import chapters_from_diary as c


def chap(id_, name, date):
    return {"id": id_, "boatId": c.BOAT_ID, "name": name, "start": c.start_ms(date)}


def test_chapter_name_carries_the_period():
    assert c.chapter_name("2025-07-23", "Family trip to Turkey") == "2025-07: Family trip to Turkey"
    assert c.chapter_name("2026-03-06", "Repairing the boat") == "2026-03: Repairing the boat"


def test_a_name_that_already_states_its_period_keeps_it():
    # A chapter that starts on the last days of a month but belongs to the next one:
    # 2021-06-29 .. 07-21 is a July trip. The plan says so and the date does not override it.
    assert (c.chapter_name("2021-06-29", "2021-07: To Gothenburg with my daughter")
            == "2021-07: To Gothenburg with my daughter")


def test_chapter_name_is_idempotent():
    # add_chapters compares stored names, which carry the prefix, against freshly built
    # ones. Without this a second pass would produce `2025-07: 2025-07: ...` and read as
    # a rename, retitling the chapter on every run.
    once = c.chapter_name("2025-07-23", "Family trip to Turkey")
    assert c.chapter_name("2025-07-23", once) == once


def test_a_title_merely_containing_a_date_is_still_prefixed():
    assert (c.chapter_name("2024-06-28", "The 2024-06 passage")
            == "2024-06: The 2024-06 passage")


def test_start_ms_matches_the_web_ui():
    # Values observed from chapters created by hand in the browser, one CET, one CEST.
    assert c.start_ms("2026-03-10") == 1773097200000
    assert c.start_ms("2024-08-15") == 1723672800000


def test_replace_never_touches_pre_diary_chapters():
    existing = [
        chap(1, "hand-built 2021", "2021-06-01"),
        chap(2, "hand-built 2022", "2022-03-01"),
        chap(3, "stale diary chapter", "2023-09-13"),
        chap(4, "another stale one", "2025-03-14"),
    ]
    doomed = c.replaceable(existing, cutoff=c.start_ms("2023-06-01"))
    assert [x["id"] for x in doomed] == [3, 4]


def test_replace_keeps_a_chapter_exactly_on_the_cutoff_out_of_danger():
    # A chapter starting on the cutoff day is diary territory, so it is replaceable.
    existing = [chap(9, "first diary chapter", "2023-06-01")]
    assert c.replaceable(existing, cutoff=c.start_ms("2023-06-01")) == existing


def test_nothing_is_replaceable_when_all_predate_the_diaries():
    existing = [chap(1, "2021", "2021-01-01"), chap(2, "2022", "2022-01-01")]
    assert c.replaceable(existing, cutoff=c.start_ms("2023-06-01")) == []


def desired(*pairs):
    return [{"id": 0, "name": name, "start": c.start_ms(date)} for date, name in pairs]


def test_reconcile_renames_in_place_rather_than_recreating():
    # A retitled diary heading keeps its date, so the stored chapter is updated by id.
    # Recreating it would churn ids and, mid-failure, leave the journey short a chapter.
    existing = [chap(4255, "2023-06: Tur fra Algés til Menorca", "2023-06-01")]
    matched, creates, stale = c.reconcile(existing, desired(("2023-06-01", "2023-06: From Algés to Menorca")))
    assert creates == [] and stale == []
    stored, want = matched[0]
    assert stored["id"] == 4255
    assert want["name"] == "2023-06: From Algés to Menorca"


def test_reconcile_creates_only_what_is_not_stored_at_that_instant():
    existing = [chap(1, "2023-06: kept", "2023-06-01")]
    matched, creates, stale = c.reconcile(
        existing, desired(("2023-06-01", "2023-06: kept"), ("2024-01-01", "2024-01: new")))
    assert [m[0]["id"] for m in matched] == [1]
    assert [n["name"] for n in creates] == ["2024-01: new"]
    assert stale == []


def test_reconcile_reports_a_chapter_the_diaries_no_longer_place_there():
    # A heading whose first dated day entry moved leaves the old start orphaned; it is
    # the only case that still needs a delete, and so the only case --replace guards.
    existing = [chap(3, "2023-09: moved", "2023-09-13")]
    matched, creates, stale = c.reconcile(existing, desired(("2023-09-14", "2023-09: moved")))
    assert matched == []
    assert [n["name"] for n in creates] == ["2023-09: moved"]
    assert [s["id"] for s in stale] == [3]


def test_reconcile_is_idempotent_when_nothing_changed():
    existing = [chap(1, "2023-06: same", "2023-06-01")]
    matched, creates, stale = c.reconcile(existing, desired(("2023-06-01", "2023-06: same")))
    assert creates == [] and stale == []
    assert matched[0][0]["name"] == matched[0][1]["name"]


def test_collect_reads_headings_and_their_first_dated_day(tmp_path):
    d = tmp_path / "diary-2099.md"
    d.write_text(
        "# A chapter\n\n## Monday 2099-01-02 - somewhere\n\ntext\n\n"
        "## Tuesday 2099-01-03\n\n# Another chapter\n\n## Wednesday 2099-02-04\n",
        encoding="utf-8",
    )
    rows = c.collect(str(tmp_path / "diary-*.md"))
    assert [(date, title) for date, title, _ in rows] == [
        ("2099-01-02", "A chapter"),
        ("2099-02-04", "Another chapter"),
    ]
