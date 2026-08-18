"""Where the data lives and which boat it is, in one place instead of thirty-one.

TODO.md's "Cleanup and split" could not start while thirty-one scripts hardcoded
`/home/tobias/tracker`: move a single file and the tools go on reading the old path, or
fail with it. So the roots became configuration first, and the moves become possible after.

Three layers, highest wins: **environment variable, then config file, then default.** The
environment is on top because it is how one command is pointed somewhere else for one run;
the file is how a machine is set up once.

The defaults are deliberately different depending on where the package is running from. In
a git checkout the corpus sits beside the code, which is where it has always been and what
every existing path assumed. Installed as a package there is no checkout to sit beside, so
the XDG directories are used instead - otherwise a `pip install` would have the tools
writing into `site-packages`.
"""

import importlib
import os

import pytest

from boattracker import config as default_config

REPO = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))


def conftest_absent_config():
    """The nonexistent config path `conftest.py` pins for the whole suite."""
    return os.path.join(REPO, 'tests', 'no-such-config.toml')

ENV_KEYS = ('TRACKER_ROOT', 'TRACKER_DATA', 'SOLVEIG_DIR', 'PHOTO_ROOT', 'NFL_BOAT_ID',
            'NFL_BOAT_NAME', 'NFL_BOAT_SLUG', 'NFL_TRACKING_MAIL', 'NFL_FROM_MAIL', 'TRACKER_JOURNEY',
            'BOATTRACKER_CONFIG', 'XDG_CONFIG_HOME', 'XDG_DATA_HOME')


@pytest.fixture
def reloaded(monkeypatch, tmp_path):
    """config reads the environment and the file once, at import; give a fresh read.

    `BOATTRACKER_CONFIG` is pointed at a path that does not exist unless the test says
    otherwise, so "no config file" is the baseline. Without that the suite reads whatever
    the developer has in `~/.config/boattracker/config.toml` and the tests that assert the
    *defaults* fail on a machine that has configured anything - which is exactly what
    happened the moment the corpus was moved out of the repository.
    """
    absent = str(tmp_path / 'no-such-config.toml')

    def load(**env):
        for key in ENV_KEYS:
            monkeypatch.delenv(key, raising=False)
        monkeypatch.setenv('BOATTRACKER_CONFIG', absent)
        for key, value in env.items():
            monkeypatch.setenv(key, value)
        return importlib.reload(default_config)
    yield load
    ## Teardown has to put the module back the way `conftest.py` set it up, not the way the
    ## developer's own machine is configured.  Clearing the environment and reloading was
    ## not enough: `monkeypatch` has not yet undone conftest's variables at this point, so
    ## the reload read ~/.config/boattracker/config.toml and left `config.DATA` pointing at
    ## the author's real corpus for every test module that ran after this one.
    for key in ENV_KEYS:
        monkeypatch.delenv(key, raising=False)
    monkeypatch.setenv('BOATTRACKER_CONFIG', conftest_absent_config())
    importlib.reload(default_config)


@pytest.fixture
def conf(tmp_path):
    """Write a config file and return its path."""
    def write(text):
        path = tmp_path / 'config.toml'
        path.write_text(text)
        return str(path)
    return write


## --- what has a default, and what refuses to guess ------------------------------

def test_a_checkout_keeps_the_corpus_beside_the_code(reloaded):
    cfg = reloaded()
    assert cfg.TRACKER == REPO
    assert cfg.DATA == REPO


def test_the_derived_directories_hang_off_the_data_root(reloaded):
    cfg = reloaded()
    assert cfg.GPXDIR == os.path.join(REPO, 'nfl-export')
    assert cfg.SNAPDIR == os.path.join(REPO, 'nfl-snapshots')
    assert cfg.ARCHIVE == os.path.join(REPO, 'gpstracker-archive')
    assert cfg.RETIRED == os.path.join(REPO, 'nfl-retired')


