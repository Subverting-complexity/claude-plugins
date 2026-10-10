#!/usr/bin/env python3
"""
Tests for the areas table, the release-targets table and the Jev row that
`wf_config` reads from `ClaudeProject.md`.

The tables are the one list of area and release labels a repository has, so a
row that cannot become a label is refused here, where the file is read, and
not later, where the label would silently be missing. A configuration cache
written before the tables existed carries none of their keys and must not be
believed.

Run standalone (`python3 tests/test_config_tables.py`) or via `run-tests.sh`.
"""

import json
import os
import sys
import tempfile
import time
import unittest
from unittest import mock

sys.path.insert(0, os.path.join(os.path.dirname(os.path.abspath(__file__)), '..', 'synergy', 'scripts'))

import wf_config  # noqa: E402
from wf_config import ConfigError, parse_claude_project  # noqa: E402

IDENTITY = '# P\n\n## Identity\n\n| Setting | Value |\n| --- | --- |\n| org | acme |\n| repo | shop |\n\n'

BOTH = IDENTITY + (
    '## Areas\n\n'
    '| Name | Description | Colour | Epic | Was |\n'
    '| ---- | ----------- | ------ | ---- | --- |\n'
    '| `checkout` | Basket, payment and the order \\| receipt pages | `#0E8A16` | #12 | `cart` |\n'
    '| reader | Runs `cat a | sort` for the reader | 1d76db | | |\n'
    '\n'
    '## Release Targets\n\n'
    '| Name | Description | Colour |\n'
    '| ---- | ----------- | ------ |\n'
    '| mobile | The iOS and Android apps | fbca04 |\n'
    '| web | The site | c5def5 |\n'
    '\n'
    '## Jev\n\n'
    '| Setting | Value |\n| --- | --- |\n| jev | `off` |\n'
)


def areas_table(*rows):
    return IDENTITY + '## Areas\n\n| Name | Description | Colour |\n| --- | --- | --- |\n' + ''.join(rows)


class TableTests(unittest.TestCase):

    def test_both_tables_are_read_in_order(self):
        cfg = parse_claude_project(BOTH)
        self.assertEqual([a['name'] for a in cfg['areas']], ['checkout', 'reader'])
        self.assertEqual(cfg['release_targets'], [
            {'name': 'mobile', 'description': 'The iOS and Android apps', 'colour': 'fbca04'},
            {'name': 'web', 'description': 'The site', 'colour': 'c5def5'},
        ])

    def test_an_escaped_pipe_stays_in_the_description(self):
        area = parse_claude_project(BOTH)['areas'][0]
        self.assertEqual(area['description'], 'Basket, payment and the order | receipt pages')
        self.assertEqual((area['colour'], area['epic'], area['was']), ('0e8a16', 12, 'cart'))

    def test_a_pipe_in_a_code_span_stays_in_the_description(self):
        area = parse_claude_project(BOTH)['areas'][1]
        self.assertEqual(area['description'], 'Runs `cat a | sort` for the reader')
        self.assertEqual((area['colour'], area['epic'], area['was']), ('1d76db', None, None))

    def test_a_file_with_neither_table_loads_with_empty_lists(self):
        cfg = parse_claude_project(IDENTITY)
        self.assertEqual((cfg['areas'], cfg['release_targets'], cfg['jev']), ([], [], 'on'))
        self.assertEqual(cfg['org'], 'acme')

    def test_optional_columns_may_be_left_out(self):
        cfg = parse_claude_project(areas_table('| docs | The guides | ffffff |\n'))
        self.assertEqual(cfg['areas'], [{'name': 'docs', 'description': 'The guides',
                                         'colour': 'ffffff', 'epic': None, 'was': None}])

    def test_a_template_placeholder_row_is_no_row(self):
        cfg = parse_claude_project(areas_table('| `{area-name}` | {one sentence} | `{rrggbb}` |\n'))
        self.assertEqual(cfg['areas'], [])

    def test_a_description_of_100_characters_is_accepted(self):
        cfg = parse_claude_project(areas_table('| docs | %s | ffffff |\n' % ('x' * 100)))
        self.assertEqual(len(cfg['areas'][0]['description']), 100)

    def test_a_description_over_100_characters_is_refused(self):
        with self.assertRaises(ConfigError) as caught:
            parse_claude_project(areas_table('| docs | %s | ffffff |\n' % ('x' * 101)))
        self.assertIn('docs', str(caught.exception))
        self.assertIn('101', str(caught.exception))

    def test_a_name_that_appears_twice_is_refused(self):
        with self.assertRaises(ConfigError) as caught:
            parse_claude_project(areas_table('| docs | One | ffffff |\n', '| Docs | Two | 000000 |\n'))
        self.assertIn('more than once', str(caught.exception))

    def test_a_release_target_is_held_to_the_same_limits(self):
        text = IDENTITY + ('## Release Targets\n\n| Name | Description | Colour |\n| --- | --- | --- |\n'
                           '| web | %s | ffffff |\n' % ('x' * 101))
        with self.assertRaises(ConfigError):
            parse_claude_project(text)

    def test_other_tables_still_lose_their_backticks(self):
        cfg = parse_claude_project('## Identity\n\n| org | `acme` |\n| repo | `shop` |\n')
        self.assertEqual((cfg['org'], cfg['repo']), ('acme', 'shop'))


