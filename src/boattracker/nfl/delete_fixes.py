"""Delete noforeignland fixes by fixId.

There is no documented API for this, but the app's own call is straightforward:

    DELETE https://www.noforeignland.com/api/v1/boat/fix?fixId=<fixId>
    authorization: <JWT>

Auth is **entirely** the `authorization` header — the only cookies the app sends are
Google Analytics, so they can be omitted. The JWT payload is
`{"nonce": N, "timestamp": <ms>, "sub": "<userId>"}`, so it is presumably short-lived;
capture a fresh one when a run starts returning 401/403.

To capture one: open the journey page in the browser, delete any single fix with the
Network tab recording, and copy that request as cURL. The token is the `authorization`
header. (Deleting one fix by hand is the cheapest way to get a token, and it doubles as a
check that the endpoint has not changed.)

Cloudflare does not block this from curl, so no browser automation is needed.

## Ordering matters

The importer merges a new fix into an existing one within a few metres, silently. Several
Raymarine segments end at the exact position of an older aggregate fix, so uploading a
replacement *before* deleting the aggregate is a no-op — two of the nine March legs were
lost that way. Always:

  1. measure coverage and decide what to delete (`audit_duplicates.py`), against the
     precedence rule in `../SOURCES.md` — plotter for position, tracker for time
  2. **export the doomed fixes to local GPX** with `reimport_journey.py`, into
     `../nfl-retired/`, and verify the files before going further
  3. harvest any timestamps worth keeping from the fixes about to be deleted
  4. delete
  5. upload the replacements
  6. verify against the read-only journey endpoint

Step 2 is the owner's rule of 2026-08-12: **data comes off the site, it is not thrown
away.** A snapshot preserves the geometry but is not something you can put back; the GPX
is. It matters most for `NFL App` and hand-routed lines, whose points exist nowhere else.

Step 2 is easy to skip and hard to undo. An aggregate's own end timestamp is often the
best evidence for when a leg *arrived*, precisely because it came from a different source;
five of the March legs had their arrival times corrected this way, one by seven hours.

Snapshots live in `../nfl-snapshots/`. Take one before any deletion run — the API has no
undo, and a deleted fix can only be reconstructed by re-uploading its GPX, which is exactly
why step 2 above writes that GPX out first. Retired lines live in `../nfl-retired/`.
"""
import argparse
import subprocess
import sys
import time

from boattracker import config, files
from boattracker.nfl import nfl_auth

URL = config.FIX_URL + '?fixId={fid}'
UA = nfl_auth.UA  ## one browser identity for every caller, kept where the token is

def delete(fid, token, timeout=30):
    r = subprocess.run(
        ['curl', '-s', '-m', str(timeout), '-o', '/dev/null', '-w', '%{http_code}',
         '-X', 'DELETE', URL.format(fid=fid),
         '-H', 'accept: application/json, text/plain, */*',
         '-H', f'authorization: {token}',
         '-H', 'origin: https://www.noforeignland.com',
         '-H', f'referer: {config.REFERER}',
         '-H', 'sec-fetch-dest: empty', '-H', 'sec-fetch-mode: cors',
         '-H', 'sec-fetch-site: same-origin', '-A', UA],
        capture_output=True, text=True)
    return r.stdout.strip()

def main():
    ap = argparse.ArgumentParser(description=__doc__)
    ap.add_argument('--token-file', required=True,
                    help='file holding the authorization JWT, one line')
    ap.add_argument('--ids', required=True,
                    help='JSON list of [fixId, description] pairs, or a comma-separated '
                         'list of fixIds')
    ap.add_argument('--dry-run', action='store_true')
    a = ap.parse_args()
    token = files.read_stripped(a.token_file)
    try:
        items = files.read_json(a.ids) if a.ids.endswith('.json') \
            else [[x.strip(), ''] for x in a.ids.split(',')]
    except FileNotFoundError:
        items = [[x.strip(), ''] for x in a.ids.split(',')]
    print(f'{len(items)} fixes to delete')
    ok = bad = 0
    for it in items:
        fid, desc = (it if isinstance(it, list) else (it, ''))[:2]
        if a.dry_run:
            print(f'   would delete {fid}  {desc}')
            continue
        code = delete(fid, token)
        # a connection failure reports 000 and is worth one retry; a 4xx is not
        if code == '000':
            time.sleep(2)
            code = delete(fid, token)
        print(f'   HTTP {code}  {fid}  {desc}')
        if code == '200':
            ok += 1
        else:
            bad += 1
            if code in ('401', '403'):
                print('   token rejected — capture a fresh one and re-run the remainder',
                      file=sys.stderr)
                break
        time.sleep(1)
    if not a.dry_run:
        print(f'\n{ok} deleted, {bad} failed')

if __name__ == '__main__':
    main()
