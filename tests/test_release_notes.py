#!/usr/bin/env python3
"""Release notes written at Done (#345).

`post-merge --notes` writes the `User release notes` and `Internal release
notes` fields in the same mutation that sets `Stage` to Done, for the issues
the PR closes and nothing else. `Shipped in version` is known by name and
never written.
"""

import json
import os
import sys
import tempfile
import unittest
from unittest import mock

sys.path.insert(
    0,
    os.path.join(os.path.dirname(__file__), '..', 'synergy', 'scripts'),
)
sys.path.insert(0, os.path.dirname(__file__))
import wf  # noqa: E402
import wf_core  # noqa: E402
from test_decision_logic import _FIELD_MAP, _TYPE_MAP, _entry  # noqa: E402
from test_io_shell import _capture, _cfg, _settle_graphql  # noqa: E402

_NOTE_FIELDS = {
    'User release notes': {'id': 'F_user', 'data_type': 'text', 'options': {}},
    'Internal release notes': {'id': 'F_int', 'data_type': 'text', 'options': {}},
    'Shipped in version': {'id': 'F_ver', 'data_type': 'text', 'options': {}},
}


class TestReleaseNoteFields(unittest.TestCase):

    def test_all_three_fields_are_mapped_so_preflight_does_not_flag_them(self):
        names = ['User release notes', 'Internal release notes', 'Shipped in version']
        self.assertEqual(wf_core.unmapped_field_findings(names), [])

    def test_none_of_them_is_required_or_reported_missing(self):
        """An open issue has shipped nothing yet, so a blank one is not a gap."""
        for key in ('field-user-release-notes', 'field-internal-release-notes',
                    'field-shipped-version'):
            self.assertNotIn(key, wf_core.MANDATORY_FIELD_KEYS)
            self.assertNotIn(key, wf_core.OPTIONAL_FIELD_KEYS)

    def test_shipped_in_version_is_never_a_release_note_the_workflow_writes(self):
        self.assertNotIn('field-shipped-version',
                         wf_core.RELEASE_NOTE_FIELD_KEYS.values())
        self.assertIn('field-shipped-version', wf_core.NEVER_WRITTEN_FIELD_KEYS)

    def test_a_spec_that_sets_shipped_in_version_is_refused(self):
        entry = _entry(fields=dict(_entry()['fields'],
                                   **{'field-shipped-version': '1.2.0'}))
        field_map = dict(_FIELD_MAP, **_NOTE_FIELDS)
        errors, _, plans = wf_core.validate_spec([entry], field_map, _TYPE_MAP)
        self.assertEqual(len(errors), 1)
        self.assertIn('Shipped in version', errors[0])
        self.assertNotIn('Shipped in version', plans[0]['fields'])


class TestParseReleaseNotes(unittest.TestCase):

    def test_both_texts_are_kept_per_issue(self):
        notes, errors = wf_core.parse_release_notes(
            {'5': {'user': 'Settings\n* A thing.', 'internal': '* Refactored.'}})
        self.assertEqual(errors, [])
        self.assertEqual(notes, {5: {'user': 'Settings\n* A thing.',
                                     'internal': '* Refactored.'}})

    def test_a_blank_or_none_text_is_left_out_so_the_field_stays_blank(self):
        notes, _ = wf_core.parse_release_notes(
            {'#6': {'user': '  ', 'internal': '* Cleaned up tests.'},
             '7': {'user': 'None.', 'internal': ''}})
        self.assertEqual(notes, {6: {'internal': '* Cleaned up tests.'}, 7: {}})

    def test_a_bad_key_or_entry_is_an_error_and_the_rest_still_apply(self):
        notes, errors = wf_core.parse_release_notes(
            {'x': {'user': 'a'}, '8': 'text', '9': {'internal': '* b'}})
        self.assertEqual(notes, {9: {'internal': '* b'}})
        self.assertEqual(len(errors), 2)

    def test_a_version_in_the_file_is_ignored_and_said_so(self):
        notes, errors = wf_core.parse_release_notes(
            {'5': {'internal': '* b', 'version': '1.2.0'}})
        self.assertEqual(notes, {5: {'internal': '* b'}})
        self.assertIn('version', errors[0])


