"""
Session labels: the claim mark that cloud and local sessions both read (#440).

A local session claims with a ref under `refs/claims/`. A Claude Code cloud
session cannot create one: `git push` answers HTTP 403 there, and so does
every write to the REST git data API. Every session runs as the same login,
so an assignment cannot tell two sessions apart either. Each claim therefore
also adds the label `session: <guid>` to the issue or pull request, where
`<guid>` names the Claude session. Both kinds of session read it.

- Where the ref push works, the ref stays the primary lock and the label is
  added beside it. A label write that fails there is a warning, not a lost
  claim.
- Where the push is refused with 403 (or `WF_CLAIM_REFS=off`), the label is
  the only lock. The run first checks the claim ref with `ls-remote`, which
  still works there, so a story a local run holds by ref is taken.
- After adding its label, a run reads the labels GitHub returns. When its own
  is the only `session:` label, it holds the item. When there are more, it
  reads the item's events, and the session whose present label was added
  first keeps it. Any other session removes its own label and treats the item
  as taken.
- Every run and every Builder in one Claude session shares the GUID, so a
  second run in the same session treats the first run's label as its own.

Releasing a claim removes the label as well as the ref. `claim-reap` deletes a
`session:` label from the repository once no open issue or pull request
carries it; release does not, because a run in the same session may be adding
it to another item at that moment, and deleting a label takes it off every
item.

The marker file `.claude/claim-<target>.sha` holds the ref's sha for a ref
claim, or `session:<guid>` for a claim held by the label alone.

`scripts/README.md` has the module map.
"""

import os
import re
import threading
import uuid
from urllib.parse import quote

from wf_config import load_config, repo_root
from wf_io import eprint, gh_graphql, gh_rest, graphql_blocked, run


CLAIM_REFS_ENV = 'WF_CLAIM_REFS'
SESSION_ENV = 'WF_SESSION_ID'
CLAUDE_SESSION_ENV = 'CLAUDE_CODE_SESSION_ID'
SESSION_LABEL_PREFIX = 'session: '
LABEL_MARKER_PREFIX = 'session:'
SESSION_ID_FILE = 'wf-session-id'
# GitHub caps a label name at 50 characters; the prefix takes 9.
_GUID_MAX = 40
_EVENT_PAGES = 10

REFUSED_NOTICE = (
    'wf: this session refuses claim refs (HTTP 403), so wf claims each story '
    'with its session label alone')

_state = {'refused': False, 'announced': False, 'repo': None, 'session': None}
_lock = threading.Lock()


def claim_marker_path(root, target):
    return os.path.join(root, '.claude', 'claim-%s.sha' % target)


def push_refused(err):
    """Whether a claim push failed because the remote refused it with 403.

    A rate limit can also answer 403, and it passes, so it does not switch the
    run to label claims.
    """
    text = (err or '').lower()
    return 'rate limit' not in text and re.search(r'\b403\b', text) is not None


def mark_claim_refs_refused():
    """Claim with the session label alone for the rest of the run, and say so
    once."""
    with _lock:
        _state['refused'] = True
        if not _state['announced']:
            _state['announced'] = True
            eprint(REFUSED_NOTICE)


def claim_refs_refused():
    """Whether this run claims with the session label alone."""
    if (not _state['refused']
            and os.environ.get(CLAIM_REFS_ENV, '').strip().lower() == 'off'):
        mark_claim_refs_refused()
    return _state['refused']


def reset_claim_label_state():
    """Forget the switch, the repository and the session. The offline tests
    call this between cases."""
    _state.update(refused=False, announced=False, repo=None, session=None)


def _clean_guid(raw):
    return re.sub(r'[^A-Za-z0-9-]', '', raw or '')[:_GUID_MAX]


def session_guid():
    """The GUID of this Claude session.

    `WF_SESSION_ID` when it is set, else `CLAUDE_CODE_SESSION_ID`, which
    Claude Code gives every command in the session, a Builder's included.
    Outside Claude Code, a GUID kept in `.claude/wf-session-id` of this
    checkout, so the runs in one checkout share it.
    """
    with _lock:
        if _state['session']:
            return _state['session']
        guid = (_clean_guid(os.environ.get(SESSION_ENV))
                or _clean_guid(os.environ.get(CLAUDE_SESSION_ENV)))
        if not guid:
            path = os.path.join(repo_root(), '.claude', SESSION_ID_FILE)
            try:
                with open(path, encoding='utf-8') as fh:
                    guid = _clean_guid(fh.read())
            except OSError:
                guid = ''
            if not guid:
                guid = str(uuid.uuid4())
                try:
                    os.makedirs(os.path.dirname(path), exist_ok=True)
                    with open(path, 'w', encoding='utf-8') as fh:
                        fh.write(guid)
                except OSError:
                    pass
        _state['session'] = guid
        return guid


