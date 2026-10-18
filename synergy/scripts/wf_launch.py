#!/usr/bin/env python3
"""The interpreter and virtualenv logic behind wf.sh and wf.ps1, in one place.

Both launchers used to carry their own copy of this in bash and PowerShell.
Now each keeps only what cannot run in Python: finding the data dir, trusting
a cached venv interpreter without launching anything, finding a base Python 3
when there is none, and installing one on `setup --install-python`. Everything
else is here:

    wf_launch.py --launcher wf.sh --data-root DIR run [wf args...]
    wf_launch.py --launcher wf.sh --data-root DIR setup [--force] [--install-python] [--ready-only]

This file runs on whatever bare system Python the launcher found, before
anything is pip-installed, so it imports the standard library only. Keep it
that way, and keep its syntax readable by an old Python 3 so a too-old
interpreter gets the version message rather than a SyntaxError.

The cache is two lines under the data dir: `venv` or `base`, then the
interpreter's absolute path. wf.sh reads `wf-python` and wf.ps1 reads
`wf-python-ps1`; they stay separate because a path the bash launcher wrote
before this module existed is one PowerShell cannot run.

Exit codes: `run` passes on wf.py's own; `setup` exits 0 when the venv is
ready and 20 when it is not (1 from wf.ps1 when requirements.txt fails, as
before), and 20 is what callers read as "fall back to the inline procedure".
"""
import os
import shutil
import subprocess
import sys
import time

HERE = os.path.dirname(os.path.abspath(__file__))
WF = os.path.join(HERE, 'wf.py')
REQUIREMENTS = os.path.join(HERE, 'requirements.txt')

CACHE_NAMES = {'wf.sh': 'wf-python', 'wf.ps1': 'wf-python-ps1'}

# Seconds a caller waits for a concurrent venv build before treating the lock
# as abandoned (its owner was killed without releasing it) and reclaiming it.
LOCK_TIMEOUT = 120
MIN_VERSION = (3, 8)
EXIT_ERROR = 20
# `setup --ready-only` on a venv that is not ready; the launcher reports it.
EXIT_NOT_READY = 3


class Paths(object):
    def __init__(self, data_root, launcher):
        data_root = os.path.abspath(data_root)
        self.launcher = launcher
        self.data_root = data_root
        self.venv = os.path.join(data_root, 'wf-venv')
        # Creating this directory is the exclusivity check: it succeeds for
        # exactly one concurrent caller. The name is the one both launchers
        # used before, so an older launcher still running respects it.
        self.lock = os.path.join(data_root, 'wf-venv.lock')
        # Written last, only by the caller holding the lock while building,
        # so it marks the venv as fully provisioned rather than merely there.
        self.ready = os.path.join(self.venv, '.wf-ready')
        self.cache = os.path.join(data_root, CACHE_NAMES[launcher])


def say(message):
    # As UTF-8 bytes, as the shell launchers wrote it, so a Windows code page
    # cannot mangle the text.
    sys.stderr.flush()
    stream = getattr(sys.stderr, 'buffer', None)
    if stream is None:
        sys.stderr.write(message + '\n')
    else:
        stream.write((message + '\n').encode('utf-8'))
    sys.stderr.flush()


def venv_candidates(paths):
    return [os.path.join(paths.venv, 'bin', 'python'),
            os.path.join(paths.venv, 'Scripts', 'python.exe')]


def runs(python):
    try:
        return subprocess.call([python, '--version'], stdout=subprocess.DEVNULL,
                               stderr=subprocess.DEVNULL) == 0
    except OSError:
        return False


def venv_python(paths):
    """The venv's interpreter if it exists and runs.

    True as soon as `python -m venv` finishes, before pip has run, so it must
    never decide that a build is complete. `venv_ready` does that.
    """
    for p in venv_candidates(paths):
        if os.path.isfile(p):
            return p if runs(p) else None
    return None


def venv_ready(paths):
    if not os.path.isfile(paths.ready):
        return None
    return venv_python(paths)


def version_text(python):
    try:
        out = subprocess.check_output([python, '--version'], stderr=subprocess.STDOUT)
        return out.decode('utf-8', 'replace').strip()
    except (OSError, subprocess.CalledProcessError):
        return 'Python'


def save_cache(paths, kind, python):
    """Best-effort: a cache that cannot be written only means a slower next call."""
    try:
        if not os.path.isdir(paths.data_root):
            os.makedirs(paths.data_root)
        with open(paths.cache, 'w', newline='\n') as f:
            f.write('%s\n%s\n' % (kind, python))
    except OSError:
        pass


def remove_cache(paths):
    try:
        os.remove(paths.cache)
    except OSError:
        pass


def acquire_lock(paths, timeout=LOCK_TIMEOUT, sleep=time.sleep):
    """Hold the build lock, waiting up to `timeout` seconds for another holder.

    Returns False on timeout, including a reclaim that lost to another late
    arrival.
    """
    try:
        if not os.path.isdir(paths.data_root):
            os.makedirs(paths.data_root)
    except OSError:
        pass
    waited = 0
    while True:
        try:
            os.mkdir(paths.lock)
            return True
        except OSError:
            pass
        if waited >= timeout:
            release_lock(paths)
            try:
                os.mkdir(paths.lock)
                return True
            except OSError:
                return False
        sleep(1)
        waited += 1


def release_lock(paths):
    shutil.rmtree(paths.lock, ignore_errors=True)


