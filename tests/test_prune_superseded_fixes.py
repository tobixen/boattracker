"""Tests for the one rule in the pruner that is not about coverage.

A hand-placed fix at a chapter boundary looks exactly like a superseded one — the boat was
lying still where track from the arrival or departure passes within metres — and it is the
only thing making its chapter render in the right place. On 2026-08-11 the pruner's list
held four of the eight boundary fixes added on 2026-08-03, so this is a bug that already
happened, not a hypothetical.
"""

from boattracker.nfl import prune_superseded_fixes as P

HOUR = 3600.0


def chapters(*starts_ms):
    """Stored chapters, as the journey endpoint returns them."""
    return {'chapters': [{'id': 4200 + i, 'boatId': 1234567890123456,
                          'name': f'chapter {i}', 'start': ms}
                         for i, ms in enumerate(starts_ms)]}


def test_stored_chapter_starts_are_read():
    assert P.chapter_starts(chapters(1749074400000, 1753221600000)) == [
        1749074400.0, 1753221600.0]


def test_synthetic_year_chapters_do_not_protect_anything():
    ## A boat with no stored chapters reads back generated per-year ones carrying id 0 and
    ## boatId 0 (../NFL-CHAPTERS.md). Counted, they would protect every 1 January - and
    ## 1 January is exactly when a boat is lying still with track from the day either side.
    doc = {'chapters': [{'id': 0, 'boatId': 0, 'name': '2021', 'start': 1609459200000}]}
    assert P.chapter_starts(doc) == []


def test_no_chapters_at_all_is_not_an_error():
    assert P.chapter_starts({}) == []


def test_a_fix_a_minute_after_a_chapter_start_is_protected():
    ## The convention `add_fixes.py` was run with on 2026-08-03: local midnight plus one
    ## minute, so the fix falls inside the window whichever way the comparison is written.
    starts = [1749074400.0]
    assert P.at_a_chapter_boundary(1749074460.0, starts, 2 * HOUR)


def test_a_fix_an_hour_before_a_chapter_start_is_protected():
    ## The La Rochelle refinement uses a *pair*, one either side of the boundary, so the
    ## window has to reach backwards as well - see ../NFL-CHAPTERS.md.
    starts = [1749074400.0]
    assert P.at_a_chapter_boundary(1749074400.0 - HOUR, starts, 2 * HOUR)


def test_a_fix_far_from_any_boundary_is_not_protected():
    starts = [1749074400.0]
    assert not P.at_a_chapter_boundary(1749074400.0 + 9 * HOUR, starts, 2 * HOUR)


def test_protection_does_not_extend_to_the_next_chapter():
    ## Two boundaries a month apart must protect two instants, not the span between them.
    starts = [1749074400.0, 1751752800.0]
    assert not P.at_a_chapter_boundary((starts[0] + starts[1]) / 2, starts, 2 * HOUR)


## ------------------------------------------------------ the owner's precedence rule
##
## `../SOURCES.md`, 2026-08-12. The three hand-placed sources are not equivalent and the
## tool used to treat them as one bucket:
##
##   `Check in`  never has an accurate position, and its timestamp is not trustworthy either
##   `Manual`    usually exact in both, but should still yield to real track
##   `NFL App`   reliable enough, but not reliably started and stopped - it under-covers a
##               passage and sometimes keeps recording ashore
##
## The consequence for the coverage test is specific: for a `Check in` the *distance* to
## real track is not evidence of anything, because the position it is measured from is not
## evidence. What matters is only whether real track exists around that time.


def test_a_checkin_is_judged_on_a_far_wider_tolerance():
    assert P.tolerance_for('Check in', 300.0) > 300.0


def test_manual_and_app_fixes_keep_the_ordinary_tolerance():
    ## A `Manual` position is usually exact, so distance from track means what it says.
    assert P.tolerance_for('Manual', 300.0) == 300.0
    assert P.tolerance_for('NFL App', 300.0) == 300.0


def test_raising_the_base_tolerance_still_raises_the_checkin_one():
    ## `--tolerance` must not be silently capped by the check-in default.
    assert P.tolerance_for('Check in', 9000.0) >= 9000.0


## ------------------------------------------------ a fix that is the only record of its day
##
## The tool's stated rule is that a hand-placed point which is still "the only record of its
## day" is kept, but it only ever checked whether *track* passed nearby. Track belongs to a
## different fix with its own timestamp, and the coverage window reaches 36 hours, so a fix
## can be covered and still be the last thing standing on its date. On 2026-08-12 seven of
## the ten `Manual` candidates were exactly that — the 2022 departure fixes, added on purpose
## to give that season its missing voyage days. Deleting them would have removed seven days
## from the journey while "losing no geometry".


def test_the_only_fix_of_its_day_is_kept():
    days = {'2022-07-14': 1}
    assert P.last_of_its_day('2022-07-14', days)


def test_a_day_with_other_fixes_is_not_protected():
    days = {'2022-07-21': 2}
    assert not P.last_of_its_day('2022-07-21', days)


def test_a_day_that_is_not_in_the_census_is_treated_as_bare():
    ## Defensive: an unknown day means the census did not see it, and guessing "there must be
    ## others" is the guess that loses data.
    assert P.last_of_its_day('2022-07-14', {})


def test_the_census_counts_every_fix_not_just_hand_placed_ones():
    ## What keeps a day on the journey is any fix at all, so a hand-placed point sharing its
    ## day with a plotter leg is not protected by this rule.
    doc = {'geojson': {'features': [
        {'geometry': {'type': 'Point'},
         'properties': {'fixId': 1, 'timeMs': 1657800000000, 'source': 'Manual'}},
        {'geometry': {'type': 'Point'},
         'properties': {'fixId': 2, 'timeMs': 1657801000000, 'source': 'Raymarine GPX Export'}},
    ]}}
    census = P.fixes_per_day(doc)
    assert sum(census.values()) == 2 and len(census) == 1
