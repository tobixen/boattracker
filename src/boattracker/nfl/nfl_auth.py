"""Obtain and check the noforeignland API token.

## What the credential is

Every write to noforeignland (`DELETE /api/v1/boat/fix`, and the import replies) is authorised
by a single header:

    authorization: eyJhbGciOiJIUzI1NiJ9.<payload>.<signature>

**Cookies are not used.** A captured browser request also carries `_ga`, `_ga_XFB3XT8XKQ` and
`_ga_BPLPFE2TCB`, but those are Google Analytics; dropping them changes nothing, which the
~100 deletions made this way confirm. Auth is the header alone.

## Why it cannot be scraped from the browser

The obvious approach — `browser_cookie3`, as `~/order-scrapers` uses for svb24 and Decathlon —
does not apply, because the credential is not a cookie. Nor is it sitting in local storage: the
payload decodes to

    {"nonce": 2112, "timestamp": 1785504801089, "sub": "<userId>"}

A per-request nonce and a millisecond timestamp mean the app **mints a fresh token for each
call**, client-side, from something it holds after a Firebase login. Chromium's Local Storage
LevelDB for the origin holds no token matching the `eyJhbGciOiJIUzI1NiJ9.` prefix, so there is
nothing durable to read. Searching it turns up JWTs from unrelated origins, which is a trap:
LevelDB mixes origins in the same files.

In practice the timestamp is barely enforced: a captured token was still accepted **62 hours**
after it was minted, across roughly a hundred requests. Convenient, but do not design around it —
check with `--check` at the start of a session rather than assuming.

## Getting one, in order of preference

1. **The Claude in Chrome extension**, when a session has it connected. It can read the
   `authorization` header off a live request, or run JS in the page to mint one. This is the
   only route that avoids manual work, but the extension is detected at session start, so it
   has to be connected before the session begins.
2. **By hand, from DevTools.** Open the journey page, delete any single fix with the Network
   tab recording, and copy that request as cURL. Takes half a minute, and it doubles as a check
   that the endpoint has not changed — worth something, since this API is undocumented.
   Then: `nfl_auth.py --save '<token>'`
3. There is no third option. If both fail, deletions cannot be automated; uploads still can,
   since import is by email and needs no token at all.

## Where it is kept

`~/tracker/.nfl-token`, mode 0600, and gitignored. It is a bearer credential for a live
account: it does not belong in the repository, in a commit message, or in a scratchpad that
might be committed.
"""
import argparse
import base64
import json
import os
import subprocess
import sys
import time

from boattracker import config, files

TOKEN_FILE = os.path.join(config.TRACKER, '.nfl-token')
BASE = config.FIX_URL
UA = ('Mozilla/5.0 (X11; Linux x86_64) AppleWebKit/537.36 (KHTML, like Gecko) '
      'Chrome/148.0.0.0 Safari/537.36')

def save(token):
    token = token.strip()
    if token.lower().startswith('bearer '):
        token = token[7:].strip()
    if token.count('.') != 2:
        sys.exit('that does not look like a JWT (expected three dot-separated parts)')
    with open(TOKEN_FILE, 'w') as f:
        f.write(token + '\n')
    os.chmod(TOKEN_FILE, 0o600)
    print(f'saved to {TOKEN_FILE} (mode 600)')
    describe(token)

def load():
    if not os.path.exists(TOKEN_FILE):
        sys.exit(f'no token at {TOKEN_FILE} — see the module docstring for how to capture one')
    return files.read_stripped(TOKEN_FILE)

def describe(token):
    try:
        body = token.split('.')[1]
        body += '=' * (-len(body) % 4)
        p = json.loads(base64.urlsafe_b64decode(body))
    except Exception as e:
        print(f'   (could not decode the payload: {e})')
        return
    age = None
    if p.get('timestamp'):
        age = (time.time()*1000 - p['timestamp'])/3600000
    print(f"   sub={p.get('sub')} nonce={p.get('nonce')}"
          + (f' minted {age:.1f} h ago' if age is not None else ''))

def check(token):
    """Probe with a DELETE on an implausible fixId.

    There is no authenticated *read* endpoint to test against — the journey endpoint is public —
    so the probe has to be a write. A fixId of 1 cannot exist, which makes this harmless: a
    401/403 means the token is bad, anything else means it was accepted. In practice a bogus id
    answers **500**, not 404 — the server errors rather than reporting not-found, so do not treat
    5xx as a failure here.
    """
    r = subprocess.run(
        ['curl', '-s', '-m', '25', '-o', '/dev/null', '-w', '%{http_code}',
         '-X', 'DELETE', f'{BASE}?fixId=1',
         '-H', 'accept: application/json, text/plain, */*',
         '-H', f'authorization: {token}',
         '-H', 'origin: https://www.noforeignland.com',
         '-H', f'referer: {config.REFERER}',
         '-H', 'sec-fetch-dest: empty', '-H', 'sec-fetch-mode: cors',
         '-H', 'sec-fetch-site: same-origin', '-A', UA],
        capture_output=True, text=True)
    code = r.stdout.strip()
    print(f'probe HTTP {code}')
    if code in ('401', '403'):
        print('   token rejected — capture a fresh one')
        return 1
    if code == '000':
        print('   no answer (network or Cloudflare); inconclusive, try again')
        return 2
    print('   token accepted')
    return 0

def main():
    ap = argparse.ArgumentParser(description=__doc__,
                                 formatter_class=argparse.RawDescriptionHelpFormatter)
    ap.add_argument('--save', metavar='TOKEN', help='store a token captured from the browser')
    ap.add_argument('--check', action='store_true', help='probe whether the stored token works')
    ap.add_argument('--show', action='store_true', help='decode the stored token payload')
    ap.add_argument('--path', action='store_true', help='print the token file path and exit')
    a = ap.parse_args()
    if a.path:
        print(TOKEN_FILE); return
    if a.save:
        save(a.save); return
    if a.show:
        describe(load()); return
    if a.check:
        sys.exit(check(load()))
    ap.print_help()

if __name__ == '__main__':
    main()
