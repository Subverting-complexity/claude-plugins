"""
Whether a long run may start another round, judged against the Claude plan
limits.

A Claude plan has a 5-hour limit and a weekly limit, each reported as a percent
used with a reset time. `orchestrate` reads both before every round and asks
this module one question: may the next round start? The answer is `go`, `wait`
(with the time to continue) or `stop`.

Three checks, and a round starts only when all of them pass:

  - `five_hour`: the 5-hour percent used, plus what one round costs, stays at
    or below the 5-hour ceiling.
  - `weekly`: the weekly percent used, plus what one round costs, stays at or
    below the weekly ceiling.
  - `daily`: what today has used of the weekly limit, plus what one round
    costs, stays at or below today's budget. The week is cut into 7 days of 24
    hours counted from the weekly reset. Today's budget is what was left of
    the weekly limit when the day started, divided by the days left in the
    week with today counted, times `daily_share` percent. So a heavy day makes
    every later day's budget smaller, and a light day makes it larger.
    `week.budget_basis` writes the sum out in words. The start of the day is
    exact only when an earlier check of the same day stored it
    (`day_start_source: stored`). Otherwise it is the present reading, and
    `week.day_start_note` says how many hours of the day came before it.

What one round costs is the last round's measured rise where there is one, and
the configured reserve before that.

Pure: `scripts/README.md` has the module map.
"""

import datetime
import math

QUOTA_WEEK_DAYS = 7
QUOTA_ON_LIMIT = ('stop', 'wait')
QUOTA_ON_UNKNOWN = ('continue', 'stop')

# Every setting, with its default. The ceilings sit below 100 so that work a
# person does by hand in the same window still has room. The reserves are an
# estimate of one bulk-execute round, used only until a round has been measured.
QUOTA_DEFAULTS = {
    'five_hour_ceiling': 85.0,
    'weekly_ceiling': 90.0,
    'daily_share': 100.0,
    'round_reserve_five_hour': 15.0,
    'round_reserve_weekly': 3.0,
    'on_limit': 'stop',
    'max_wait_hours': 5.0,
    'on_unknown': 'continue',
}

_PERCENT_KEYS = ('five_hour_ceiling', 'weekly_ceiling', 'daily_share',
                 'round_reserve_five_hour', 'round_reserve_weekly')
_CHOICE_KEYS = {'on_limit': QUOTA_ON_LIMIT, 'on_unknown': QUOTA_ON_UNKNOWN}


def quota_settings(*layers):
    """The settings after each layer in turn overrides the defaults. A layer is
    a dict; a key whose value is None is left alone. Returns (settings, errors),
    and the settings are usable only when errors is empty."""
    settings = dict(QUOTA_DEFAULTS)
    errors = []
    for layer in layers:
        for key, value in (layer or {}).items():
            if value is None:
                continue
            if key not in QUOTA_DEFAULTS:
                errors.append('unknown setting "%s"' % key)
            elif key in _CHOICE_KEYS:
                if value not in _CHOICE_KEYS[key]:
                    errors.append('"%s" must be one of: %s' % (key, ', '.join(_CHOICE_KEYS[key])))
                else:
                    settings[key] = value
            elif isinstance(value, bool) or not isinstance(value, (int, float)):
                errors.append('"%s" must be a number' % key)
            elif key in _PERCENT_KEYS and not 0 <= value <= 100:
                errors.append('"%s" must be from 0 to 100' % key)
            elif value < 0:
                errors.append('"%s" must not be negative' % key)
            else:
                settings[key] = float(value)
    return settings, errors


def quota_parse_time(text):
    """An ISO 8601 time as an aware UTC datetime, or None. A time with no zone
    is read as UTC."""
    if not text:
        return None
    try:
        moment = datetime.datetime.fromisoformat(str(text).strip().replace('Z', '+00:00'))
    except ValueError:
        return None
    if moment.tzinfo is None:
        moment = moment.replace(tzinfo=datetime.timezone.utc)
    return moment.astimezone(datetime.timezone.utc)


def quota_iso(moment):
    return moment.strftime('%Y-%m-%dT%H:%M:%SZ') if moment else None


def quota_week(weekly_resets, now):
    """Where `now` falls in the week that ends at `weekly_resets`: the day
    number from 1 to 7, and when that week started."""
    started = weekly_resets - datetime.timedelta(days=QUOTA_WEEK_DAYS)
    elapsed_days = (now - started).total_seconds() / 86400.0
    day = min(QUOTA_WEEK_DAYS, max(1, int(math.floor(elapsed_days)) + 1))
    return day, started


def quota_day_budget(used_at_start, day, share):
    """The percent of the weekly limit one day may use: what was left when the
    day started, spread evenly over the days left with this one counted, times
    the share."""
    days_left = QUOTA_WEEK_DAYS - day + 1
    return max(0.0, 100.0 - used_at_start) / days_left * share / 100.0


def quota_budget_basis(day_start, days_left, share, budget):
    """The sum behind a day's budget, in words, so a person can check it. Today
    counts as a whole day even when part of it has passed."""
    return ('%g%% of the weekly limit was left when the day started, divided by %d %s left '
            '(today counts as a whole day), times a %g%% share, is %g%%.'
            % (_round1(max(0.0, 100.0 - day_start)), days_left,
               'day' if days_left == 1 else 'days', share, _round1(budget)))


def quota_day_start_note(source, day, hours_into_day):
    """Why `day_start_used` may be higher than the real start of the day. Only
    a start stored by an earlier check of the same day is exact. The others are
    the reading itself, so use before it is not counted in `used_today`."""
    if source == 'first_check':
        what = 'This is the first check of day %d, so its reading is taken as the start of the day.'
    else:
        what = ('No start of day %d is stored, so the present reading is taken as the start, '
                'and nothing is stored.')
    return (what % day + ' Day %d began %.1f hours ago. Use of the plan before this reading is '
            'not counted in used_today, so the room left today may be overstated.'
            % (day, hours_into_day))


