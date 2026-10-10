#!/usr/bin/env python3
"""
Tests for `wf quota`, which tells a long run whether it may start another round
without going past the Claude plan limits.

The rules are pure: a reading, the settings and a time go in, and `go`, `wait`
or `stop` comes out. Nothing here reads real usage or the clock. The rule that
matters most is the daily allowance, which lets the weekly limit be used only
as fast as the week passes.

Run standalone (`python3 tests/test_quota.py`) or via `run-tests.sh`.
"""

import datetime
import io
import json
import os
import sys
import tempfile
import unittest
from contextlib import redirect_stdout
from unittest import mock

HERE = os.path.dirname(os.path.abspath(__file__))
sys.path.insert(0, os.path.join(HERE, '..', 'synergy', 'scripts'))

import wf  # noqa: E402
import wf_core  # noqa: E402
import wf_quota  # noqa: E402

UTC = datetime.timezone.utc
# A week that started on 1 October at 00:00 and resets on 8 October at 00:00.
WEEK_START = datetime.datetime(2026, 10, 1, tzinfo=UTC)
WEEKLY_RESETS = WEEK_START + datetime.timedelta(days=7)


def at(days=0, hours=0):
    return WEEK_START + datetime.timedelta(days=days, hours=hours)


def decide(now, five=10, weekly=5, five_resets=None, settings=None, **reading):
    full = {'five_hour_used': five, 'weekly_used': weekly, 'weekly_resets': WEEKLY_RESETS,
            'five_hour_resets': five_resets or now + datetime.timedelta(hours=2)}
    full.update(reading)
    merged, errors = wf_core.quota_settings(settings)
    assert not errors, errors
    return wf_core.quota_decide(full, merged, now)


def check(result, name):
    return next(c for c in result['checks'] if c['name'] == name)


class TestSettings(unittest.TestCase):

    def test_the_default_daily_percent_is_one_seventh_of_the_week(self):
        settings, errors = wf_core.quota_settings()
        self.assertEqual(errors, [])
        self.assertAlmostEqual(settings['daily_percent'] * 7, 100.0)
        self.assertEqual(settings['on_limit'], 'stop')
        self.assertEqual(settings['on_unknown'], 'continue')

    def test_a_later_layer_overrides_an_earlier_one_and_none_is_skipped(self):
        settings, errors = wf_core.quota_settings(
            {'weekly_ceiling': 70, 'daily_percent': 10}, {'weekly_ceiling': 60, 'daily_percent': None})
        self.assertEqual(errors, [])
        self.assertEqual(settings['weekly_ceiling'], 60.0)
        self.assertEqual(settings['daily_percent'], 10.0)

    def test_wrong_values_are_named(self):
        _, errors = wf_core.quota_settings({'weekly_ceiling': 140, 'on_limit': 'pause',
                                            'daily_percent': '14', 'days': 5, 'max_wait_hours': -1})
        self.assertEqual(len(errors), 5)


class TestWeek(unittest.TestCase):

    def test_days_are_24_hours_counted_from_the_weekly_reset(self):
        self.assertEqual(wf_core.quota_week(WEEKLY_RESETS, at(0))[0], 1)
        self.assertEqual(wf_core.quota_week(WEEKLY_RESETS, at(0, 23))[0], 1)
        self.assertEqual(wf_core.quota_week(WEEKLY_RESETS, at(1))[0], 2)
        self.assertEqual(wf_core.quota_week(WEEKLY_RESETS, at(6, 23))[0], 7)

    def test_a_time_outside_the_week_stays_in_range(self):
        self.assertEqual(wf_core.quota_week(WEEKLY_RESETS, at(-1))[0], 1)
        self.assertEqual(wf_core.quota_week(WEEKLY_RESETS, at(9))[0], 7)


