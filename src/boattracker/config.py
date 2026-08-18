"""Where the data lives, and which boat it belongs to.

Until 2026-08-17 thirty-one scripts hardcoded `/home/tobias/tracker`, and several more
hardcoded the boat: `BOAT_ID` twice, `S/Y Solveig` in two mail builders, and
`map/boat/solveig/journey` as an HTTP referer in five. That is what blocked TODO.md's
"Cleanup and split" - the track corpus cannot leave the repository while the tools go on
looking for it there, and the repository cannot be published while the tools only work for
one boat.

## Three layers, highest first

1. **The environment** - `TRACKER_DATA`, `SOLVEIG_DIR`, `PHOTO_ROOT`, `NFL_BOAT_ID` and
   friends. This is how one command is pointed somewhere else for one run.
2. **The config file** - `~/.config/boattracker/config.toml`, or wherever
   `BOATTRACKER_CONFIG` says. This is how a machine is set up once. See
   `config.example.toml` in the repository root.
3. **The defaults**, below.

## Why the defaults depend on where this is running from

In a git checkout the corpus sits *beside* the code, at the repository root - that is
where it has always been and what every path in the project assumed. Installed as a
package there is no checkout to sit beside, so the XDG directories are used instead;
otherwise `pip install boattracker` would leave the tools writing into `site-packages`.
`_checkout()` decides which case applies by looking for `.git` above the package.

## Two roots, and the separation is the point

* `TRACKER` - state that belongs to the installation: the API token, and nothing else.
* `DATA` - the track corpus: `nfl-export/`, `nfl-snapshots/`, `gpstracker-archive/`,
  `nfl-retired/` and the `*.gpx` exports.

`TRACKER_DATA` is what lets the corpus move out without the code following. One trap,
recorded in TODO.md: `track_dates.py` dates tracks by reading the *filenames* in
`nfl-export/`, so pointing `TRACKER_DATA` somewhere that lacks them does not fail - it
silently disables the gap scans' date filtering. Move the whole corpus together.
"""

import os
import tomllib


class ConfigError(Exception):
    """A config file that exists but cannot be used.

    Raised rather than warned about. Falling back to the defaults would point the tools at
    the wrong corpus and report nothing, which is precisely the silent-wrong-path failure
    this module exists to remove.
    """


class NotConfigured(ConfigError):
    """A required setting that has simply not been set.

    Separate from its parent so `get()` can fall back on *absence* without also falling
    back on a malformed value - matching on the text of an error message worked until the
    first message was reworded.
    """


## The shape of the file.  Every key is listed, because an unknown one is an error: a typo
## that silently does nothing leaves the operator believing the tool was redirected.
SCHEMA = {
    'paths': {'state', 'data', 'diary', 'photos', 'journey'},
    'boat': {'id', 'name', 'slug', 'callsign'},
    'mail': {'to', 'from'},
    ## Read only by the daemon half, which must keep working with nothing configured.
    'daemon': {'status_dir', 'alarm_service'},
}


def _xdg(env, fallback):
    return os.environ.get(env) or os.path.expanduser(fallback)


def _checkout():
    """The git checkout this file lives in, or None when installed as a package."""
    package = os.path.dirname(os.path.abspath(__file__))       # .../src/boattracker
    root = os.path.dirname(os.path.dirname(package))           # .../
    return root if os.path.isdir(os.path.join(root, '.git')) else None


def _load(path):
    if not path or not os.path.isfile(path):
        return {}
    try:
        with open(path, 'rb') as f:
            data = tomllib.load(f)
    except (tomllib.TOMLDecodeError, OSError) as e:
        raise ConfigError(f'{path}: {e}') from e
    for section, keys in data.items():
        if section not in SCHEMA:
            raise ConfigError(f'{path}: unknown section [{section}]; '
                              f'expected one of {", ".join(sorted(SCHEMA))}')
        if not isinstance(keys, dict):
            raise ConfigError(f'{path}: [{section}] must be a table')
        for key in keys:
            if key not in SCHEMA[section]:
                raise ConfigError(f'{path}: unknown key {key!r} in [{section}]; '
                                  f'expected one of {", ".join(sorted(SCHEMA[section]))}')
    return data


CONFIG_FILE = os.environ.get('BOATTRACKER_CONFIG') or os.path.join(
    _xdg('XDG_CONFIG_HOME', '~/.config'), 'boattracker', 'config.toml')

_FILE = _load(CONFIG_FILE)


def _setting(env, section, key, default):
    """Environment, then file, then default."""
    value = os.environ.get(env)
    if value:
        return value
    value = _FILE.get(section, {}).get(key)
    return default if value is None else value


def _path(env, key, default):
    return os.path.expanduser(str(_setting(env, 'paths', key, default)))


CHECKOUT = _checkout()

TRACKER = _path('TRACKER_ROOT', 'state',
                CHECKOUT or os.path.join(_xdg('XDG_CONFIG_HOME', '~/.config'), 'boattracker'))
DATA = _path('TRACKER_DATA', 'data',
             CHECKOUT or os.path.join(_xdg('XDG_DATA_HOME', '~/.local/share'), 'boattracker'))

GPXDIR = os.path.join(DATA, 'nfl-export')
SNAPDIR = os.path.join(DATA, 'nfl-snapshots')
ARCHIVE = os.path.join(DATA, 'gpstracker-archive')
RETIRED = os.path.join(DATA, 'nfl-retired')