class JevRowTests(unittest.TestCase):

    def test_off_is_read(self):
        self.assertEqual(parse_claude_project(BOTH)['jev'], 'off')

    def test_on_is_the_default_and_the_reading_of_any_other_value(self):
        for value in ('on', 'ON', 'yes', ''):
            text = IDENTITY + '## Jev\n\n| Setting | Value |\n| --- | --- |\n| jev | %s |\n' % value
            self.assertEqual(parse_claude_project(text)['jev'], 'on', value)


class LoadConfigTests(unittest.TestCase):

    def setUp(self):
        self._tmp = tempfile.TemporaryDirectory()
        self.root = self._tmp.name
        self.addCleanup(self._tmp.cleanup)
        os.makedirs(os.path.join(self.root, '.claude'))
        patcher = mock.patch.object(wf_config, 'repo_root', lambda: self.root)
        patcher.start()
        self.addCleanup(patcher.stop)

    def write_source(self, text):
        path = os.path.join(self.root, 'ClaudeProject.md')
        with open(path, 'w', encoding='utf-8') as fh:
            fh.write(text)
        old = time.time() - 600
        os.utime(path, (old, old))

    def write_cache(self, cfg):
        with open(os.path.join(self.root, '.claude', 'wf-config.json'), 'w', encoding='utf-8') as fh:
            json.dump(cfg, fh)

    def test_a_cache_from_the_previous_version_is_rebuilt_not_read(self):
        self.write_source(BOTH)
        self.write_cache({'org': 'stale', 'repo': 'stale', 'labels': {}, 'review_labels': {}})
        ok, cfg, _ = wf_config.load_config()
        self.assertTrue(ok)
        self.assertEqual(cfg['org'], 'acme')
        self.assertEqual([a['name'] for a in cfg['areas']], ['checkout', 'reader'])

    def test_a_cache_with_the_keys_is_read(self):
        self.write_source(BOTH)
        self.write_cache({'org': 'cached', 'repo': 'shop', 'areas': [], 'release_targets': [],
                          'jev': 'on'})
        ok, cfg, _ = wf_config.load_config()
        self.assertTrue(ok)
        self.assertEqual(cfg['org'], 'cached')

    def test_a_refused_row_is_an_error_that_names_it(self):
        self.write_source(areas_table('| docs | %s | ffffff |\n' % ('x' * 101)))
        ok, cfg, err = wf_config.load_config()
        self.assertFalse(ok)
        self.assertIsNone(cfg)
        self.assertIn('ClaudeProject.md', err)
        self.assertIn('docs', err)


if __name__ == '__main__':
    unittest.main()