def session_label(guid=None):
    return SESSION_LABEL_PREFIX + (guid or session_guid())


def is_session_label(name):
    return (name or '').startswith(SESSION_LABEL_PREFIX)


def _repo():
    if _state['repo'] is None:
        ok, cfg, _err = load_config()
        if not ok or not cfg.get('org') or not cfg.get('repo'):
            return None
        _state['repo'] = '%s/%s' % (cfg['org'], cfg['repo'])
    return _state['repo']


def _issue_path(target):
    """`repos/{owner}/{repo}/issues/{n}` for an `issue-N` or `pr-N` target, or
    None. A pull request is an issue to the REST label and event endpoints."""
    kind, _, raw = target.partition('-')
    if kind not in ('issue', 'pr') or not raw.isdigit():
        return None
    repo = _repo()
    return 'repos/%s/issues/%d' % (repo, int(raw)) if repo else None


def _label_names(data):
    """Label names from a labels list or from an issue object."""
    if isinstance(data, dict):
        data = data.get('labels')
    names = []
    for label in data or ():
        name = label.get('name') if isinstance(label, dict) else label
        if name:
            names.append(name)
    return names


def read_label_marker(target):
    """The GUID when this checkout holds `target` by its label alone, else
    None, which is also the answer for a ref claim's marker."""
    try:
        with open(claim_marker_path(repo_root(), target), encoding='utf-8') as fh:
            held = fh.read().strip()
    except OSError:
        return None
    if not held.startswith(LABEL_MARKER_PREFIX):
        return None
    return held[len(LABEL_MARKER_PREFIX):] or None


def claim_error_reason(target, ref_reason):
    """The reason a caller gives for a claim that ended in 'error'.

    `ref_reason` is its wording for a failed claim ref push, kept exactly
    where refs are used. After the switch the failure was the label, so the
    reason says that and points at stderr, which names the cause.
    """
    if not claim_refs_refused():
        return ref_reason
    return ('could not claim %s with its session label through the REST issues '
            'API (not a lost claim); the line before this one names the cause'
            % target)


def claim_ref_of(target):
    """What holds `target`, for a pick or review result: its claim ref, or
    `label:session: <guid>` for a claim held by the label alone."""
    guid = read_label_marker(target)
    return 'label:%s' % session_label(guid) if guid else 'refs/claims/%s' % target


def _first_added(path, present):
    """The present session label whose latest `labeled` event came first, or
    None when the events cannot be read."""
    latest = {}
    for page in range(1, _EVENT_PAGES + 1):
        ok, events, err = gh_rest('%s/events?per_page=100&page=%d' % (path, page))
        if not ok or not isinstance(events, list):
            eprint('wf: cannot read the events of %s to order its session labels '
                   '(%s)' % (path, err or 'no list returned'))
            return None
        for event in events:
            name = ((event or {}).get('label') or {}).get('name')
            if (event or {}).get('event') == 'labeled' and name in present:
                latest[name] = max(latest.get(name, 0), int(event.get('id') or 0))
        if len(events) < 100:
            break
    if not latest:
        return None
    # A label that is present but whose event was not found sorts last: it
    # cannot be shown to have come first.
    return min(present, key=lambda name: latest.get(name, float('inf')))


def label_winner(path, names):
    """Which session holds the item, from the labels it carries now.

    Returns (label or None, readable). No `session:` label at all is
    (None, True). Several mean a race, settled by the events.
    """
    present = [name for name in names if is_session_label(name)]
    if not present:
        return None, True
    if len(present) == 1:
        return present[0], True
    first = _first_added(path, present)
    return first, first is not None


def remove_session_label(target, label=None):
    """Take this session's label off `target`. True when it is gone; a label
    that is not there is gone."""
    path = _issue_path(target)
    if not path:
        return False
    label = label or session_label()
    ok, _data, err = gh_rest('%s/labels/%s' % (path, quote(label, safe='')), 'DELETE')
    if ok or '404' in (err or '') or 'not found' in (err or '').lower():
        return True
    eprint('wf: warning - could not remove the label "%s" from %s (%s)'
           % (label, target, err or 'no detail'))
    return False


def remove_session_labels(targets):
    """Take this session's label off many items. Returns {target: removed}.

    Through GraphQL this costs two requests however many items there are: one
    read of their node ids and the label's, and one aliased mutation. Where
    GraphQL is blocked, or the batch fails, each item costs one REST request.
    """
    targets = [t for t in dict.fromkeys(targets or ()) if _issue_path(t)]
    if not targets:
        return {}
    if len(targets) > 1 and not graphql_blocked():
        done = _remove_labels_graphql(targets)
        if done is not None:
            return done
    return {target: remove_session_label(target) for target in targets}


