"""
Claims through an issue assignment, for a session that refuses claim refs.

A Claude Code cloud session refuses every way of creating a ref under
`refs/claims/`: `git push` answers HTTP 403, and so does every write to the
REST git data API. Reads still work there, and so do issue writes. When a
claim push is refused with 403, `acquire_claim` claims through the assignees
of the issue or pull request instead, and wf says once that it did.
`WF_CLAIM_REFS=off` starts a run on assignment claims without trying a push.

An assignment is a weaker lock than a ref. Only one run wrote a claim ref's
object, so its sha tells that run from every other. An assignment names only
the GitHub login, and every run by one person signs in as the same login, so
two sessions by the same person started on the same pool at the same moment
can take the same story. Runs by different logins still keep each other out:
each reads the assignees, writes its own login and reads the answer back, and
a run that finds any other login there gives its assignment back and treats
the item as taken.

The claim is recorded in the same marker file a ref claim uses,
`.claude/claim-<target>.sha`, holding `assign:<login>:added` or
`assign:<login>:kept`. `added` means this claim wrote the assignment, so
releasing it removes the assignment. `kept` means the login was the only
assignee of a pull request already, so releasing leaves it as it was found.
An issue claim is always `added`: the pick refuses an assigned issue, so an
issue already assigned to this login alone can only be this person's own
earlier claim, and leaving it assigned would leave a claim behind.

`scripts/README.md` has the module map.
"""

import os
import re
import threading

from wf_config import load_config, repo_root
from wf_io import eprint, gh_rest
from wf_rest import rest_viewer_login


CLAIM_REFS_ENV = 'WF_CLAIM_REFS'
ASSIGN_PREFIX = 'assign:'

ASSIGNMENT_NOTICE = (
    'wf: this session refuses claim refs (HTTP 403), so wf claims each story '
    'through an issue assignment instead. An assignment names only the GitHub '
    'login, so two sessions run by the same person on the same pool at the '
    'same moment can take the same story')

_state = {'refused': False, 'announced': False, 'repo': None}
_lock = threading.Lock()


def claim_marker_path(root, target):
    return os.path.join(root, '.claude', 'claim-%s.sha' % target)


def push_refused(err):
    """Whether a claim push failed because the remote refused it with 403.

    A rate limit can also answer 403, and it passes, so it does not switch the
    run to assignment claims.
    """
    text = (err or '').lower()
    return 'rate limit' not in text and re.search(r'\b403\b', text) is not None


def mark_claim_refs_refused():
    """Claim through assignments for the rest of the run, and say so once."""
    with _lock:
        _state['refused'] = True
        if not _state['announced']:
            _state['announced'] = True
            eprint(ASSIGNMENT_NOTICE)


def claim_refs_refused():
    """Whether this run claims through assignments rather than refs."""
    if (not _state['refused']
            and os.environ.get(CLAIM_REFS_ENV, '').strip().lower() == 'off'):
        mark_claim_refs_refused()
    return _state['refused']


def reset_claim_assign_state():
    """Forget the switch and the repository. The offline tests call this
    between cases."""
    _state.update(refused=False, announced=False, repo=None)


def _issue_path(target):
    """`repos/{owner}/{repo}/issues/{n}` for an `issue-N` or `pr-N` target, or
    None. A pull request is an issue to the REST assignees endpoint."""
    kind, _, raw = target.partition('-')
    if kind not in ('issue', 'pr') or not raw.isdigit():
        return None
    if _state['repo'] is None:
        ok, cfg, _err = load_config()
        if not ok or not cfg.get('org') or not cfg.get('repo'):
            return None
        _state['repo'] = '%s/%s' % (cfg['org'], cfg['repo'])
    return 'repos/%s/issues/%d' % (_state['repo'], int(raw))


def _logins(data):
    return [a.get('login') for a in (data or {}).get('assignees') or ()
            if a.get('login')]