## Everything below names a person or a boat, so none of it may be guessed.  Until
## 2026-08-18 these carried the author's own values as defaults - `Solveig`, the boat id,
## `~/solveig`, `~/s/photos.tobixen` and a personal mail address - which made the software
## quietly wrong for everyone else and published them in a public repository.

@pytest.mark.parametrize('name', ['BOAT_ID', 'BOAT_NAME', 'BOAT_SLUG', 'FROM',
                                  'DIARY', 'PHOTOS', 'JOURNEY', 'PLANS', 'DIARY_GLOB',
                                  'JOURNEY_URL', 'REFERER'])
def test_a_personal_setting_has_no_default_and_says_how_to_set_it(reloaded, name):
    cfg = reloaded()
    with pytest.raises(Exception) as excinfo:
        getattr(cfg, name)
    assert is_config_error(excinfo.value)
    ## the message has to be actionable: which key, which file, which variable
    ## Actionable means all three: which file, which key, which environment variable.
    message = str(excinfo.value)
    assert cfg.CONFIG_FILE in message
    assert 'config.example.toml' in message


def test_an_unknown_attribute_is_still_an_attribute_error(reloaded):
    """`__getattr__` must not turn a typo into a ConfigError, or `hasattr` breaks."""
    with pytest.raises(AttributeError):
        _ = reloaded().NO_SUCH_SETTING


def test_the_importer_address_is_not_personal_and_keeps_its_default(reloaded):
    """`tracking@noforeignland.com` belongs to the service, not to anybody here."""
    assert reloaded().TO == 'tracking@noforeignland.com'


## --- the environment layer ---------------------------------------------------------

def test_moving_the_data_leaves_the_code_where_it_is(reloaded):
    """The whole reason for two roots: the corpus can go without the scripts following."""
    cfg = reloaded(TRACKER_DATA='/mnt/solveig-tracks')

    assert cfg.TRACKER == REPO
    assert cfg.DATA == '/mnt/solveig-tracks'
    assert cfg.GPXDIR == '/mnt/solveig-tracks/nfl-export'
    assert cfg.ARCHIVE == '/mnt/solveig-tracks/gpstracker-archive'


def test_a_tilde_in_the_environment_is_expanded(reloaded):
    """`TRACKER_DATA=~/solveig-tracks` from a shell that did not expand it would otherwise
    create a directory literally named `~`."""
    cfg = reloaded(TRACKER_DATA='~/solveig-tracks')
    assert cfg.DATA == os.path.expanduser('~/solveig-tracks')


def test_the_boat_id_is_an_integer_however_it_arrives(reloaded):
    """It is interpolated into URLs and posted as a form field; a string would compare
    unequal to the ids read back out of the journey JSON."""
    cfg = reloaded(NFL_BOAT_ID='123456789')
    assert cfg.BOAT_ID == 123456789


def test_a_boat_id_that_is_not_a_number_says_so(reloaded):
    cfg = reloaded(NFL_BOAT_ID='not-a-number')
    with pytest.raises(Exception) as excinfo:
        _ = cfg.BOAT_ID
    assert is_config_error(excinfo.value)


def test_the_urls_carry_the_configured_boat(reloaded):
    cfg = reloaded(NFL_BOAT_ID='42', NFL_BOAT_SLUG='another')
    assert 'boatId=42' in cfg.JOURNEY_URL
    assert cfg.REFERER == 'https://www.noforeignland.com/map/boat/another/journey'


def test_the_mail_subject_carries_the_configured_boat_name(reloaded):
    cfg = reloaded(NFL_BOAT_NAME='Nordkapp')
    assert cfg.subject('2026-08-10') == 'Nordkapp GPX track 2026-08-10'


## --- the file layer ----------------------------------------------------------------