class TestDecision(unittest.TestCase):

    def test_low_usage_goes(self):
        result = decide(at(1, 4))
        self.assertEqual(result['decision'], 'go')
        self.assertTrue(all(c['ok'] for c in result['checks']))
        self.assertEqual(result['week']['day'], 2)
        self.assertEqual(result['week']['allowed_percent'], 28.6)

    def test_the_daily_allowance_stops_a_week_used_too_fast(self):
        # Day 2 allows 28.6%. 27% used plus a 3% round is above it, though far
        # below the 90% weekly ceiling.
        result = decide(at(1, 4), weekly=27)
        self.assertEqual(result['decision'], 'stop')
        self.assertFalse(check(result, 'daily')['ok'])
        self.assertTrue(check(result, 'weekly')['ok'])
        self.assertIn('day 2 of the week', result['reason'])
        # Day 3 allows 42.9%, so the run may continue when day 3 starts.
        self.assertEqual(result['resume_at'], '2026-10-03T00:00:00Z')

    def test_unused_allowance_carries_to_later_days(self):
        # 40% used would fail on day 2, and passes on day 4 (57.1% allowed).
        self.assertEqual(decide(at(1), weekly=40)['decision'], 'stop')
        self.assertEqual(decide(at(3), weekly=40)['decision'], 'go')

    def test_a_configured_daily_percent_is_used(self):
        # 10% a day allows 20% on day 2.
        result = decide(at(1), weekly=18, settings={'daily_percent': 10})
        self.assertFalse(check(result, 'daily')['ok'])
        self.assertEqual(check(result, 'daily')['limit'], 20.0)
        # 18% plus a 3% round needs 21%, which day 3 (30%) is the first to allow.
        self.assertEqual(result['resume_at'], '2026-10-03T00:00:00Z')

    def test_the_resume_day_is_the_first_one_that_covers_the_round(self):
        # 50% used plus 3% needs 53%, which day 4 (57.1%) is the first to allow.
        result = decide(at(0, 1), weekly=50)
        self.assertEqual(result['resume_at'], '2026-10-04T00:00:00Z')

    def test_the_five_hour_ceiling_stops_and_names_the_reset(self):
        resets = at(1, 6)
        result = decide(at(1, 4), five=75, five_resets=resets)
        self.assertEqual(result['decision'], 'stop')
        self.assertFalse(check(result, 'five_hour')['ok'])
        self.assertEqual(result['resume_at'], '2026-10-02T06:00:00Z')
        self.assertEqual(result['wait_seconds'], 7200)

    def test_a_round_that_ends_exactly_on_the_ceiling_goes(self):
        self.assertEqual(decide(at(6), five=70)['decision'], 'go')

    def test_the_weekly_ceiling_resumes_at_the_weekly_reset(self):
        result = decide(at(6, 12), weekly=89)
        self.assertFalse(check(result, 'weekly')['ok'])
        self.assertEqual(result['resume_at'], '2026-10-08T00:00:00Z')

    def test_wait_is_chosen_when_the_limit_clears_in_time(self):
        result = decide(at(1, 4), five=75, five_resets=at(1, 6), settings={'on_limit': 'wait'})
        self.assertEqual(result['decision'], 'wait')
        self.assertEqual(result['wait_seconds'], 7200)

    def test_wait_becomes_stop_when_the_wait_is_too_long(self):
        result = decide(at(1, 4), weekly=27, settings={'on_limit': 'wait'})
        self.assertEqual(result['decision'], 'stop')
        self.assertIn('longer than max_wait_hours', result['reason'])
        longer = decide(at(1, 4), weekly=27, settings={'on_limit': 'wait', 'max_wait_hours': 24})
        self.assertEqual(longer['decision'], 'wait')

    def test_two_failed_checks_wait_for_the_later_one(self):
        result = decide(at(1, 22), five=80, weekly=27, five_resets=at(1, 23),
                        settings={'on_limit': 'wait'})
        self.assertEqual(result['resume_at'], '2026-10-03T00:00:00Z')

    def test_a_failed_check_with_no_reset_time_stops(self):
        result = wf_core.quota_decide({'five_hour_used': 95}, wf_core.quota_settings(
            {'on_limit': 'wait'})[0], at(1))
        self.assertEqual(result['decision'], 'stop')
        self.assertIsNone(result['resume_at'])


class TestRoundCost(unittest.TestCase):

    def test_the_reserve_is_used_before_a_round_is_measured(self):
        result = decide(at(1))
        self.assertEqual(result['round_cost']['five_hour'], 15.0)
        self.assertEqual(result['round_cost']['five_hour_source'], 'reserve')

    def test_a_measured_round_replaces_the_reserve(self):
        # The last round took the 5-hour limit from 30% to 60%. Another 30%
        # would end at 90%, above the 85% ceiling.
        result = decide(at(1), five=60, before_five_hour=30, before_weekly=3)
        self.assertEqual(result['round_cost']['five_hour'], 30.0)
        self.assertEqual(result['round_cost']['five_hour_source'], 'measured')
        self.assertEqual(result['round_cost']['weekly'], 2.0)
        self.assertEqual(result['decision'], 'stop')

    def test_a_cheap_measured_round_lets_the_run_go_further(self):
        # 75% used fails on the 15% reserve and passes on a measured 5%.
        self.assertEqual(decide(at(6), five=75)['decision'], 'stop')
        self.assertEqual(decide(at(6), five=75, before_five_hour=70)['decision'], 'go')

    def test_a_window_that_reset_during_the_round_falls_back_to_the_reserve(self):
        result = decide(at(1), five=8, before_five_hour=70)
        self.assertEqual(result['round_cost']['five_hour_source'], 'reserve')


