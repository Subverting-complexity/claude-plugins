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
- A label of a crashed session would come first for good, so a run does not
  count a label as a rival's when it is stale: on an open issue that nobody is
  assigned to, and added `REAP_THRESHOLD_HOURS` or more ago, the same test
  `claim-reap` applies. The run takes that label off and claims the issue. A
  live holder is assigned within moments of its claim, so it is never stale.

Releasing a claim this checkout holds removes the label from that item only.
A closed, completed issue and a merged pull request keep their label for good,
as the record of the session that built them, and `handoff` leaves the label
on each issue it hands to review so the issue still carries it when it
closes. The repository label is deleted only by `claim-reap`, once no issue or
pull request, open or closed, carries it: deleting a label takes it off every
item. `claim-reap` frees a crashed claim by taking every `session:` label off
the item, and judges a claim held by a label alone as it judges a ref.

The marker file `.claude/claim-<target>.sha` holds the ref's sha for a ref
claim, or `session:<guid>` for a claim held by the label alone. A ref claim
also writes `.claude/claim-<target>.session`, the GUID of the label it added,
so its release removes that label even after a `/clear` gave the session a
new id (#442).

`scripts/README.md` has the module map.
"""

import os
import re
import threading
import time
import uuid
from datetime import datetime
from urllib.parse import quote

from wf_config import load_config, repo_root
from wf_core_claims import REAP_THRESHOLD_HOURS
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


def keep_label_path(root, target):
    """The file a `handoff` whose release failed leaves beside the marker, so
    the retried release keeps the label too."""
    return os.path.join(root, '.claude', 'claim-%s.keep-label' % target)


def claim_session_path(root, target):
    """The file beside a ref claim's marker that names the GUID of the session
    label the claim added (#442). The marker itself holds only the ref's sha,
    which `holds_claim` compares."""
    return os.path.join(root, '.claude', 'claim-%s.session' % target)


def write_claim_marker(root, target, held, guid=None):
    """Write the marker of a new claim. A `.keep-label` file an earlier
    claim's failed handoff left is dropped, or this claim's release would
    leave its label on the item. `guid`, for a ref claim, is the session whose
    label the claim adds; it is written beside the marker, and a file an
    earlier claim left there is dropped when there is none."""
    os.makedirs(os.path.join(root, '.claude'), exist_ok=True)
    with open(claim_marker_path(root, target), 'w', encoding='utf-8') as fh:
        fh.write(held)
    if guid:
        with open(claim_session_path(root, target), 'w', encoding='utf-8') as fh:
            fh.write(guid)
    stale = [keep_label_path(root, target)]
    if not guid:
        stale.append(claim_session_path(root, target))
    for path in stale:
        try:
            os.remove(path)
        except OSError:
            pass


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

    `WF_SESSION_ID` first: the plugin's SessionStart hook
    (`hooks/session-id.sh`) sets it from the `session_id` Claude Code passes
    the hook, so it is the session's own id. Else `CLAUDE_CODE_SESSION_ID`,
    which Claude Code sets in the environment of the commands it runs (not
    documented, and not checked to be the parent's id inside a Builder).
    Else, outside Claude Code, a random GUID
    kept in `.claude/wf-session-id` of this checkout, so the runs in one
    checkout share it.
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


def claim_label(target):
    """The session label the claim this checkout holds on `target` added.

    A claim held by the label alone names its GUID in its marker, and a ref
    claim in the file beside its marker. Either can differ from this
    session's GUID: `/clear` gives the session a new id, and the
    `SessionStart` hook exports it (#442). Removing this session's label then
    would answer 404, count as done, and leave the claim's label on the item.
    This session's label is the answer only when neither names one, as for a
    marker an older version wrote.
    """
    guid = read_label_marker(target)
    if guid is None:
        try:
            with open(claim_session_path(repo_root(), target), encoding='utf-8') as fh:
                guid = _clean_guid(fh.read())
        except OSError:
            guid = None
    return session_label(guid or None)


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
    if any(name not in latest for name in present):
        # A present label whose event was not read cannot be placed. Guessing
        # its place could let two sessions both hold the item, so the order is
        # unreadable and the caller gives its own label back.
        return None
    return min(present, key=lambda name: latest[name])


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


def stale_rivals(target, path, rivals):
    """The labels in `rivals` that no live session can hold, or [].

    Only an open issue with nobody assigned to it qualifies: a live claim
    assigns the issue right after it is won, and a pull request has no
    assignee to test. A label counts as stale at `REAP_THRESHOLD_HOURS`, the
    age `claim-reap` uses, and a label whose age cannot be read is not stale.
    """
    kind, _, raw = target.partition('-')
    repo = _repo()
    if kind != 'issue' or not raw.isdigit() or not repo:
        return []
    ok, item, _err = gh_rest(path)
    if (not ok or not isinstance(item, dict) or item.get('pull_request')
            or item.get('state') != 'open' or item.get('assignees')):
        return []
    stale = []
    for name in rivals:
        age = _label_age(repo, int(raw), name)
        if age is not None and age >= REAP_THRESHOLD_HOURS:
            stale.append(name)
    return stale


def remove_session_label(target, label=None):
    """Take `label`, this session's by default, off `target`. True when it
    is gone; a label that is not there is gone, which is why a release must
    name the label its claim added (`claim_label`). With no org/repo in the config no claim could
    have added it, so it is gone too."""
    path = _issue_path(target)
    if not path:
        return True
    label = label or session_label()
    ok, _data, err = gh_rest('%s/labels/%s' % (path, quote(label, safe='')), 'DELETE')
    if ok or '404' in (err or '') or 'not found' in (err or '').lower():
        return True
    eprint('wf: warning - could not remove the label "%s" from %s (%s)'
           % (label, target, err or 'no detail'))
    return False


def _carried(repo, name):
    """True when any issue or pull request, open or closed, carries the
    label, False when none does, None when the answer cannot be read."""
    ok, items, _err = gh_rest('repos/%s/issues?state=all&per_page=1&labels=%s'
                              % (repo, quote(name, safe='')))
    if not ok or not isinstance(items, list):
        return None
    return bool(items)


def _delete_repo_label(repo, name):
    ok, _data, err = gh_rest('repos/%s/labels/%s' % (repo, quote(name, safe='')),
                             'DELETE')
    return ok or '404' in (err or '') or 'not found' in (err or '').lower()


def remove_every_session_label(target):
    """Take every `session:` label off `target`, whichever session added it.
    `claim-reap` calls this for an item it frees, because a crashed session's
    label would otherwise come first on it and every later claim would lose.
    Finished work keeps its labels. True when none is left on an open item."""
    path = _issue_path(target)
    if not path or is_record(target):
        return True
    return strip_session_labels(path)


def strip_session_labels(path, closed_at=None):
    """Take the `session:` labels off the open item at `path`
    (`repos/{owner}/{repo}/issues/{n}`). True when none is left that should go.

    With `closed_at`, the time an abandoned pull request closed, `pick` calls
    it when it resets the issue that pull request was for. Only a label whose
    latest `labeled` event came before that time is the old build's and comes
    off. A label added after it is a live claim by a session rebuilding the
    issue, and stays: removing it would let a second session win the claim,
    so two sessions would build one story. When the close time or the events
    cannot be read, nothing comes off and the warning says why, because a
    guess could strip that live claim. A present label whose event was not
    read stays too. Without `closed_at` every `session:` label comes off.
    """
    ok, data, err = gh_rest(path + '/labels')
    if not ok:
        eprint('wf: warning - could not read the labels of %s to take its session '
               'labels off (%s)' % (path, err or 'no detail'))
        return False
    present = [name for name in _label_names(data) if is_session_label(name)]
    if not present:
        return True
    gone = True
    if closed_at is not None:
        closed = _parse_stamp(closed_at)
        added = _latest_labeled(path, present) if closed else None
        if added is None:
            eprint('wf: warning - could not tell when the session labels on %s were '
                   'added (%s), so none was taken off'
                   % (path, 'no close time for the pull request' if not closed
                      else 'its events could not be read'))
            return False
        unplaced = [name for name in present if name not in added]
        if unplaced:
            eprint('wf: warning - no event says when "%s" was added to %s, so it '
                   'stays' % ('", "'.join(unplaced), path))
            gone = False
        present = [name for name in present
                   if name in added and added[name] < closed]
    for name in present:
        done, _data, err = gh_rest('%s/labels/%s' % (path, quote(name, safe='')),
                                   'DELETE')
        if not (done or '404' in (err or '')):
            eprint('wf: warning - could not remove the label "%s" from %s (%s)'
                   % (name, path, err or 'no detail'))
            gone = False
    return gone


def _parse_stamp(stamp):
    try:
        return datetime.strptime((stamp or '')[:19], '%Y-%m-%dT%H:%M:%S')
    except ValueError:
        return None


def _latest_labeled(path, names):
    """{label: time of its latest `labeled` event} for the labels in `names`,
    or None when the events cannot be read."""
    added = {}
    for page in range(1, _EVENT_PAGES + 1):
        ok, events, _err = gh_rest('%s/events?per_page=100&page=%d' % (path, page))
        if not ok or not isinstance(events, list):
            return None
        for event in events:
            name = ((event or {}).get('label') or {}).get('name')
            when = _parse_stamp((event or {}).get('created_at'))
            if (event or {}).get('event') == 'labeled' and name in names and when:
                added[name] = max(added.get(name, when), when)
        if len(events) < 100:
            break
    return added


def _hours_since(stamp):
    try:
        then = datetime.strptime(stamp, '%Y-%m-%dT%H:%M:%SZ')
    except (TypeError, ValueError):
        return None
    return int((time.time() - (then - datetime(1970, 1, 1)).total_seconds()) // 3600)


def label_claims(skip=()):
    """Every claim held by a `session:` label alone, for `claim-reap`.

    Returns [(target, label, age_hours)] for each open issue or pull request
    carrying a `session:` label whose target is not in `skip` (the items that
    have a claim ref, which the ref pass judges). The age comes from the
    label's latest `labeled` event, None when it cannot be read.
    """
    repo = _repo()
    if not repo:
        return []
    claims = []
    for name in _session_repo_labels(repo):
        ok, items, _err = gh_rest('repos/%s/issues?state=open&per_page=100&labels=%s'
                                  % (repo, quote(name, safe='')))
        if not ok or not isinstance(items, list):
            continue
        for item in items:
            number = (item or {}).get('number')
            if not number:
                continue
            target = ('pr-%d' if item.get('pull_request') else 'issue-%d') % number
            if target in skip:
                continue
            claims.append((target, name, _label_age(repo, number, name)))
    return claims


def _label_age(repo, number, name):
    stamp = None
    for page in range(1, _EVENT_PAGES + 1):
        ok, events, _err = gh_rest('repos/%s/issues/%d/events?per_page=100&page=%d'
                                   % (repo, number, page))
        if not ok or not isinstance(events, list):
            return None
        for event in events:
            if ((event or {}).get('event') == 'labeled'
                    and ((event.get('label') or {}).get('name')) == name):
                stamp = event.get('created_at') or stamp
        if len(events) < 100:
            break
    return _hours_since(stamp) if stamp else None


def _session_repo_labels(repo):
    names = []
    for page in range(1, _EVENT_PAGES + 1):
        ok, labels, _err = gh_rest('repos/%s/labels?per_page=100&page=%d' % (repo, page))
        if not ok or not isinstance(labels, list):
            break
        names += [n for n in _label_names(labels) if is_session_label(n)]
        if len(labels) < 100:
            break
    return names


def _record_of(item, kind):
    """Whether an issue or pull request, as REST returns it, is a finished
    piece of work whose session label stays as its record."""
    if kind == 'pr' or (item or {}).get('pull_request'):
        return bool(((item or {}).get('pull_request') or {}).get('merged_at')
                    or (item or {}).get('merged_at'))
    return ((item or {}).get('state') == 'closed'
            and (item or {}).get('state_reason') in (None, 'completed'))


def is_record(target):
    """True when `target` is a closed, completed issue or a merged pull
    request, whose session label stays for good. False when it cannot be
    read: the label then comes off, as for any open item."""
    path = _issue_path(target)
    if not path:
        return False
    ok, item, _err = gh_rest(path)
    return bool(ok and isinstance(item, dict)
                and _record_of(item, target.partition('-')[0]))


def release_label(target, label=None):
    """Take `label`, this session's by default, off `target` at release,
    unless the item is finished work, which keeps it. True when the claim no
    longer holds it."""
    if is_record(target):
        return True
    return remove_session_label(target, label)


def remove_session_labels(targets, labels=None):
    """Take a session label off many items at release, leaving it on
    finished work as `release_label` does. Returns {target: removed}.

    `labels` maps a target to the label its claim added (`claim_label`); a
    target it does not name loses this session's label.

    Through GraphQL this costs two requests for each distinct label however
    many items carry it: one read of their node ids, their state and the
    label's id, and one aliased mutation. Where GraphQL is blocked, or a batch
    fails, each item costs a read and a removal through REST.
    """
    targets = list(dict.fromkeys(targets or ()))
    done = {t: True for t in targets if not _issue_path(t)}
    targets = [t for t in targets if t not in done]
    if not targets:
        return done
    label_of = {t: (labels or {}).get(t) or session_label() for t in targets}
    if not graphql_blocked():
        groups = {}
        for target in targets:
            groups.setdefault(label_of[target], []).append(target)
        for label, group in groups.items():
            if len(group) > 1:
                batch = _remove_labels_graphql(group, label)
                if batch is not None:
                    done.update(batch)
    done.update((target, release_label(target, label_of[target]))
                for target in targets if target not in done)
    return done


def _remove_labels_graphql(targets, label=None):
    """The batched removal of `label`, this session's by default, or None when
    it could not be made."""
    owner, _, name = _repo().partition('/')
    label = label or session_label()
    items = ''.join(
        ' t%d: issueOrPullRequest(number: %d) { ... on Issue { id state stateReason } '
        '... on PullRequest { id merged } }' % (i, int(t.partition('-')[2]))
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
    ids = {}
    for i, t in enumerate(targets):
        node = repo.get('t%d' % i) or {}
        finished = node.get('merged') or (
            node.get('state') == 'CLOSED'
            and node.get('stateReason') in (None, 'COMPLETED'))
        ids[t] = None if finished else node.get('id')
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
    rivals = [n for n in names if is_session_label(n) and n != mine]
    if rivals:
        gone = [n for n in stale_rivals(target, path, rivals)
                if remove_session_label(target, n)]
        if gone:
            eprint('wf: took the stale session label%s "%s" off %s: nobody is '
                   'assigned and %s older than %dh'
                   % ('s' if len(gone) > 1 else '', '", "'.join(gone), target,
                      'they are' if len(gone) > 1 else 'it is', REAP_THRESHOLD_HOURS))
            names = [n for n in names if n not in gone]
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
        write_claim_marker(repo_root(), target, LABEL_MARKER_PREFIX + session_guid())
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
    """Delete each `session:` repository label that no issue or pull
    request carries, open or closed: deleting a label takes it off every item,
    closed ones included, so a label still on a finished item is its record
    and stays. Returns (deleted, failed), lists of label names."""
    repo = _repo()
    if not repo:
        return [], []
    deleted, failed = [], []
    for name in _session_repo_labels(repo):
        if _carried(repo, name) is not False:
            continue
        if dry_run or _delete_repo_label(repo, name):
            deleted.append(name)
        else:
            failed.append(name)
    return deleted, failed
