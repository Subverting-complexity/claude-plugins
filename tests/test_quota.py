#!/usr/bin/env python3
"""
Tests for `wf quota`, which tells a long run whether it may start another round
without going past the Claude plan limits.

The rules are pure: a reading, the settings and a time go in, and `go`, `wait`
or `stop` comes out. Nothing here reads real usage or the clock, and the two
personal files are pointed at a temporary directory. The rule that matters most
is the daily budget: what was left of the week when the day started, divided by
the days left, times the share a run may use.

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

    def test_the_defaults(self):
        settings, errors = wf_core.quota_settings()
        self.assertEqual(errors, [])
        self.assertEqual(settings['daily_share'], 100.0)
        self.assertEqual(settings['on_limit'], 'stop')
        self.assertEqual(settings['on_unknown'], 'continue')

    def test_a_later_layer_overrides_an_earlier_one_and_none_is_skipped(self):
        settings, errors = wf_core.quota_settings(
            {'weekly_ceiling': 70, 'daily_share': 50}, {'weekly_ceiling': 60, 'daily_share': None})
        self.assertEqual(errors, [])
        self.assertEqual(settings['weekly_ceiling'], 60.0)
        self.assertEqual(settings['daily_share'], 50.0)

    def test_no_file_is_the_same_as_no_settings(self):
        self.assertEqual(wf_core.quota_settings(None, None)[0], wf_core.QUOTA_DEFAULTS)

    def test_wrong_values_are_named(self):
        _, errors = wf_core.quota_settings({'weekly_ceiling': 140, 'on_limit': 'pause',
                                            'daily_share': '50', 'days': 5, 'max_wait_hours': -1})
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


class TestDayBudget(unittest.TestCase):

    def test_an_unused_week_gives_one_seventh_on_day_1(self):
        self.assertAlmostEqual(wf_core.quota_day_budget(0, 1, 100), 100 / 7)

    def test_the_leftover_is_spread_over_the_days_left(self):
        # 30% used after 3 days leaves 70% for 4 days: 17.5% a day.
        self.assertAlmostEqual(wf_core.quota_day_budget(30, 4, 100), 17.5)

    def test_the_share_takes_a_part_of_it(self):
        self.assertAlmostEqual(wf_core.quota_day_budget(30, 4, 40), 7.0)

    def test_the_last_day_gets_all_that_is_left(self):
        self.assertAlmostEqual(wf_core.quota_day_budget(80, 7, 100), 20.0)

    def test_a_used_up_week_gives_nothing(self):
        self.assertEqual(wf_core.quota_day_budget(100, 5, 100), 0.0)


class TestDecision(unittest.TestCase):

    def test_low_usage_goes(self):
        result = decide(at(3, 4), weekly=30, day_start_used=30)
        self.assertEqual(result['decision'], 'go')
        self.assertTrue(all(c['ok'] for c in result['checks']))
        self.assertEqual(result['week']['day'], 4)
        self.assertEqual(result['week']['days_left'], 4)
        self.assertEqual(result['week']['day_budget'], 17.5)
        self.assertEqual(result['week']['used_today'], 0.0)

    def test_the_daily_budget_stops_a_day_that_used_its_part(self):
        # The day started at 30% with a 17.5% budget. 16% used today plus a 3%
        # round is above it, though far below the 90% weekly ceiling.
        result = decide(at(3, 4), weekly=46, day_start_used=30)
        self.assertEqual(result['decision'], 'stop')
        self.assertFalse(check(result, 'daily')['ok'])
        self.assertTrue(check(result, 'weekly')['ok'])
        self.assertEqual(check(result, 'daily')['used'], 16.0)
        self.assertIn('Day 4 of the week', result['reason'])
        # Day 5 starts a new budget: 54% left over 3 days.
        self.assertEqual(result['resume_at'], '2026-10-05T00:00:00Z')

    def test_a_smaller_share_stops_sooner(self):
        # 40% of 17.5% is 7%. 5% used today plus 3% is above it.
        self.assertEqual(decide(at(3, 4), weekly=35, day_start_used=30)['decision'], 'go')
        result = decide(at(3, 4), weekly=35, day_start_used=30, settings={'daily_share': 40})
        self.assertEqual(result['decision'], 'stop')
        self.assertEqual(check(result, 'daily')['limit'], 7.0)

    def test_a_heavy_day_makes_the_next_budget_smaller(self):
        light = decide(at(4), weekly=30, day_start_used=30)['week']['day_budget']
        heavy = decide(at(4), weekly=60, day_start_used=60)['week']['day_budget']
        self.assertEqual((light, heavy), (23.3, 13.3))

    def test_with_no_stored_start_the_day_starts_at_the_reading(self):
        result = decide(at(3, 4), weekly=46)
        self.assertEqual(result['week']['day_start_used'], 46.0)
        self.assertEqual(result['week']['used_today'], 0.0)

    def test_a_stored_start_above_the_reading_is_ignored(self):
        self.assertEqual(decide(at(3), weekly=10, day_start_used=40)['week']['day_start_used'], 10.0)

    def test_the_resume_day_is_the_first_whose_budget_covers_a_round(self):
        # With a 3% share and 10% left, day 6 gets 0.15% and day 7 gets 0.3%:
        # no day of this week covers a 3% round, so the run resumes at the reset.
        result = decide(at(4, 1), weekly=90, day_start_used=90,
                        settings={'daily_share': 3, 'weekly_ceiling': 100})
        self.assertEqual(result['resume_at'], '2026-10-08T00:00:00Z')

    def test_the_five_hour_ceiling_stops_and_names_the_reset(self):
        result = decide(at(1, 4), five=75, five_resets=at(1, 6))
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
        result = decide(at(3, 4), weekly=46, day_start_used=30, settings={'on_limit': 'wait'})
        self.assertEqual(result['decision'], 'stop')
        self.assertIn('longer than max_wait_hours', result['reason'])
        longer = decide(at(3, 4), weekly=46, day_start_used=30,
                        settings={'on_limit': 'wait', 'max_wait_hours': 24})
        self.assertEqual(longer['decision'], 'wait')

    def test_two_failed_checks_wait_for_the_later_one(self):
        result = decide(at(3, 22), five=80, weekly=46, day_start_used=30, five_resets=at(3, 23),
                        settings={'on_limit': 'wait'})
        self.assertEqual(result['resume_at'], '2026-10-05T00:00:00Z')

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

    def setUp(self):
        tmp = tempfile.TemporaryDirectory()
        self.addCleanup(tmp.cleanup)
        self.config = os.path.join(tmp.name, 'synergy', 'quota.json')
        self.state = os.path.join(tmp.name, 'synergy', 'quota-state.json')
        env = mock.patch.dict(os.environ, {wf_quota.QUOTA_CONFIG_ENV: self.config})
        env.start()
        self.addCleanup(env.stop)
        os.environ.pop(wf_quota.QUOTA_STATE_ENV, None)

    def write_config(self, text):
        os.makedirs(os.path.dirname(self.config), exist_ok=True)
        with open(self.config, 'w', encoding='utf-8') as fh:
            fh.write(text)

    def run_quota(self, argv):
        """Run `wf quota`. Returns (exit_code, parsed stdout)."""
        buf = io.StringIO()
        with redirect_stdout(buf):
            try:
                wf.main(['quota'] + argv)
                code = 0
            except SystemExit as exc:
                code = exc.code
        return code, json.loads(buf.getvalue())

    def reading(self, weekly, now='2026-10-04T04:00:00Z'):
        return ['--now', now, '--five-hour-used', '10', '--five-hour-resets', '2026-10-04T06:00:00Z',
                '--weekly-used', str(weekly), '--weekly-resets', '2026-10-08T00:00:00Z']

    def test_the_defaults_apply_with_no_file_and_it_is_not_configured(self):
        code, out = self.run_quota(self.reading(30))
        self.assertEqual((code, out['decision'], out['configured']), (0, 'go', False))
        self.assertIsNone(out['settings_file'])
        self.assertEqual(out['week']['day_budget'], 17.5)

    def test_the_first_check_of_a_day_stores_the_start_and_later_checks_use_it(self):
        self.run_quota(self.reading(30))
        code, out = self.run_quota(self.reading(46, now='2026-10-04T09:00:00Z'))
        self.assertEqual(out['week']['day_start_used'], 30.0)
        self.assertEqual(out['week']['used_today'], 16.0)
        self.assertEqual(out['decision'], 'stop')

    def test_a_new_day_stores_a_new_start(self):
        self.run_quota(self.reading(30))
        code, out = self.run_quota(self.reading(46, now='2026-10-05T01:00:00Z'))
        self.assertEqual(out['week']['day'], 5)
        self.assertEqual(out['week']['day_start_used'], 46.0)
        self.assertEqual(out['decision'], 'go')

    def test_a_new_week_does_not_use_the_old_start(self):
        self.run_quota(self.reading(30))
        code, out = self.run_quota(['--now', '2026-10-11T04:00:00Z', '--weekly-used', '31',
                                    '--weekly-resets', '2026-10-15T00:00:00Z'])
        self.assertEqual(out['week']['day_start_used'], 31.0)

    def test_the_reset_time_may_move_by_a_fraction_of_a_second(self):
        self.run_quota(self.reading(30))
        argv = self.reading(40)
        argv[-1] = '2026-10-07T23:59:59.702Z'
        self.assertEqual(self.run_quota(argv)[1]['week']['day_start_used'], 30.0)

    def test_no_record_stores_nothing(self):
        self.run_quota(self.reading(30) + ['--no-record'])
        self.assertFalse(os.path.exists(self.state))

    def test_save_with_no_flag_records_that_the_defaults_were_chosen(self):
        code, out = self.run_quota(['--save'])
        self.assertEqual((code, out['saved'], out['configured']), (0, {}, True))
        code, out = self.run_quota(self.reading(30))
        self.assertTrue(out['configured'])
        self.assertEqual(out['settings']['daily_share'], 100.0)

    def test_save_writes_the_flags_and_keeps_what_the_file_had(self):
        self.write_config('{"on_limit": "wait"}')
        code, out = self.run_quota(['--save', '--daily-share', '40'])
        self.assertEqual(out['saved'], {'on_limit': 'wait', 'daily_share': 40.0})
        code, out = self.run_quota(self.reading(30))
        self.assertEqual(out['week']['day_budget'], 7.0)
        self.assertEqual(out['settings']['on_limit'], 'wait')

    def test_save_refuses_a_wrong_value_and_writes_nothing(self):
        code, out = self.run_quota(['--save', '--daily-share', '140'])
        self.assertEqual(code, 2)
        self.assertFalse(os.path.exists(self.config))

    def test_a_flag_overrides_the_personal_file(self):
        self.write_config('{"daily_share": 40}')
        code, out = self.run_quota(self.reading(30) + ['--daily-share', '100'])
        self.assertEqual(out['week']['day_budget'], 17.5)

    def test_a_file_with_a_byte_order_mark_is_read(self):
        self.write_config('﻿{"daily_share": 40}')
        code, out = self.run_quota(self.reading(30))
        self.assertEqual((code, out['week']['day_budget']), (0, 7.0))

    def test_a_broken_file_or_a_wrong_setting_is_a_usage_error(self):
        self.write_config('{not json')
        self.assertEqual(self.run_quota(self.reading(30))[0], 2)
        self.write_config('{"daily_shar": 20}')
        code, out = self.run_quota(self.reading(30))
        self.assertEqual(code, 2)
        self.assertIn('daily_shar', out['reason'])

    def test_a_time_that_does_not_parse_is_a_usage_error(self):
        code, out = self.run_quota(['--weekly-used', '5', '--weekly-resets', 'Thursday'])
        self.assertEqual(code, 2)
        self.assertIn('--weekly-resets', out['reason'])

    def test_no_reading_reports_unknown(self):
        code, out = self.run_quota([])
        self.assertEqual((code, out['decision'], out['unknown']), (0, 'go', True))


if __name__ == '__main__':
    unittest.main()