class TestPostMergeWritesReleaseNotes(unittest.TestCase):

    def setUp(self):
        fd, self.path = tempfile.mkstemp(suffix='.json')
        os.close(fd)
        self.addCleanup(os.remove, self.path)

    def _post_merge(self, notes, field_map=None, fail_combined=False):
        with open(self.path, 'w', encoding='utf-8') as fh:
            json.dump(notes, fh)
        calls = []
        caps = {'field_map': _NOTE_FIELDS if field_map is None else field_map}

        def set_stages(cfg, wanted, ids=None, extra=None):
            calls.append((dict(wanted), dict(extra or {})))
            if fail_combined and extra:
                return {int(n): (n not in extra, 'text refused') for n in wanted}
            return {int(n): (True, 'Stage set to Done') for n in wanted}

        def fake_run(argv, input_text=None):
            if argv[:3] == ['gh', 'pr', 'view']:
                return 0, json.dumps({
                    'number': 50, 'state': 'MERGED',
                    'mergedAt': '2026-09-19T00:00:00Z', 'baseRefName': 'main',
                    'closingIssuesReferences': [{'number': 5}]}), ''
            return _settle_graphql(argv, input_text) or (0, '', '')

        args = wf.build_parser().parse_args(
            ['post-merge', '--pr', '50', '--no-unblock', '--notes', self.path])
        with mock.patch.object(wf, 'check_environment', return_value=None), \
                mock.patch.object(wf, 'load_config', return_value=(True, _cfg(), '')), \
                mock.patch.object(wf, 'resolve_org_capabilities',
                                  return_value=(True, caps, '')), \
                mock.patch.object(wf, 'set_stages', set_stages), \
                mock.patch.object(wf, 'close_finished_ancestors',
                                  return_value=([], [])), \
                mock.patch.object(wf, 'run', side_effect=fake_run):
            code, payload = _capture(args.func, args)
        return code, payload, calls

    def test_both_texts_ride_in_the_done_write(self):
        code, payload, calls = self._post_merge(
            {'5': {'user': 'Settings\n* A thing.', 'internal': '* Refactored.'}})
        self.assertEqual(code, wf.EXIT_OK)
        self.assertEqual(len(calls), 1)
        wanted, extra = calls[0]
        self.assertEqual(wanted, {5: 'Done'})
        self.assertEqual(extra[5], [
            {'fieldId': 'F_user', 'textValue': 'Settings\n* A thing.'},
            {'fieldId': 'F_int', 'textValue': '* Refactored.'}])
        self.assertEqual(payload['release_notes'],
                         {'5': ['User release notes', 'Internal release notes']})

    def test_a_chore_writes_internal_notes_and_leaves_user_notes_blank(self):
        _, _, calls = self._post_merge({'5': {'user': 'None.',
                                              'internal': '* Cleaned up.'}})
        self.assertEqual(calls[0][1][5], [{'fieldId': 'F_int',
                                           'textValue': '* Cleaned up.'}])

    def test_shipped_in_version_is_never_written(self):
        _, _, calls = self._post_merge({'5': {'user': 'A\n* b', 'internal': '* c',
                                              'version': '1.2.0'}})
        ids = [i['fieldId'] for i in calls[0][1][5]]
        self.assertNotIn('F_ver', ids)

    def test_a_note_for_an_issue_the_pr_does_not_close_is_not_written(self):
        """Only issues closed by their own PR: a container, or anything else
        named in the file, gets nothing."""
        _, _, calls = self._post_merge({'10': {'user': 'A\n* b'}})
        self.assertEqual(calls[0][1], {})

    def test_an_org_without_the_fields_settles_exactly_as_before(self):
        code, payload, calls = self._post_merge(
            {'5': {'user': 'A\n* b', 'internal': '* c'}}, field_map={})
        self.assertEqual(code, wf.EXIT_OK)
        self.assertEqual(calls, [({5: 'Done'}, {})])
        self.assertEqual(payload['settled'], [5])
        self.assertNotIn('release_notes', payload)

    def test_a_refused_text_still_lets_the_issue_reach_done(self):
        code, payload, calls = self._post_merge(
            {'5': {'user': 'A\n* b'}}, fail_combined=True)
        self.assertEqual(code, wf.EXIT_OK)
        self.assertEqual(calls[1], ({5: 'Done'}, {}))
        entry = payload['settled'][0]
        self.assertTrue(entry['stage_set'])
        self.assertEqual(entry['release_notes']['written'], [])
        self.assertEqual(entry['release_notes']['error'], 'text refused')

    def test_no_notes_file_is_no_notes(self):
        notes, errors = wf.read_release_notes(None)
        self.assertEqual((notes, errors), ({}, []))


if __name__ == '__main__':
    unittest.main()
