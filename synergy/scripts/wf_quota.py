"""
`wf quota`: may a long run start another round, judged against the Claude plan
limits?

The caller reads the plan limits (the 5-hour and weekly percent used, and when
each resets) and passes them in. This command adds the settings and prints the
decision: `go`, `wait` or `stop`. It reads no usage itself and changes nothing,
so it is safe to run at any time.

Settings come from three places, each overriding the one before: the defaults in
`wf_core_quota.py`, the personal file at ~/.claude/synergy/quota.json (or the
path in SYNERGY_QUOTA_CONFIG), and the flags of this call. The file is personal
because the limits belong to an account, not to a repository.

`scripts/README.md` has the module map.
"""

import datetime
import json
import os

import wf_core
from wf_io import EXIT_OK, EXIT_USAGE, emit

QUOTA_CONFIG_ENV = 'SYNERGY_QUOTA_CONFIG'


def quota_config_path():
    return os.environ.get(QUOTA_CONFIG_ENV) or os.path.join(
        os.path.expanduser('~'), '.claude', 'synergy', 'quota.json')


def load_quota_config(path=None):
    """The personal settings as (dict, error). No file is an empty dict. A
    byte-order mark, which Windows PowerShell 5 writes, is allowed."""
    path = path or quota_config_path()
    if not os.path.isfile(path):
        return {}, None
    try:
        with open(path, encoding='utf-8-sig') as fh:
            data = json.load(fh)
        if not isinstance(data, dict):
            raise ValueError('the file must hold one JSON object')
    except (OSError, ValueError) as exc:
        return {}, '%s: %s' % (path, exc)
    return data, None


def cmd_quota(args):
    file_settings, file_error = load_quota_config()
    if file_error:
        emit('usage', EXIT_USAGE, reason='The quota settings file could not be read. ' + file_error)
    flags = {key: getattr(args, key, None) for key in wf_core.QUOTA_DEFAULTS}
    settings, errors = wf_core.quota_settings(file_settings, flags)
    if errors:
        emit('usage', EXIT_USAGE, reason='A quota setting is wrong: ' + '; '.join(errors) + '.')

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
    result = wf_core.quota_decide(reading, settings, now)
    settings['daily_percent'] = round(settings['daily_percent'], 1)
    emit('ok', EXIT_OK, now=wf_core.quota_iso(now), settings=settings,
         settings_file=quota_config_path() if file_settings else None, **result)