def test_a_config_file_sets_the_roots_and_the_boat(reloaded, conf):
    path = conf("""
        [paths]
        data = "/srv/tracks"
        diary = "/srv/diaries"
        photos = "/srv/photos"

        journey = "/srv/record"

        [boat]
        id = 777
        name = "Nordkapp"
        slug = "nordkapp"
        """)
    cfg = reloaded(BOATTRACKER_CONFIG=path)

    assert cfg.DATA == '/srv/tracks'
    assert cfg.GPXDIR == '/srv/tracks/nfl-export'
    assert cfg.DIARY_GLOB == '/srv/diaries/diary-*.md'
    assert cfg.PHOTOS == '/srv/photos'
    assert cfg.PLANS == '/srv/record/plans'
    assert cfg.BOAT_ID == 777
    assert cfg.BOAT_NAME == 'Nordkapp'
    assert cfg.REFERER.endswith('/map/boat/nordkapp/journey')


def test_the_environment_beats_the_file(reloaded, conf):
    """One command pointed somewhere else for one run must not need the file edited."""
    path = conf('[paths]\ndata = "/srv/tracks"\n')
    cfg = reloaded(BOATTRACKER_CONFIG=path, TRACKER_DATA='/mnt/other')
    assert cfg.DATA == '/mnt/other'


def test_the_file_beats_the_default(reloaded, conf):
    path = conf('[paths]\ndata = "/srv/tracks"\n')
    assert reloaded(BOATTRACKER_CONFIG=path).DATA == '/srv/tracks'


def test_a_partial_file_leaves_the_rest_alone(reloaded, conf):
    """A partial file is the normal case - most people set one or two things.

    What "alone" means differs by setting, which is the whole design: `data` has a sensible
    default and keeps it, while `id` names a particular boat and so stays unconfigured
    rather than being guessed.
    """
    path = conf('[boat]\nname = "Nordkapp"\n')
    cfg = reloaded(BOATTRACKER_CONFIG=path)

    assert cfg.BOAT_NAME == 'Nordkapp'
    assert cfg.DATA == REPO
    with pytest.raises(Exception) as excinfo:
        _ = cfg.BOAT_ID
    assert is_config_error(excinfo.value)


def test_a_tilde_in_the_file_is_expanded(reloaded, conf):
    path = conf('[paths]\ndata = "~/tracks"\n')
    assert reloaded(BOATTRACKER_CONFIG=path).DATA == os.path.expanduser('~/tracks')


def test_a_missing_config_file_is_not_an_error(reloaded, tmp_path):
    """Nothing needs configuring to run from a checkout, so absence is the normal state."""
    cfg = reloaded(BOATTRACKER_CONFIG=str(tmp_path / 'nope.toml'))
    assert cfg.DATA == REPO


def test_an_unparseable_config_file_says_which_file(reloaded, conf):
    """Silently falling back to the defaults would point the tools at the wrong corpus and
    report nothing - the exact failure mode this whole module exists to remove."""
    path = conf('[paths\ndata = ')
    with pytest.raises(Exception) as excinfo:
        reloaded(BOATTRACKER_CONFIG=path)
    assert is_config_error(excinfo.value)
    assert path in str(excinfo.value)


def test_an_unknown_key_is_refused_rather_than_ignored(reloaded, conf):
    """A typo that silently does nothing is worse than a crash: the tool carries on
    against the default corpus and the operator believes it was redirected."""
    path = conf('[paths]\ndataa = "/srv/tracks"\n')
    with pytest.raises(Exception) as excinfo:
        reloaded(BOATTRACKER_CONFIG=path)
    assert is_config_error(excinfo.value)
    assert 'dataa' in str(excinfo.value)


def is_config_error(exc):
    """Compared by name over the whole ancestry, not by identity.

    `importlib.reload` re-executes the module and so builds a *new* `ConfigError` class
    each time; the one raised inside a reload is never the same object as the one bound
    here, and `pytest.raises(default_config.ConfigError)` would not match it. The ancestry
    is walked rather than just the concrete type, because `NotConfigured` — the subclass
    that means "simply not set" — is what most of these raise.
    """
    return any(c.__name__ in ('ConfigError', 'NotConfigured') for c in type(exc).__mro__)


## --- where the file is looked for --------------------------------------------------

