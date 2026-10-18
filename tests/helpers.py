#!/usr/bin/env python3
"""
Shared test plumbing for the `wf` CLI test suite.

`tests/test_io_shell.py` drives `wf`'s command entry points through the
seams `wf.py` exposes for exactly this purpose (`check_environment`,
`load_issue_facets`, `claimed_issue_numbers`, `load_config`), rather than
hitting GitHub. Nearly every command checks the same three seams —
environment, issue facets, claimed numbers — before it does anything else,
so most test classes patched the same three to the same permissive
defaults and then redefined an identical `_use_cfg` helper for the fourth.
`WfCommandTestCase` holds that pattern once so a test class only states
what makes it different: which config it needs, and what it overrides for
one test.

Not every test class in the suite needs this — plenty stub a temp
directory, a local git repo, or nothing at all — so inheriting from
`WfCommandTestCase` is opt-in per class, not a blanket base for every test.
"""
import os
import sys
import unittest
from unittest import mock

# Import the I/O shell itself, the same way every `tests/test_*.py` module
# does, so `WfCommandTestCase` can patch its seams directly.
sys.path.insert(
    0,
    os.path.join(os.path.dirname(__file__), '..', 'synergy', 'scripts'),
)
import wf  # noqa: E402


# Sentinel for a keyword whose default is a value, so `None` stays meaningful.
_UNSET = object()


class _CodeOwned(dict):
    """An `Ownership` map answering `Code agent` for any issue not named in it.

    Truthy even when empty, because the picker treats a falsy ownership map as
    "the org told us nothing" and empties the pool.

    The picker excludes anything it cannot confirm is code work, so a fixture
    saying nothing about ownership would empty every pool and every test would
    be asserting that filter rather than what it meant to assert. This is the
    ordinary state of a configured backlog: most issues are code work and the
    org has said so. Tests about ownership pass a real map.
    """

    def get(self, key, default=None):
        return dict.get(self, key, 'Code agent')

    def __bool__(self):
        return True


def facets(types=None, priority=None, classification=None, effort=None,
           ownership=_UNSET, stage=None):
    """The `load_issue_facets` return shape.

    `cmd_pick` and `cmd_candidates` read the org's native types and field
    values before selecting, so every test that drives them stubs this. The
    type, priority and classification maps are empty by default — that is the
    org-has-not-typed-this case, and it is a case the picker has to handle.
    Ownership is not: pass `ownership={}` for the org that defines no such
    field, which is a pool of nothing.
    """
    return {'types': types or {}, 'priority': priority or {},
            'classification': classification or {}, 'effort': effort or {},
            'stage': stage or {},
            'ownership': _CodeOwned() if ownership is _UNSET
            else (ownership or {})}


class WfCommandTestCase(unittest.TestCase):
    """Shared plumbing for tests that drive a `wf` command through its seams.

    `setUp` patches the three seams almost every command checks first —
    `check_environment`, `load_issue_facets`, `claimed_issue_numbers` — to
    permissive defaults, so a test only overrides what it is actually
    about. `_use_cfg` patches the fourth, `load_config`: it is a method
    rather than part of `setUp` because not every test class fixes its
    config for the whole class, and some vary it per test.
    """

    def setUp(self):
        super().setUp()
        for name, value in (
            ('check_environment', None),
            ('load_issue_facets', facets()),
            ('claimed_issue_numbers', set()),
        ):
            patch = mock.patch.object(wf, name, return_value=value)
            patch.start()
            self.addCleanup(patch.stop)

    def _use_cfg(self, cfg):
        """Patch `wf.load_config` to answer `cfg` for the rest of the test."""
        patch = mock.patch.object(wf, 'load_config', return_value=(True, cfg, ''))
        patch.start()
        self.addCleanup(patch.stop)
