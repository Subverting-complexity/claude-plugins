#!/usr/bin/env python3
"""Tests for wf_launch.py, the venv logic wf.sh and wf.ps1 share.

The unit tests stub out every child process. The end-to-end tests run each
launcher for real against a throwaway data dir, building a real venv, and are
skipped where that launcher's shell is not installed.
"""
import ast
import io
import os
import shutil
import subprocess
import sys
import tempfile
import unittest
from unittest import mock

SCRIPTS = os.path.join(os.path.dirname(os.path.dirname(os.path.abspath(__file__))), 'synergy', 'scripts')
sys.path.insert(0, SCRIPTS)

import wf_launch  # noqa: E402


class LaunchTestCase(unittest.TestCase):
    launcher = 'wf.sh'

    def setUp(self):
        self.root = tempfile.mkdtemp()
        self.addCleanup(shutil.rmtree, self.root, True)
        self.paths = wf_launch.Paths(self.root, self.launcher)
        self.stderr = io.StringIO()
        patcher = mock.patch.object(wf_launch, 'say', lambda m: self.stderr.write(m + '\n'))
        patcher.start()
        self.addCleanup(patcher.stop)

    def make_venv(self, ready=True):
        exe = wf_launch.venv_candidates(self.paths)[1 if os.name == 'nt' else 0]
        os.makedirs(os.path.dirname(exe))
        open(exe, 'w').close()
        if ready:
            open(self.paths.ready, 'w').close()
        return exe

    def read_cache(self):
        with open(self.paths.cache) as f:
            return f.read().splitlines()


class TestStdlibOnly(unittest.TestCase):
    def test_imports_nothing_outside_the_standard_library(self):
        with open(os.path.join(SCRIPTS, 'wf_launch.py')) as f:
            tree = ast.parse(f.read())
        names = set()
        for node in ast.walk(tree):
            if isinstance(node, ast.Import):
                names.update(a.name.split('.')[0] for a in node.names)
            elif isinstance(node, ast.ImportFrom):
                names.add((node.module or '').split('.')[0])
        self.assertLessEqual(names, {'os', 'shutil', 'subprocess', 'sys', 'time'})


class TestPaths(LaunchTestCase):
    def test_each_launcher_keeps_its_own_cache_file(self):
        self.assertEqual(os.path.basename(wf_launch.Paths(self.root, 'wf.sh').cache), 'wf-python')
        self.assertEqual(os.path.basename(wf_launch.Paths(self.root, 'wf.ps1').cache), 'wf-python-ps1')

    def test_cache_is_two_lines_kind_then_path(self):
        wf_launch.save_cache(self.paths, 'venv', '/x/python')
        self.assertEqual(self.read_cache(), ['venv', '/x/python'])
        wf_launch.remove_cache(self.paths)
        self.assertFalse(os.path.exists(self.paths.cache))


class TestLock(LaunchTestCase):
    def test_second_caller_waits_then_reclaims_an_abandoned_lock(self):
        self.assertTrue(wf_launch.acquire_lock(self.paths))
        sleeps = []
        self.assertTrue(wf_launch.acquire_lock(self.paths, timeout=3, sleep=sleeps.append))
        self.assertEqual(len(sleeps), 3)
        wf_launch.release_lock(self.paths)
        self.assertFalse(os.path.exists(self.paths.lock))

    def test_reclaim_that_loses_the_race_times_out(self):
        os.makedirs(self.paths.lock)
        with mock.patch.object(wf_launch, 'release_lock'):
            self.assertFalse(wf_launch.acquire_lock(self.paths, timeout=0, sleep=lambda s: None))


class TestResolve(LaunchTestCase):
    def test_a_venv_that_runs_wins_even_before_it_is_ready(self):
        exe = self.make_venv(ready=False)
        with mock.patch.object(wf_launch, 'runs', return_value=True):
            self.assertEqual(wf_launch.resolve(self.paths), ('venv', exe))
        self.assertEqual(self.read_cache(), ['venv', exe])

    def test_no_venv_builds_one_from_this_interpreter(self):
        built = os.path.join(self.root, 'built-python')
        with mock.patch.object(wf_launch, 'venv_python', return_value=None), \
                mock.patch.object(wf_launch, 'build_venv', return_value=(built, None)) as build:
            self.assertEqual(wf_launch.resolve(self.paths), ('venv', built))
        self.assertEqual(build.call_args[0][1], sys.executable)
        self.assertTrue(build.call_args[1]['quiet'])
        self.assertEqual(self.read_cache(), ['venv', built])
        self.assertFalse(os.path.exists(self.paths.lock))

    def test_failed_build_falls_back_to_system_python_with_a_warning(self):
        with mock.patch.object(wf_launch, 'venv_python', return_value=None), \
                mock.patch.object(wf_launch, 'build_venv', return_value=(None, ('no', 20))):
            self.assertEqual(wf_launch.resolve(self.paths), ('base', sys.executable))
        self.assertIn("Run 'wf.sh setup' to pin one", self.stderr.getvalue())
        self.assertEqual(self.read_cache(), ['base', sys.executable])

    def test_lock_timeout_falls_back_without_building(self):
        with mock.patch.object(wf_launch, 'venv_python', return_value=None), \
                mock.patch.object(wf_launch, 'acquire_lock', return_value=False), \
                mock.patch.object(wf_launch, 'build_venv') as build:
            self.assertEqual(wf_launch.resolve(self.paths)[0], 'base')
        build.assert_not_called()