def read_assignment_marker(target):
    """(login, added) when this checkout holds `target` by assignment, else
    None, which is also the answer for a ref claim's marker."""
    try:
        with open(claim_marker_path(repo_root(), target), encoding='utf-8') as fh:
            held = fh.read().strip()
    except OSError:
        return None
    if not held.startswith(ASSIGN_PREFIX):
        return None
    login, _, how = held[len(ASSIGN_PREFIX):].rpartition(':')
    if not login:
        return None
    return login, how != 'kept'


def claim_ref_of(target):
    """What holds `target`, for a pick or review result: its claim ref, or
    `assignee:<login>` for a claim taken by assignment."""
    held = read_assignment_marker(target)
    return 'assignee:%s' % held[0] if held else 'refs/claims/%s' % target


def acquire_by_assignment(target):
    """Claim `target` by assigning the run's login. 'won', 'lost' or 'error',
    as `acquire_claim` returns them.

    The assignees are read first, so an item somebody else holds is lost
    without a write. The write's answer is the read-back: GitHub returns the
    issue as it stands after the write. Any other login there means a rival
    wrote at the same moment, so this run removes its own and loses. No login
    at all means GitHub dropped the write, which it does without an error for
    a login that may not be assigned, and that is an environment error.
    """
    path = _issue_path(target)
    login = rest_viewer_login()
    if not path or not login:
        eprint('wf: cannot claim %s by assignment (%s)'
               % (target, 'no org/repo in the config' if not path
                  else 'could not read the signed-in login'))
        return 'error'
    ok, data, err = gh_rest(path)
    if not ok:
        eprint('wf: cannot read the assignees of %s to claim it (%s)' % (target, err))
        return 'error'
    before = _logins(data)
    if any(name != login for name in before):
        return 'lost'
    added = target.startswith('issue-') or login not in before
    if login not in before:
        ok, data, err = gh_rest(path + '/assignees', 'POST', {'assignees': [login]})
        if not ok:
            eprint('wf: cannot assign %s to claim %s (%s)' % (login, target, err))
            return 'error'
        after = _logins(data)
        if any(name != login for name in after):
            gh_rest(path + '/assignees', 'DELETE', {'assignees': [login]})
            return 'lost'
        if login not in after:
            eprint('wf: GitHub did not assign %s to %s, so it cannot be claimed '
                   'by assignment' % (login, target))
            return 'error'
    root = repo_root()
    os.makedirs(os.path.join(root, '.claude'), exist_ok=True)
    with open(claim_marker_path(root, target), 'w', encoding='utf-8') as fh:
        fh.write('%s%s:%s' % (ASSIGN_PREFIX, login, 'added' if added else 'kept'))
    return 'won'


def release_assignment(target, keep_assignment=False):
    """Release a claim taken by assignment. True when it is gone.

    `keep_assignment` lets go of the claim and leaves the login assigned.
    `handoff` asks for it, because from the open pull request on an issue's
    assignment is its ownership marker, as it is after a claim ref is
    released, and the issue stays assigned through review.

    Removing an assignee that is already gone succeeds, so this stays
    idempotent. A failed removal is a failed release only when the login is
    still assigned or the assignees cannot be read, and the marker then stays,
    so a re-run can release it.
    """
    held = read_assignment_marker(target)
    if held is None:
        return True
    login, added = held
    path = _issue_path(target)
    if added and not keep_assignment:
        if not path:
            eprint('wf: warning - could not release %s: no org/repo in the config'
                   % target)
            return False
        ok, data, err = gh_rest(path + '/assignees', 'DELETE', {'assignees': [login]})
        if not ok:
            probed, data, _ = gh_rest(path)
            if not probed or login in _logins(data):
                eprint('wf: warning - could not release %s: %s is still assigned '
                       '(%s)' % (target, login, err or 'no detail'))
                return False
    try:
        os.remove(claim_marker_path(repo_root(), target))
    except OSError:
        pass
    return True


def holds_assignment(target):
    """Whether this checkout still holds `target` by assignment: its marker
    names the login, and that login is the only assignee."""
    held = read_assignment_marker(target)
    path = _issue_path(target)
    if held is None or not path:
        return False
    ok, data, _ = gh_rest(path)
    return ok and _logins(data) == [held[0]]