class TestUnknown(unittest.TestCase):

    def test_no_reading_continues_by_default_and_says_so(self):
        result = wf_core.quota_decide({}, wf_core.quota_settings()[0], at(1))
        self.assertEqual(result['decision'], 'go')
        self.assertTrue(result['unknown'])

    def test_no_reading_stops_when_configured(self):
        settings = wf_core.quota_settings({'on_unknown': 'stop'})[0]
        self.assertEqual(wf_core.quota_decide({}, settings, at(1))['decision'], 'stop')

    def test_one_missing_window_still_checks_the_other(self):
        result = wf_core.quota_decide({'five_hour_used': 95, 'five_hour_resets': at(1, 2)},
                                      wf_core.quota_settings()[0], at(1))
        self.assertEqual([c['name'] for c in result['checks']], ['five_hour'])
        self.assertEqual(result['decision'], 'stop')


class TestCommand(unittest.TestCase):

    def run_quota(self, argv, config=None):
        """Run `wf quota`. Returns (exit_code, parsed stdout)."""
        with tempfile.TemporaryDirectory() as tmp:
            path = os.path.join(tmp, 'quota.json')
            if config is not None:
                with open(path, 'w', encoding='utf-8') as fh:
                    fh.write(config)
            buf = io.StringIO()
            with mock.patch.dict(os.environ, {wf_quota.QUOTA_CONFIG_ENV: path}), \
                    redirect_stdout(buf):
                try:
                    wf.main(['quota'] + argv)
                    code = 0
                except SystemExit as exc:
                    code = exc.code
        return code, json.loads(buf.getvalue())

    READING = ['--now', '2026-10-02T04:00:00Z', '--five-hour-used', '10',
               '--five-hour-resets', '2026-10-02T06:00:00Z',
               '--weekly-used', '27', '--weekly-resets', '2026-10-08T00:00:00Z']

    def test_the_defaults_apply_with_no_file(self):
        code, out = self.run_quota(self.READING)
        self.assertEqual((code, out['decision']), (0, 'stop'))
        self.assertIsNone(out['settings_file'])
        self.assertEqual(out['settings']['daily_percent'], 14.3)

    def test_the_personal_file_overrides_a_default(self):
        code, out = self.run_quota(self.READING, config='{"daily_percent": 20}')
        self.assertEqual((code, out['decision']), (0, 'go'))
        self.assertEqual(out['week']['allowed_percent'], 40.0)
        self.assertTrue(out['settings_file'])

    def test_a_flag_overrides_the_personal_file(self):
        code, out = self.run_quota(self.READING + ['--daily-percent', '10'],
                                   config='{"daily_percent": 20}')
        self.assertEqual(out['decision'], 'stop')
        self.assertEqual(out['settings']['daily_percent'], 10.0)

    def test_a_file_with_a_byte_order_mark_is_read(self):
        code, out = self.run_quota(self.READING, config='﻿{"daily_percent": 20}')
        self.assertEqual((code, out['decision']), (0, 'go'))

    def test_a_broken_file_or_a_wrong_setting_is_a_usage_error(self):
        self.assertEqual(self.run_quota(self.READING, config='{not json')[0], 2)
        code, out = self.run_quota(self.READING, config='{"daily_percnt": 20}')
        self.assertEqual(code, 2)
        self.assertIn('daily_percnt', out['reason'])

    def test_a_time_that_does_not_parse_is_a_usage_error(self):
        code, out = self.run_quota(['--weekly-used', '5', '--weekly-resets', 'Thursday'])
        self.assertEqual(code, 2)
        self.assertIn('--weekly-resets', out['reason'])

    def test_no_reading_reports_unknown(self):
        code, out = self.run_quota([])
        self.assertEqual((code, out['decision'], out['unknown']), (0, 'go', True))


if __name__ == '__main__':
    unittest.main()
