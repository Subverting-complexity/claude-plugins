"""
`wf quota`: may a long run start another round, judged against the Claude plan
limits?

The caller reads the plan limits (the 5-hour and weekly percent used, and when
each resets) and passes them in. This command adds the settings and prints the
decision: `go`, `wait` or `stop`. It reads no usage itself.

Settings come from three places, each overriding the one before: the defaults in
`wf_core_quota.py`, the personal file at ~/.claude/synergy/quota.json (or the
path in SYNERGY_QUOTA_CONFIG), and the flags of this call. The file is personal
because the limits belong to an account, not to a repository. `--save` writes
the setting flags of the call into that file. A file with no settings in it is
the record that a person chose the defaults, so `configured` is true from then
on and nobody is asked again.

The daily budget needs the weekly percent at the start of the day, which no
reading gives. The first check of each day stores it beside the settings, in
quota-state.json (or the path in SYNERGY_QUOTA_STATE), and the later checks of
that day read it back. `--no-record` reads it and stores nothing.

`scripts/README.md` has the module map.
"""

import datetime
import json
import os

import wf_core
from wf_io import EXIT_ENV, EXIT_OK, EXIT_USAGE, emit

QUOTA_CONFIG_ENV = 'SYNERGY_QUOTA_CONFIG'
QUOTA_STATE_ENV = 'SYNERGY_QUOTA_STATE'
# Two readings name the same weekly reset when their times are this close. The
# reset time a reading carries moves by a fraction of a second between calls.
QUOTA_SAME_RESET_SECONDS = 3600


def quota_config_path():
    return os.environ.get(QUOTA_CONFIG_ENV) or os.path.join(
        os.path.expanduser('~'), '.claude', 'synergy', 'quota.json')


def quota_state_path():
    return os.environ.get(QUOTA_STATE_ENV) or os.path.join(
        os.path.dirname(quota_config_path()), 'quota-state.json')


def load_quota_config(path=None):
    """The personal settings as (dict or None, error). None means no file,
    which is different from a file with no settings in it. A byte-order mark,
    which Windows PowerShell 5 writes, is allowed."""
    path = path or quota_config_path()
    if not os.path.isfile(path):
        return None, None
    try:
        with open(path, encoding='utf-8-sig') as fh:
            data = json.load(fh)
        if not isinstance(data, dict):
            raise ValueError('the file must hold one JSON object')
    except (OSError, ValueError) as exc:
        return {}, '%s: %s' % (path, exc)
    return data, None


def write_json(path, data):
    os.makedirs(os.path.dirname(path) or '.', exist_ok=True)
    with open(path, 'w', encoding='utf-8', newline='\n') as fh:
        json.dump(data, fh, indent=2)
        fh.write('\n')


def quota_day_start(weekly_used, weekly_resets, day, record):
    """The weekly percent when day `day` of this week started: the stored
    figure when it is for this week and this day, and the present reading
    otherwise, which is then stored unless `record` is false."""
    path = quota_state_path()
    try:
        with open(path, encoding='utf-8-sig') as fh:
            state = json.load(fh)
        stored_resets = wf_core.quota_parse_time(state.get('weekly_resets'))
        same_week = stored_resets is not None and abs(
            (stored_resets - weekly_resets).total_seconds()) <= QUOTA_SAME_RESET_SECONDS
        start = state.get('day_start_used')
        if (same_week and state.get('day') == day and isinstance(start, (int, float))
                and not isinstance(start, bool) and start <= weekly_used):
            return float(start)
    except (OSError, ValueError, AttributeError):
        pass
    if record:
        try:
            write_json(path, {'weekly_resets': wf_core.quota_iso(weekly_resets), 'day': day,
                              'day_start_used': weekly_used})
        except OSError:
            pass
    return weekly_used


def cmd_quota(args):
    file_settings, file_error = load_quota_config()
    if file_error:
        emit('usage', EXIT_USAGE, reason='The quota settings file could not be read. ' + file_error)
    configured = file_settings is not None
    flags = {key: getattr(args, key, None) for key in wf_core.QUOTA_DEFAULTS}
    settings, errors = wf_core.quota_settings(file_settings, flags)
    if errors:
        emit('usage', EXIT_USAGE, reason='A quota setting is wrong: ' + '; '.join(errors) + '.')

    if getattr(args, 'save', False):
        saved = dict(file_settings or {})
        saved.update((key, value) for key, value in flags.items() if value is not None)
        try:
            write_json(quota_config_path(), saved)
        except OSError as exc:
            emit('error', EXIT_ENV, reason='The quota settings file could not be written: %s' % exc)
        emit('ok', EXIT_OK, saved=saved, settings=settings, settings_file=quota_config_path(),
             configured=True)

    times = {}
    for name in ('now', 'five_hour_resets', 'weekly_resets'):
        text = getattr(args, name, None)
        times[name] = wf_core.quota_parse_time(text)
        if text and times[name] is None:
            emit('usage', EXIT_USAGE,
                 reason='--%s is not an ISO 8601 time: %s' % (name.replace('_', '-'), text))
    now = times['now'] or datetime.datetime.now(datetime.timezone.utc)

    reading = {
        'five_hour_used': args.five_hour_used, 'five_hour_resets': times['five_hour_resets'],
        'weekly_used': args.weekly_used, 'weekly_resets': times['weekly_resets'],
        'before_five_hour': args.before_five_hour, 'before_weekly': args.before_weekly,
    }
    if args.weekly_used is not None and times['weekly_resets'] is not None:
        day = wf_core.quota_week(times['weekly_resets'], now)[0]
        reading['day_start_used'] = quota_day_start(
            args.weekly_used, times['weekly_resets'], day,
            record=not getattr(args, 'no_record', False))
    result = wf_core.quota_decide(reading, settings, now)
    emit('ok', EXIT_OK, now=wf_core.quota_iso(now), configured=configured, settings=settings,
         settings_file=quota_config_path() if configured else None, **result)