def build_venv(paths, base, quiet):
    """Create the venv from `base`, install requirements and mark it ready.

    The caller holds the lock. Returns (interpreter, None) on success or
    (None, (message, exit code)) on failure; quiet mode sends every child's
    output to nowhere.
    """
    sink = subprocess.DEVNULL if quiet else None
    parent = os.path.dirname(paths.venv)
    if not os.path.isdir(parent):
        os.makedirs(parent)
    if not quiet:
        say('wf: creating virtualenv at %s ...' % paths.venv)
    try:
        created = subprocess.call([base, '-m', 'venv', paths.venv], stdout=sink, stderr=sink) == 0
    except OSError:
        created = False
    if not created:
        return None, ('wf: could not create the virtualenv (on Debian/Ubuntu install python3-venv first).', EXIT_ERROR)
    vpy = venv_python(paths)
    if not vpy:
        return None, ('wf: virtualenv created but its interpreter is not usable.', EXIT_ERROR)
    upgraded = subprocess.call([vpy, '-m', 'pip', 'install', '--quiet', '--upgrade', 'pip'],
                               stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL) == 0
    if not upgraded and not quiet:
        say('wf: warning — could not upgrade pip; continuing.')
    if os.path.isfile(REQUIREMENTS):
        if subprocess.call([vpy, '-m', 'pip', 'install', '--quiet', '-r', REQUIREMENTS],
                           stdout=sink, stderr=sink) != 0:
            if paths.launcher == 'wf.ps1':
                return None, ("wf: installing %s failed; re-run 'wf.ps1 setup -Force' once the error above is fixed." % REQUIREMENTS, 1)
            return None, ('wf: failed to install requirements.txt.', EXIT_ERROR)
    open(paths.ready, 'a').close()
    return vpy, None


def autobootstrap(paths, base):
    """Build the venv silently on a run that would otherwise use system Python.

    Two ordinary calls with no venv can start at once (parallel agents share
    the data dir), so only the lock holder builds and everyone else waits for
    it rather than interleaving writes into one venv. Readiness is checked
    only once this call holds the lock, so a build in progress under someone
    else's hold is never mistaken for a finished one. Any failure returns
    None and the caller falls back to system Python.
    """
    if sys.version_info < MIN_VERSION:
        return None
    if not acquire_lock(paths):
        return None
    try:
        existing = venv_ready(paths)
        if existing:
            vpy = existing
        else:
            shutil.rmtree(paths.venv, ignore_errors=True)
            try:
                vpy, _ = build_venv(paths, base, quiet=True)
            except OSError:
                vpy = None
        if vpy:
            save_cache(paths, 'venv', vpy)
        return vpy
    finally:
        release_lock(paths)


def resolve(paths):
    """The interpreter wf.py should run on, as (kind, path), cached for next time.

    A venv that runs wins even before its ready marker exists, as both
    launchers always allowed. Otherwise this process's own interpreter is the
    base, and the venv is built from it before falling back to it.
    """
    vpy = venv_python(paths)
    if vpy:
        save_cache(paths, 'venv', vpy)
        return 'venv', vpy
    base = sys.executable
    vpy = autobootstrap(paths, base)
    if vpy:
        return 'venv', vpy
    say("wf: no dedicated virtualenv yet — using system Python %s. Run '%s setup' to pin one." % (base, paths.launcher))
    save_cache(paths, 'base', base)
    return 'base', base


def run_wf(python, args, execv=os.execv):
    argv = [python, WF] + list(args)
    if os.name != 'nt':
        sys.stdout.flush()
        sys.stderr.flush()
        return execv(python, argv)
    proc = subprocess.Popen(argv)
    while True:
        try:
            return proc.wait()
        except KeyboardInterrupt:
            continue


def cmd_run(paths, args):
    _, python = resolve(paths)
    return run_wf(python, args)


def cmd_setup(paths, args):
    force = '--force' in args or '-Force' in args
    # The launcher found no base Python and is asking an existing venv
    # interpreter only whether the venv is ready. It must never build from
    # itself, so anything short of ready leaves the launcher to report.
    ready_only = '--ready-only' in args
    # Whatever setup ends with is what the next call runs, so a failed setup
    # leaves no stale answer behind.
    remove_cache(paths)
    # The same lock as the silent build, so setup never races it either way.
    if not acquire_lock(paths):
        say('wf: timed out waiting for another wf process building the virtualenv. Try again shortly.')
        return EXIT_ERROR
    try:
        vpy = venv_ready(paths)
        if vpy and not force:
            save_cache(paths, 'venv', vpy)
            say('wf: virtualenv already set up — %s at %s' % (version_text(vpy), paths.venv))
            return 0
        if ready_only:
            return EXIT_NOT_READY
        if sys.version_info < MIN_VERSION:
            say('wf: found Python %d.%d but Python >= 3.8 is required.' % sys.version_info[:2])
            return EXIT_ERROR
        if force:
            shutil.rmtree(paths.venv, ignore_errors=True)
        vpy, failure = build_venv(paths, sys.executable, quiet=False)
        if failure:
            say(failure[0])
            return failure[1]
        save_cache(paths, 'venv', vpy)
        say('wf: setup complete — %s' % version_text(vpy))
        say("    Future '%s' calls reuse this interpreter automatically." % paths.launcher)
        return 0
    finally:
        release_lock(paths)


def main(argv):
    try:
        if argv[0] != '--launcher' or argv[2] != '--data-root' or argv[4] not in ('run', 'setup'):
            raise IndexError
        launcher, data_root, command, rest = argv[1], argv[3], argv[4], argv[5:]
        if launcher not in CACHE_NAMES:
            raise IndexError
    except IndexError:
        say('usage: wf_launch.py --launcher wf.sh|wf.ps1 --data-root DIR run|setup [args...]')
        return EXIT_ERROR
    paths = Paths(data_root, launcher)
    if command == 'setup':
        return cmd_setup(paths, rest)
    return cmd_run(paths, rest)


if __name__ == '__main__':
    sys.exit(main(sys.argv[1:]))
