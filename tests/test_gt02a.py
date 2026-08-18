"""Blob-level tests for the TK103 parser.

`test_parser.py` exercises the parser through a 15-hour recording, which covers the happy
path well and the error paths not at all. These are the error paths, and they matter now
that the 2021 archive (322 000 fixes, `gpstracker-archive/`) is being parsed in batch: every
`pdb.set_trace()` on a parse error is a batch run that stops dead waiting on a terminal.
"""

import pytest

from boattracker.tracker.gt02a import BlobError, parse_blob

## A real blob, moving: 7.4 km/h on heading 123.45 at 23:59:52 on 2021-07-05.
GOOD = b'028042516052BR00210705A5856.4693N01108.6720E007.4235952123.4501000000L00000000'


def test_a_moving_fix_is_parsed():
    point = parse_blob(GOOD)
    assert point.ts == '2021-07-05T235952'
    assert point.lat == pytest.approx(58 + 56.4693 / 60)
    assert point.long == pytest.approx(11 + 8.6720 / 60)
    assert point.heading == 123.45


def test_the_speed_keeps_its_decimal():
    ## The field is five characters, `SSS.S` km/h. Reading four of them silently truncates
    ## 7.4 km/h to 7.0 - a 5% error on every fix, invisible because it still parses.
    assert parse_blob(GOOD).speed == pytest.approx(7.4 / 3.6)


@pytest.mark.parametrize('blob, why', [
    (GOOD.replace(b'N01108', b'X01108'), 'hemisphere is neither N nor S'),
    (GOOD.replace(b'5856.4693', b'58zz.4693'), 'latitude is not a number'),
    (GOOD.replace(b'01108.6720E', b'01108.6720X'), 'hemisphere is neither E nor W'),
    (GOOD.replace(b'E007.4235952', b'Ezzz.zzzzzz'), 'speed and time are not numbers'),
])
def test_a_malformed_blob_raises_rather_than_stopping_the_run(blob, why):
    with pytest.raises(BlobError):
        parse_blob(blob)
