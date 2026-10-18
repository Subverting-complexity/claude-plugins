#!/usr/bin/env python3
"""Area values in a spec's `field-type` (issue #282 follow-up).

An area says which part of the system the work touches, never what kind of
change it is, so a spec may not file an issue carrying areas alone, and an org
whose Classification field has no area options still files issues as before.
"""
import os
import sys
import unittest

sys.path.insert(
    0,
    os.path.join(os.path.dirname(__file__), '..', 'synergy', 'scripts'),
)
from wf_core_spec import validate_spec  # noqa: E402

KINDS = {'New Feature': 'o_nf', 'Bug Fix': 'o_bf'}
AREAS = {'Front end': 'o_fe', 'Back end': 'o_be'}


def field_map(classification_options):
    fields = {
        'Priority': {'id': 'F_pri', 'data_type': 'single-select',
                     'options': {'High': 'o_hi'}},
        'Effort': {'id': 'F_eff', 'data_type': 'single-select',
                   'options': {'Medium': 'o_med'}},
        'Ownership': {'id': 'F_own', 'data_type': 'single-select',
                      'options': {'Code agent': 'o_code'}},
    }
    if classification_options is not None:
        fields['Classification'] = {'id': 'F_cls', 'data_type': 'multi-select',
                                    'options': dict(classification_options)}
    return fields


WITH_AREAS = field_map(dict(KINDS, **AREAS))
WITHOUT_AREAS = field_map(KINDS)
TYPES = {'User Story': 'IT_story', 'Bug': 'IT_bug'}


def entry(field_type, **over):
    e = {'key': 'a', 'title': 'A story', 'kind': 'story',
         'fields': {'field-priority': 'High', 'field-effort': 'Medium',
                    'field-ownership': 'Code agent', 'field-type': field_type}}
    e.update(over)
    return e


def classification(plan):
    return plan['fields']['Classification']['value']


class TestAreaOnlyValues(unittest.TestCase):
    def test_areas_alone_gain_the_kinds_default_value(self):
        errors, _, plans = validate_spec([entry(['Front end'])], WITH_AREAS, TYPES)
        self.assertEqual(errors, [])
        self.assertEqual(classification(plans[0]), ['New Feature', 'Front end'])
        self.assertEqual(plans[0]['fields']['Classification']['input'],
                         {'fieldId': 'F_cls', 'multiSelectOptionIds': ['o_nf', 'o_fe']})
        self.assertEqual(len(plans[0]['notes']), 1)
        self.assertIn("'New Feature'", plans[0]['notes'][0])

    def test_a_bug_gains_its_own_default(self):
        errors, _, plans = validate_spec(
            [entry('Back end', kind='bug', title='Bug')], WITH_AREAS, TYPES)
        self.assertEqual(errors, [])
        self.assertEqual(classification(plans[0]), ['Bug Fix', 'Back end'])

    def test_areas_alone_without_a_kind_are_refused(self):
        bare = entry(['Front end', 'Back end'])
        del bare['kind']
        errors, _, _ = validate_spec([bare], WITH_AREAS, TYPES)
        self.assertEqual(len(errors), 1)
        self.assertIn('only areas', errors[0])
        self.assertIn('Front end, Back end', errors[0])

    def test_a_kind_value_beside_areas_is_written_unchanged(self):
        errors, _, plans = validate_spec(
            [entry(['Bug Fix', 'Front end'])], WITH_AREAS, TYPES)
        self.assertEqual(errors, [])
        self.assertEqual(classification(plans[0]), ['Bug Fix', 'Front end'])
        self.assertEqual(plans[0]['notes'], [])


class TestOrgWithoutAreaOptions(unittest.TestCase):
    def test_an_undefined_area_is_dropped_with_a_note(self):
        errors, _, plans = validate_spec(
            [entry(['Bug Fix', 'Front end'])], WITHOUT_AREAS, TYPES)
        self.assertEqual(errors, [])
        self.assertEqual(classification(plans[0]), ['Bug Fix'])
        self.assertEqual(len(plans[0]['notes']), 1)
        self.assertIn("dropped 'Front end'", plans[0]['notes'][0])

    def test_areas_alone_fall_back_to_the_kinds_default(self):
        errors, _, plans = validate_spec(
            [entry(['Front end', 'Back end'])], WITHOUT_AREAS, TYPES)
        self.assertEqual(errors, [])
        self.assertEqual(classification(plans[0]), ['New Feature'])
        self.assertEqual(len(plans[0]['notes']), 2)

    def test_an_unknown_kind_of_change_value_is_still_refused(self):
        errors, _, _ = validate_spec(
            [entry(['Nonsense', 'Front end'])], WITHOUT_AREAS, TYPES)
        self.assertEqual(len(errors), 1)
        self.assertIn("'Nonsense' is not an option", errors[0])

    def test_an_org_with_no_classification_field_skips_it(self):
        bare = entry(['Front end'])
        del bare['kind']
        errors, skipped, plans = validate_spec([bare], field_map(None), TYPES)
        self.assertEqual(errors, [])
        self.assertIn('Classification', skipped)
        self.assertEqual(plans[0]['notes'], [])


if __name__ == '__main__':
    unittest.main()