class TestRunWf(unittest.TestCase):
    def test_passes_arguments_through(self):
        if os.name == 'nt':
            with mock.patch.object(wf_launch.subprocess, 'Popen') as popen:
                popen.return_value.wait.return_value = 11
                self.assertEqual(wf_launch.run_wf('py', ['pick', '--x']), 11)
            popen.assert_called_once_with(['py', wf_launch.WF, 'pick', '--x'])
        else:
            calls = []
            wf_launch.run_wf('py', ['pick'], execv=lambda p, a: calls.append((p, a)))
            self.assertEqual(calls, [('py', ['py', wf_launch.WF, 'pick'])])


class TestSetup(LaunchTestCase):
    def test_ready_venv_is_reused_and_cached(self):
        exe = self.make_venv()
        with mock.patch.object(wf_launch, 'runs', return_value=True), \
                mock.patch.object(wf_launch, 'version_text', return_value='Python 3.12'), \
                mock.patch.object(wf_launch, 'build_venv') as build:
            self.assertEqual(wf_launch.cmd_setup(self.paths, []), 0)
        build.assert_not_called()
        self.assertEqual(self.read_cache(), ['venv', exe])
        self.assertIn('already set up', self.stderr.getvalue())

    def test_force_rebuilds(self):
        self.make_venv()
        with mock.patch.object(wf_launch, 'runs', return_value=True), \
                mock.patch.object(wf_launch, 'version_text', return_value='Python 3.12'), \
                mock.patch.object(wf_launch, 'build_venv', return_value=('/v/python', None)) as build:
            self.assertEqual(wf_launch.cmd_setup(self.paths, ['--force']), 0)
        build.assert_called_once()
        self.assertFalse(os.path.exists(self.paths.venv))

    def test_failure_clears_the_cache_and_exits_with_its_code(self):
        wf_launch.save_cache(self.paths, 'base', '/old')
        with mock.patch.object(wf_launch, 'build_venv', return_value=(None, ('broke', 20))):
            self.assertEqual(wf_launch.cmd_setup(self.paths, []), 20)
        self.assertFalse(os.path.exists(self.paths.cache))
        self.assertFalse(os.path.exists(self.paths.lock))

    def test_ready_only_reports_a_ready_venv(self):
        self.make_venv()
        with mock.patch.object(wf_launch, 'runs', return_value=True),                 mock.patch.object(wf_launch, 'version_text', return_value='Python 3.12'),                 mock.patch.object(wf_launch, 'build_venv') as build:
            self.assertEqual(wf_launch.cmd_setup(self.paths, ['--ready-only']), 0)
        build.assert_not_called()

    def test_ready_only_never_builds(self):
        self.make_venv(ready=False)
        with mock.patch.object(wf_launch, 'runs', return_value=True),                 mock.patch.object(wf_launch, 'build_venv') as build:
            self.assertEqual(wf_launch.cmd_setup(self.paths, ['--ready-only']), wf_launch.EXIT_NOT_READY)
        build.assert_not_called()
        self.assertTrue(os.path.isdir(self.paths.venv))
        self.assertFalse(os.path.exists(self.paths.lock))

    def test_lock_timeout_exits_20(self):
        with mock.patch.object(wf_launch, 'acquire_lock', return_value=False):
            self.assertEqual(wf_launch.cmd_setup(self.paths, []), 20)
        self.assertIn('timed out', self.stderr.getvalue())


class TestPowerShellSetupFailure(LaunchTestCase):
    launcher = 'wf.ps1'

    def test_requirements_failure_exits_1(self):
        def call(argv, **kwargs):
            if argv[1:3] == ['-m', 'venv']:
                self.make_venv(ready=False)
            return 1 if '-r' in argv else 0
        with mock.patch.object(wf_launch.subprocess, 'call', side_effect=call), \
                mock.patch.object(wf_launch, 'runs', return_value=True):
            vpy, failure = wf_launch.build_venv(self.paths, sys.executable, quiet=True)
        self.assertIsNone(vpy)
        self.assertEqual(failure[1], 1)
        self.assertFalse(os.path.exists(self.paths.ready))