## --- settings that name a person or a boat --------------------------------------------
##
## None of these has a default, and that is the point.  Until 2026-08-18 they carried the
## author's own values - `Solveig`, the boat id, `~/solveig`, `~/s/photos.tobixen` and a
## personal mail address - which made the software quietly wrong for everybody else and
## put a real address in a public repository.  They are resolved lazily through the module
## `__getattr__` below, so importing this module still works with nothing configured and
## only *using* an unconfigured setting fails, with a message saying which key to set.

_REQUIRED = {
    'BOAT_ID': ('boat', 'id', 'NFL_BOAT_ID', int),
    'BOAT_NAME': ('boat', 'name', 'NFL_BOAT_NAME', str),
    'BOAT_SLUG': ('boat', 'slug', 'NFL_BOAT_SLUG', str),
    'FROM': ('mail', 'from', 'NFL_FROM_MAIL', str),
    'DIARY': ('paths', 'diary', 'SOLVEIG_DIR', 'path'),
    'PHOTOS': ('paths', 'photos', 'PHOTO_ROOT', 'path'),
    ## Optional in practice - reached through get() with a fallback - but declared here so
    ## they resolve the same way and report the same errors.
    'CALLSIGN': ('boat', 'callsign', 'NFL_BOAT_CALLSIGN', str),
    'STATUS_DIR': ('daemon', 'status_dir', 'BOATTRACKER_STATUS_DIR', 'path'),
    'ALARM_SERVICE': ('daemon', 'alarm_service', 'BOATTRACKER_ALARM_SERVICE', str),
}

## Built from the above rather than stored, so they cannot drift out of step with it.
_DERIVED = {
    'DIARY_GLOB': lambda: os.path.join(_require('DIARY'), 'diary-*.md'),
    ## The fallback is computed only when the key is absent.  Passing
    ## `os.path.join(_require('DIARY'), ...)` as the default argument evaluated it
    ## eagerly, so setting `journey` alone still demanded `diary` and blamed the wrong key.
    'JOURNEY': lambda: _journey(),
    'PLANS': lambda: os.path.join(_require('JOURNEY'), 'plans'),
    'JOURNEY_URL': lambda: (f'{SITE}/api/v1/boat/journey'
                            f'?boatId={_require("BOAT_ID")}&showStories=true'),
    ## The site rejects an API call whose referer is not the boat's own journey page.
    'REFERER': lambda: f'{SITE}/map/boat/{_require("BOAT_SLUG")}/journey',
}


def _journey():
    value = _setting('TRACKER_JOURNEY', 'paths', 'journey', None)
    if value is None:
        value = os.path.join(_require('DIARY'), 'journey')
    return os.path.expanduser(str(value))


def _require(name):
    if name in _DERIVED:
        return _DERIVED[name]()
    if name not in _REQUIRED:
        raise ConfigError(f'{name!r} is not a setting this module knows about')
    section, key, env, kind = _REQUIRED[name]
    value = _setting(env, section, key, None)
    if value is None:
        raise NotConfigured(
            f'{name} is not configured, and there is no sensible default for it - it names '
            f'a particular boat or person. Set [{section}] {key} in {CONFIG_FILE}, or the '
            f'{env} environment variable. See config.example.toml.')
    if kind == 'path':
        return os.path.expanduser(str(value))
    try:
        return kind(value)
    except (TypeError, ValueError) as e:
        raise ConfigError(f'[{section}] {key} in {CONFIG_FILE}: {value!r} is not a '
                          f'{kind.__name__}') from e


def get(name, fallback=None):
    """A setting, or `fallback` when it is not configured.

    For the things the daemon reads. It has nothing to do with noforeignland and must keep
    running on a machine where none of this is set up, so "no boat name" is an ordinary
    state rather than an error. A value that *is* set but malformed still raises — falling
    back on a typo would hide it.
    """
    try:
        return _require(name)
    except NotConfigured:
        return fallback


def lazy_module_getattr(*names, **derived):
    """A module-level `__getattr__` forwarding these names to this module's settings.

    Several tools want `BOAT_ID` or `FROM` as a module attribute of their own. Binding it
    at import time - `BOAT_ID = config.BOAT_ID` - makes merely *importing* the module fail
    on an unconfigured machine, which broke `--help` for ten of the twelve journey tools
    and contradicted what this module's own docstring promises. This gives them the same
    attribute, resolved when it is read.

    Names are settings forwarded as-is; keyword arguments are zero-argument callables for
    values built out of a setting, e.g. `INDEX=lambda: f"{PHOTOS}/exif-index.json"`.
    """
    def __getattr__(name):
        if name in names:
            return _require(name)
        if name in derived:
            return derived[name]()
        raise AttributeError(f'no attribute {name!r}')
    return __getattr__


def __getattr__(name):
    """PEP 562: only reached for names this module does not define at import time.

    A required-but-unset name raises `NotConfigured` rather than `AttributeError`, so
    `hasattr(config, 'BOAT_ID')` propagates instead of quietly returning False. That is
    deliberate: silently answering "no such setting" for a setting that exists and simply
    is not configured is how a tool ends up running against the wrong boat.
    """
    if name in _REQUIRED or name in _DERIVED:
        return _require(name)
    raise AttributeError(f'module {__name__!r} has no attribute {name!r}')


SITE = 'https://www.noforeignland.com'
FIX_URL = f'{SITE}/api/v1/boat/fix'
CONFIG_URL = f'{SITE}/api/v1/boat/journey/config'

## Not personal: this is the importer's own address, the same for every user of the site.
TO = str(_setting('NFL_TRACKING_MAIL', 'mail', 'to', 'tracking@noforeignland.com'))


def subject(name: str) -> str:
    """The Subject line the importer matches on: `<Boat> GPX track <name>`."""
    return f'{_require("BOAT_NAME")} GPX track {name}'
