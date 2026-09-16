#!/usr/bin/env python3
"""
Every `wf_*.py` shell module is listed in `wf._SHELL_MODULES`.

That list is what `wf` re-exports and what an assignment to `wf.X` is passed
on to, so it is the seam every `mock.patch.object(wf, ...)` in the offline
suite relies on. A shell module missing from it still imports and still runs,
but a patch through `wf` no longer reaches the names it binds: a test then
patches nothing and passes anyway. Splitting a module is exactly when one is
missed, so this checks the directory rather than any one split.

Run standalone (`python3 tests/test_shell_modules.py`) or via `run-tests.sh`.
"""

import glob
import os
import sys
import unittest

HERE = os.path.dirname(os.path.abspath(__file__))
SCRIPTS = os.path.normpath(os.path.join(HERE, '..', 'synergy', 'scripts'))
sys.path.insert(0, SCRIPTS)

import wf  # noqa: E402


def shell_module_names():
    """`wf_*.py` in the scripts directory, less the `wf_core*` rules, which
    have their own facade and are never patched through `wf`."""
    names = set()
    for path in glob.glob(os.path.join(SCRIPTS, 'wf_*.py')):
        name = os.path.splitext(os.path.basename(path))[0]
        if name == 'wf_core' or name.startswith('wf_core_'):
            continue
        names.add(name)
    return names


class TestShellModulesAreListed(unittest.TestCase):

    def test_every_shell_module_is_in_shell_modules(self):
        listed = {module.__name__ for module in wf._SHELL_MODULES}
        missing = sorted(shell_module_names() - listed)
        self.assertEqual(missing, [], 'add these to _SHELL_MODULES in wf.py, or a '
                                      'patch through wf will not reach them')

    def test_the_directory_scan_finds_the_pick_modules(self):
        # Guards the scan itself: an empty glob would make the check above
        # pass for every layout.
        self.assertTrue({'wf_pick', 'wf_pick_tree', 'wf_pick_select',
                         'wf_pick_candidates'} <= shell_module_names())

    def test_a_patch_through_wf_reaches_a_split_module(self):
        original = wf.fetch_container_tree
        sentinel = object()
        wf.fetch_container_tree = sentinel
        try:
            import wf_pick_candidates
            import wf_plan
            self.assertIs(wf_pick_candidates.fetch_container_tree, sentinel)
            self.assertIs(wf_plan.fetch_container_tree, sentinel)
        finally:
            wf.fetch_container_tree = original
        self.assertIs(wf_plan.fetch_container_tree, original)


if __name__ == '__main__':
    unittest.main()