class TestMain(unittest.TestCase):
    def test_bad_arguments_exit_20(self):
        with mock.patch.object(wf_launch, 'say'):
            self.assertEqual(wf_launch.main([]), 20)
            self.assertEqual(wf_launch.main(['--launcher', 'wf.bat', '--data-root', '/d', 'run']), 20)
            self.assertEqual(wf_launch.main(['--launcher', 'wf.sh', '--data-root', '/d', 'build']), 20)


def _bash():
    if os.name != 'nt':
        return shutil.which('bash')
    # System32's bash.exe is WSL, which cannot run a Windows Python.
    git = shutil.which('git')
    folder = os.path.dirname(git) if git else ''
    for _ in range(3):
        folder = os.path.dirname(folder)
        candidate = os.path.join(folder, 'bin', 'bash.exe')
        if folder and os.path.isfile(candidate):
            return candidate
    return None


class EndToEnd(object):
    """Run a launcher for real: cold call builds the venv, warm call reuses it."""

    cache_name = None

    def command(self, *args):
        raise NotImplementedError

    def setUp(self):
        self.data = tempfile.mkdtemp()
        self.addCleanup(shutil.rmtree, self.data, True)

    def run_launcher(self, *args, **env_overrides):
        env = dict(os.environ, CLAUDE_PLUGIN_DATA=self.data, **env_overrides)
        return subprocess.run(self.command(*args), env=env, stdout=subprocess.PIPE,
                              stderr=subprocess.PIPE, timeout=300)

    def path_without_python(self):
        """A PATH on which no python3, py or python can be found.

        Directories that hold a Python are dropped. The few tools wf.sh needs
        from such a directory (on Linux, /usr/bin) are linked into a new one.
        """
        names = ('python', 'python3', 'py', 'python.exe', 'python3.exe', 'py.exe')
        kept = [d for d in os.environ.get('PATH', '').split(os.pathsep)
                if d and not any(os.path.isfile(os.path.join(d, n)) for n in names)]
        if os.name != 'nt':
            tools = tempfile.mkdtemp()
            self.addCleanup(shutil.rmtree, tools, True)
            for tool in ('dirname', 'rm', 'uname'):
                found = shutil.which(tool)
                if found:
                    os.symlink(found, os.path.join(tools, tool))
            kept.insert(0, tools)
        return os.pathsep.join(kept)

    def cache(self):
        with open(os.path.join(self.data, self.cache_name)) as f:
            return f.read().splitlines()

    def test_cold_warm_setup_and_stale_cache(self):
        cold = self.run_launcher('--help')
        self.assertEqual(cold.returncode, 0, cold.stderr)
        kind, path = self.cache()
        self.assertEqual(kind, 'venv')
        self.assertTrue(os.path.isfile(path))
        self.assertTrue(os.path.isfile(os.path.join(self.data, 'wf-venv', '.wf-ready')))

        # wf.py's own exit code comes back through the launcher.
        self.assertEqual(self.run_launcher('no-such-subcommand').returncode, 2)

        setup = self.run_launcher('setup')
        self.assertEqual(setup.returncode, 0, setup.stderr)
        self.assertIn(b'already set up', setup.stderr)

        bad = os.path.join(self.data, 'bad.exe')
        with open(bad, 'wb') as f:
            f.write(b'\x01\x02\x03')
        # Executable, so it fails to start rather than being opened as a document.
        os.chmod(bad, 0o755)
        with open(os.path.join(self.data, self.cache_name), 'w') as f:
            f.write('venv\n%s\n' % bad)
        stale = self.run_launcher('--help')
        self.assertEqual(stale.returncode, 0, stale.stderr)
        self.assertEqual(self.cache(), [kind, path])

        # A ready venv is a finished setup even with no Python on PATH.
        bare = self.run_launcher('setup', PATH=self.path_without_python())
        self.assertEqual(bare.returncode, 0, bare.stderr)
        self.assertIn(b'already set up', bare.stderr)


@unittest.skipUnless(_bash(), 'bash is not installed')
class TestWfShEndToEnd(EndToEnd, unittest.TestCase):
    cache_name = 'wf-python'

    def command(self, *args):
        return [_bash(), os.path.join(SCRIPTS, 'wf.sh')] + list(args)


@unittest.skipUnless(shutil.which('pwsh'), 'PowerShell 7 is not installed')
class TestWfPs1EndToEnd(EndToEnd, unittest.TestCase):
    cache_name = 'wf-python-ps1'

    def command(self, *args):
        return [shutil.which('pwsh'), '-NoProfile', '-NonInteractive', '-File', os.path.join(SCRIPTS, 'wf.ps1')] + list(args)


if __name__ == '__main__':
    unittest.main()