def quota_round_cost(used, before, reserve):
    """What one round costs: the measured rise from `before` to `used`, or the
    reserve when there is no earlier reading or the figure fell, which means
    the window reset during the round."""
    if used is None or before is None or used < before:
        return reserve, 'reserve'
    return used - before, 'measured'


def _round1(value):
    return None if value is None else round(value, 1)


def quota_decide(reading, settings, now):
    """May the next round start?

    `reading` holds `five_hour_used`, `five_hour_resets`, `weekly_used` and
    `weekly_resets` (percent and aware datetimes), and optionally
    `before_five_hour` and `before_weekly`, the reading taken before the last
    round, and `day_start_used`, the weekly percent when today started. Any of
    them may be None; with no `day_start_used` the day is taken to start now.
    Returns a dict with `decision`, `reason`, `resume_at`, `wait_seconds`, the
    three `checks`, and the figures behind them.
    """
    five_used, weekly_used = reading.get('five_hour_used'), reading.get('weekly_used')
    five_resets, weekly_resets = reading.get('five_hour_resets'), reading.get('weekly_resets')
    result = {'decision': 'go', 'reason': '', 'resume_at': None, 'wait_seconds': None,
              'checks': [], 'week': None, 'round_cost': None}

    if five_used is None and weekly_used is None:
        stop = settings['on_unknown'] == 'stop'
        result['decision'] = 'stop' if stop else 'go'
        result['reason'] = ('The Claude plan limits could not be read, and on_unknown is "%s".'
                            % settings['on_unknown'])
        result['unknown'] = True
        return result

    five_cost, five_source = quota_round_cost(
        five_used, reading.get('before_five_hour'), settings['round_reserve_five_hour'])
    weekly_cost, weekly_source = quota_round_cost(
        weekly_used, reading.get('before_weekly'), settings['round_reserve_weekly'])
    result['round_cost'] = {'five_hour': _round1(five_cost), 'five_hour_source': five_source,
                            'weekly': _round1(weekly_cost), 'weekly_source': weekly_source}

    # Each failed check names when it would pass again, or None when no time is known.
    failed = []

    def check(name, used, cost, limit, resume, text):
        after = used + cost
        ok = after <= limit + 1e-9
        result['checks'].append({'name': name, 'ok': ok, 'used': _round1(used),
                                 'after_round': _round1(after), 'limit': _round1(limit)})
        if not ok:
            failed.append((resume, text % (_round1(used), _round1(cost), _round1(limit))))

    if five_used is not None:
        check('five_hour', five_used, five_cost, settings['five_hour_ceiling'], five_resets,
              'The 5-hour limit is %s%% used and a round costs about %s%%, above the %s%% ceiling.')

    if weekly_used is not None:
        check('weekly', weekly_used, weekly_cost, settings['weekly_ceiling'], weekly_resets,
              'The weekly limit is %s%% used and a round costs about %s%%, above the %s%% ceiling.')
        if weekly_resets is not None:
            day, started = quota_week(weekly_resets, now)
            share = settings['daily_share']
            day_start = reading.get('day_start_used')
            source = reading.get('day_start_source') or 'stored'
            if day_start is None or day_start > weekly_used:
                day_start, source = weekly_used, 'estimate'
            budget = quota_day_budget(day_start, day, share)
            days_left = QUOTA_WEEK_DAYS - day + 1
            day_began = started + datetime.timedelta(days=day - 1)
            result['week'] = {'day': day, 'of': QUOTA_WEEK_DAYS, 'started_at': quota_iso(started),
                              'days_left': days_left,
                              'day_started_at': quota_iso(day_began),
                              'day_start_used': _round1(day_start),
                              'day_start_source': source,
                              'day_budget': _round1(budget),
                              'budget_basis': quota_budget_basis(day_start, days_left, share, budget),
                              'used_today': _round1(weekly_used - day_start)}
            if source != 'stored':
                hours = max(0.0, (now - day_began).total_seconds() / 3600.0)
                result['week']['day_start_note'] = quota_day_start_note(source, day, hours)
            # The first later day whose budget covers one round, taking that
            # day to start at the present reading, or the weekly reset when no
            # day of this week does.
            resume = weekly_resets
            for later in range(day + 1, QUOTA_WEEK_DAYS + 1):
                if weekly_cost <= quota_day_budget(weekly_used, later, share) + 1e-9:
                    resume = started + datetime.timedelta(days=later - 1)
                    break
            check('daily', weekly_used - day_start, weekly_cost, budget, resume,
                  'Day %d of the week has used %%s%%%% of the weekly limit and a round costs '
                  'about %%s%%%%, above the %%s%%%% budget for the day.' % day)

    if not failed:
        result['reason'] = 'Every check passed.'
        return result

    result['reason'] = ' '.join(text for _, text in failed)
    resumes = [resume for resume, _ in failed]
    if all(resumes):
        resume_at = max(resumes)
        wait = max(0, int(math.ceil((resume_at - now).total_seconds())))
        result['resume_at'] = quota_iso(resume_at)
        result['wait_seconds'] = wait
        if settings['on_limit'] == 'wait' and wait <= settings['max_wait_hours'] * 3600:
            result['decision'] = 'wait'
            return result
        if settings['on_limit'] == 'wait':
            result['reason'] += (' The wait is %.1f hours, longer than max_wait_hours (%s).'
                                 % (wait / 3600.0, _round1(settings['max_wait_hours'])))
    result['decision'] = 'stop'
    return result