def _remove_labels_graphql(targets):
    """The batched removal, or None when it could not be made."""
    owner, _, name = _repo().partition('/')
    label = session_label()
    items = ''.join(
        ' t%d: issueOrPullRequest(number: %d) { ... on Issue { id } '
        '... on PullRequest { id } }' % (i, int(t.partition('-')[2]))
        for i, t in enumerate(targets))
    query = ('query($owner: String!, $name: String!, $label: String!) { '
             'repository(owner: $owner, name: $name) { label(name: $label) { id }%s } }'
             % items)
    ok, data, _err = gh_graphql(query, owner=owner, name=name, label=label)
    repo = (data or {}).get('repository') if ok else None
    if not isinstance(repo, dict):
        return None
    if not repo.get('label'):
        # No item can carry a label the repository does not have.
        return dict.fromkeys(targets, True)
    ids = {t: ((repo.get('t%d' % i) or {}).get('id')) for i, t in enumerate(targets)}
    body = ''.join(
        ' r%d: removeLabelsFromLabelable(input: {labelableId: "%s", labelIds: ["%s"]}) '
        '{ clientMutationId }' % (i, ids[t], repo['label']['id'])
        for i, t in enumerate(targets) if ids[t])
    if not body:
        return dict.fromkeys(targets, True)
    ok, _data, err = gh_graphql('mutation {%s }' % body)
    if not ok:
        eprint('wf: warning - could not remove the label "%s" in one request (%s); '
               'removing it from each item' % (label, err or 'no detail'))
        return None
    return dict.fromkeys(targets, True)


def add_and_settle(target):
    """Add this session's label to `target` and settle who holds it.

    Returns 'won', 'lost' or 'error'. 'error' means the label could not be
    written or the holder could not be told, and the label has been taken
    back where it was added.
    """
    path = _issue_path(target)
    if not path:
        eprint('wf: cannot label %s to claim it: no org/repo in the config' % target)
        return 'error'
    mine = session_label()
    ok, data, err = gh_rest(path + '/labels', 'POST', {'labels': [mine]})
    if not ok:
        eprint('wf: cannot add the label "%s" to %s (%s)' % (mine, target, err))
        return 'error'
    names = _label_names(data)
    if mine not in names:
        eprint('wf: GitHub did not add the label "%s" to %s' % (mine, target))
        return 'error'
    winner, readable = label_winner(path, names)
    if winner == mine:
        return 'won'
    remove_session_label(target, mine)
    return 'lost' if readable else 'error'


def ref_present(target):
    """True, False, or None when the remote cannot be asked."""
    code, _out, _err = run(['git', 'ls-remote', '--exit-code', 'origin',
                            'refs/claims/%s' % target])
    if code == 0:
        return True
    if code == 2:
        return False
    return None


def acquire_by_label(target):
    """Claim `target` with this session's label alone, for a session that
    refuses claim refs. 'won', 'lost' or 'error', as `acquire_claim` returns
    them."""
    present = ref_present(target)
    if present:
        return 'lost'
    if present is None:
        eprint('wf: cannot read refs/claims/%s to claim it' % target)
        return 'error'
    outcome = add_and_settle(target)
    if outcome == 'won':
        root = repo_root()
        os.makedirs(os.path.join(root, '.claude'), exist_ok=True)
        with open(claim_marker_path(root, target), 'w', encoding='utf-8') as fh:
            fh.write(LABEL_MARKER_PREFIX + session_guid())
    return outcome


def holds_label(target):
    """Whether this session holds `target` by its label: no claim ref is
    there, and its label is the one added first."""
    path = _issue_path(target)
    if not path or ref_present(target) is not False:
        return False
    ok, data, _err = gh_rest(path + '/labels')
    if not ok:
        return False
    winner, _readable = label_winner(path, _label_names(data))
    return winner == session_label()


def reap_session_labels(dry_run=False):
    """Delete each `session:` repository label that no open issue or pull
    request carries. Returns (deleted, failed), lists of label names."""
    repo = _repo()
    if not repo:
        return [], []
    names = []
    for page in range(1, _EVENT_PAGES + 1):
        ok, labels, _err = gh_rest('repos/%s/labels?per_page=100&page=%d' % (repo, page))
        if not ok or not isinstance(labels, list):
            break
        names += [n for n in _label_names(labels) if is_session_label(n)]
        if len(labels) < 100:
            break
    deleted, failed = [], []
    for name in names:
        ok, carried, _err = gh_rest('repos/%s/issues?state=open&per_page=1&labels=%s'
                                    % (repo, quote(name, safe='')))
        if not ok or not isinstance(carried, list) or carried:
            continue
        if dry_run:
            deleted.append(name)
            continue
        ok, _data, err = gh_rest('repos/%s/labels/%s' % (repo, quote(name, safe='')),
                                 'DELETE')
        (deleted if ok or '404' in (err or '') else failed).append(name)
    return deleted, failed