def test_the_config_file_defaults_to_the_xdg_location(reloaded, tmp_path):
    (tmp_path / 'boattracker').mkdir()
    (tmp_path / 'boattracker' / 'config.toml').write_text('[boat]\nname = "Xdg"\n')
    ## Empty rather than unset: the fixture points BOATTRACKER_CONFIG at a nonexistent
    ## file by default, and config falls through to the XDG location on a falsy value.
    cfg = reloaded(BOATTRACKER_CONFIG='', XDG_CONFIG_HOME=str(tmp_path))

    assert cfg.CONFIG_FILE == str(tmp_path / 'boattracker' / 'config.toml')
    assert cfg.BOAT_NAME == 'Xdg'


## --- optional settings, for the daemon ----------------------------------------------
##
## The daemon must keep running with nothing configured at all - it is the half of this
## project that has nothing to do with noforeignland - so the values it reads are looked up
## with `get()` and fall back rather than raising.

def test_get_returns_the_fallback_when_a_setting_is_absent(reloaded):
    assert reloaded().get('BOAT_NAME', 'Boat') == 'Boat'


def test_get_returns_the_setting_when_it_is_configured(reloaded):
    assert reloaded(NFL_BOAT_NAME='Nordkapp').get('BOAT_NAME', 'Boat') == 'Nordkapp'


def test_get_does_not_swallow_a_misconfigured_value(reloaded):
    """A boat id that is not a number is a mistake to report, not a reason to fall back."""
    cfg = reloaded(NFL_BOAT_ID='not-a-number')
    with pytest.raises(Exception) as excinfo:
        cfg.get('BOAT_ID', 0)
    assert is_config_error(excinfo.value)


def test_the_callsign_is_optional(reloaded, conf):
    """Not every boat has one, so it may not be required; it is only used to label a track."""
    assert reloaded().get('CALLSIGN', '') == ''
    path = conf('[boat]\ncallsign = "XX1234"\n')
    assert reloaded(BOATTRACKER_CONFIG=path).CALLSIGN == 'XX1234'


def test_the_daemon_status_directory_is_optional(reloaded, conf):
    """The anchor alarm reads an override for the anchoring time and the expected swing
    radius from files a human can edit on a server. No server, no override."""
    assert reloaded().get('STATUS_DIR', None) is None
    path = conf('[daemon]\nstatus_dir = "/srv/www/boat"\n')
    assert reloaded(BOATTRACKER_CONFIG=path).STATUS_DIR == '/srv/www/boat'


def test_the_alarm_service_description_is_configurable(reloaded, conf):
    path = conf('[daemon]\nalarm_service = "Nordkapp may be drifting"\n')
    assert reloaded(BOATTRACKER_CONFIG=path).ALARM_SERVICE == 'Nordkapp may be drifting'


## --- the gaps that let real bugs through, 2026-08-18 ------------------------------

def test_the_journey_can_be_set_without_the_diary(reloaded, conf):
    """`journey`'s fallback is `<diary>/journey`, and passing that as a default *argument*
    evaluated it eagerly — so setting `journey` alone still demanded `diary`, and blamed
    the wrong key in the error."""
    path = conf('[paths]\njourney = "/srv/record"\n')
    cfg = reloaded(BOATTRACKER_CONFIG=path)
    assert cfg.JOURNEY == '/srv/record'
    assert cfg.PLANS == '/srv/record/plans'


def test_get_on_an_unknown_name_is_a_config_error_not_a_key_error(reloaded):
    """`_require` indexed `_REQUIRED[name]` unguarded, so a typo surfaced as KeyError."""
    with pytest.raises(Exception) as excinfo:
        reloaded().get('BOAT_NAM', 'fallback')
    assert is_config_error(excinfo.value)


def test_hasattr_on_an_unset_required_setting_propagates(reloaded):
    """Deliberate, and worth pinning because it surprises people: `hasattr` normally
    answers False. Answering False for a setting that *exists* and merely is not
    configured is how a tool ends up silently running against the wrong boat."""
    cfg = reloaded()
    with pytest.raises(Exception) as excinfo:
        hasattr(cfg, 'BOAT_ID')
    assert is_config_error(excinfo.value)
