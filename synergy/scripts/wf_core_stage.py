"""
The `Stage` field and work scope: stage names, who can do an issue, and which
stage an issue belongs in.

Moved verbatim out of wf_core.py; `scripts/README.md` has the module map.
"""


# With no `Ownership` value, these types are code work. They are the two kinds
# a person files for a code agent without thinking to say so; any other type
# with no owner is a question nobody has answered, and it is not picked.
DEFAULT_CODE_TYPES = frozenset({'User Story', 'Bug'})


def effective_scope(ownership, type_name=None):
    """The scope an issue's `Ownership` gives it, defaulting a blank one.

    A blank value on a `User Story` or `Bug` counts as `Code agent`. A value
    that is present but unrecognised is still None: an org that renamed its
    options gets nothing rather than a guess.
    """
    scope = ownership_scope(ownership)
    if scope is None and not str(ownership or '').strip() \
            and type_name in DEFAULT_CODE_TYPES:
        return SCOPE_CODE
    return scope


# Stage purpose key → the option's name on the org's `Stage` issue field.
#
# The state of an issue lives on the issue, in one org field, since 12.0.0. It
# lived in the `Status` field of a board card until then, which had three
# costs nobody could engineer away: an issue with no card had no state and
# could not be picked, every transition was a board write, and an issue on two
# boards had two states. A board now groups its columns by `Stage`, so every
# board shows the same value and no agent ever moves a card.
STAGE_NAMES = {
    'stage-backlog':     'Backlog',
    'stage-in-progress': 'In Progress',
    'stage-in-review':   'In Review',
    'stage-blocked':     'Blocked',
    'stage-non-code':    'Non-code',
    'stage-refinement':  'Needs refinement',
    'stage-parked':      'Parked',
    'stage-attention':   'Needs attention',
    'stage-done':        'Done',
}

# The stage the picker selects from, beside a blank `Stage`, which means the
# same thing: nobody has decided anything about this issue yet. Every other
# stage is one an issue is *not* available from.
POOL_STAGE = 'stage-backlog'


def stage_name(value):
    """The `Stage` option a purpose key or name refers to, or None.

    Accepts `stage-in-review`, `In Review` or `in review`, so a caller can pass
    whichever it holds. Anything else is None rather than passed through: a
    write naming an option the field does not have fails at GitHub, and saying
    so before the round trip is cheaper.
    """
    if not value:
        return None
    text = str(value).strip()
    if text in STAGE_NAMES:
        return STAGE_NAMES[text]
    lowered = text.lower()
    for name in STAGE_NAMES.values():
        if name.lower() == lowered:
            return name
    return None


def is_available_stage(value):
    """Whether an issue whose `Stage` is `value` is in the pick pool."""
    return not (value or '').strip() or stage_name(value) == STAGE_NAMES[POOL_STAGE]


def option_spelling(field_meta, name):
    """The live option's own spelling of `name`, matched case-insensitively.

    `stage_findings` passes an org whose option is spelled `backlog`, so the
    write has to accept that spelling too. Without this the audit reports the
    field clean and every transition then fails at GitHub on a name it was
    just told is valid.
    """
    options = (field_meta or {}).get('options') or {}
    if name in options:
        return name
    wanted = str(name).strip().lower()
    for live in options:
        if str(live).strip().lower() == wanted:
            return live
    return name


# ── work scope: who can actually do this issue ───────────────────────────────
# Three parties touch a backlog and only one of them writes code. An issue that
# needs a browser console, or a person with a device in their hand, is not work
# a code agent can pick up, and an issue body must belong to exactly one of the
# three — a body that mixes them cannot be finished by anyone.
#
# Two signals record it, and they have different jobs. The `Ownership` field is
# the structured answer: it is what the picker reads, what a board view groups
# by, and what `issue-apply` refuses to create an issue without. The title
# prefix is the human echo -- what somebody scanning a list of issue titles
# sees without opening one. `scope_findings` below is what stops the two
# drifting apart.
#
# There were four signals until 10.0.0: those two plus a `browser-agent` /
# `human-required` scope label and a `status-non-code` lifecycle label. Four
# records of one fact is three too many, and they did drift -- the check that
# reported the drift was itself most of `scope_findings`.

SCOPE_CODE = 'code'
SCOPE_BROWSER = 'browser'
SCOPE_HUMAN = 'human'

# Scope → the title prefix. Fixed strings rather than a pattern: the prefix is
# written by this plugin and read by people, and a loose match would claim any
# title that happened to open with a bracket.
SCOPE_PREFIXES = {SCOPE_BROWSER: '[Browser] ', SCOPE_HUMAN: '[Manual] '}


# Scope → the `Ownership` field option that records it. The field is the
# structured answer to "who has to do this", and the picker reads it first.
# Until 9.0.0 there was no field at all: the scope label and the title prefix
# were the only record, so a query could find non-code work but no *view* could
# group by it, and nothing stopped an issue claiming two owners at once.
OWNERSHIP_FIELD_OPTIONS = {
    SCOPE_CODE:    'Code agent',
    SCOPE_BROWSER: 'Browser agent',
    SCOPE_HUMAN:   'Human',
}

OWNERSHIP_BY_OPTION = {v.lower(): k for k, v in OWNERSHIP_FIELD_OPTIONS.items()}


def ownership_scope(field_value):
    """The scope an `Ownership` option names, or None when it names nothing.

    An unrecognised value is None rather than `code`: an org that renamed its
    options should have its issues fall through to the scope labels, not be
    handed to a code agent because the string did not match.
    """
    if not field_value:
        return None
    return OWNERSHIP_BY_OPTION.get(str(field_value).strip().lower())


def scope_from_title(title):
    """The scope a title prefix claims, or None when it carries no prefix.

    Case-insensitive, because real backlogs carry `[MANUAL]` as often as
    `[Manual]` and shouting is not a scope error. The spelling above is what
    new issues are written with; either is read.
    """
    title = (title or '').lower()
    for scope, prefix in SCOPE_PREFIXES.items():
        if title.startswith(prefix.lower()):
            return scope
    return None


def issue_scope(title, ownership=None):
    """The one party that owns this issue: browser, human, or code.

    The `Ownership` field decides. The title prefix is read only when the field
    has no value, and only so an issue written before the field existed still
    routes somewhere sensible while `issue-audit` catches up; a title that
    disagrees with a set field is a finding rather than a second opinion — see
    `scope_findings`. With neither, the issue is code work, which is the answer
    for the overwhelming majority of a backlog and the one the prefix
    convention is defined against.
    """
    scope = ownership_scope(ownership)
    if scope:
        return scope
    return scope_from_title(title) or SCOPE_CODE


def scope_findings(issues, ownership_map=None):
    """Every place an issue's two ownership signals disagree.

    `issues` are dicts carrying `number` and `title`; `ownership_map` is
    ``{issue_number: Ownership option name}`` from the org's field. Returns a
    list of {'number', 'title', 'kind', 'detail'} with these kinds:

      scope-unowned  — no `Ownership` value. The field is mandatory, so this is
                       an issue nothing can route: the picker will not offer it
                       to a code agent and no view will group it.
      scope-prefix   — the field and the title prefix name different parties,
                       or one is present without the other. The field is right
                       and the title is what gets corrected, but a person
                       scanning the list sees the title, so the two have to
                       agree.
      scope-option   — a value the `Ownership` field holds that names no known
                       party, which happens when an org renames its options.
                       Nothing can act on it.

    This used to police four signals against each other -- the field, the
    title prefix, a scope label and a `status-non-code` lifecycle label -- and
    most of it existed because a fact recorded four times is a fact that
    disagrees with itself. Two of those records are gone; what is left is the
    structured answer and the human-readable echo of it.
    """
    ownership_map = ownership_map or {}
    findings = []
    for issue in issues or ():
        number, title = issue.get('number'), issue.get('title') or ''
        value = ownership_map.get(number)
        prefixed = scope_from_title(title)

        def add(kind, detail):
            findings.append({'number': number, 'title': title,
                             'kind': kind, 'detail': detail})

        if not value:
            add('scope-unowned',
                'has no `Ownership` value, so nothing says who has to do it; '
                'set it to %s'
                % ', '.join(OWNERSHIP_FIELD_OPTIONS[k] for k in
                            (SCOPE_CODE, SCOPE_BROWSER, SCOPE_HUMAN)))
            continue

        owned = ownership_scope(value)
        if not owned:
            add('scope-option',
                "`Ownership` is '%s', which names no party this workflow knows "
                '(it reads %s)'
                % (value, ', '.join(OWNERSHIP_FIELD_OPTIONS[k] for k in
                                    (SCOPE_CODE, SCOPE_BROWSER, SCOPE_HUMAN))))
            continue

        expected = SCOPE_PREFIXES.get(owned)
        if expected and prefixed != owned:
            add('scope-prefix',
                'is owned by %s with no "%s" title prefix, so it reads as '
                'ordinary code work in any list of titles'
                % (OWNERSHIP_FIELD_OPTIONS[owned], expected.strip()))
        elif not expected and prefixed:
            add('scope-prefix',
                'is titled "%s" but owned by %s'
                % (SCOPE_PREFIXES[prefixed].strip(),
                   OWNERSHIP_FIELD_OPTIONS[owned]))
    return findings


# What a spec entry may ask for in `state`, and the stage each asks for. Three
# and not nine: these are the states a *writer* can know. In Progress, In
# Review and Done are written by the run that does the work, and Needs
# attention by the run that gives up on it, so a spec naming one of those would
# be describing something that has not happened.
SPEC_STATE_STAGES = {
    'backlog':    'stage-backlog',
    'refinement': 'stage-refinement',
    'parked':     'stage-parked',
}

# The stages `issue-apply` may change on its own. Everything else is a state
# some other run, or a person, set, and an update that is about a field value
# has no business overruling it: an issue in progress that
# was moved back to Backlog is offered to a second agent, and one a person
# parked or held for refinement is approved by the update that released it.
#
# `Needs refinement` is deliberately not here. It is where this phase puts an
# issue nothing can route, and it is also where a person withholds approval;
# the two are indistinguishable from the outside, so releasing one releases the
# other. A spec says `"state": "backlog"` to release it deliberately.
AUTO_MANAGED_STAGES = frozenset({'Backlog', 'Blocked', 'Non-code'})


def spec_state_stage(value):
    """The stage purpose key a spec's `state` names. Returns (key, err)."""
    if value is None:
        return None, None
    key = str(value).strip().lower()
    if key in SPEC_STATE_STAGES:
        return SPEC_STATE_STAGES[key], None
    return None, ("'%s' is not a state a spec may ask for (it reads: %s)"
                  % (value, ', '.join(sorted(SPEC_STATE_STAGES))))


def stage_for(scope, open_blockers, requested=None):
    """The stage purpose key an issue in this state belongs in.

    Five inputs in one order, and the order is the whole rule:

      non-code    `scope` is a browser agent or a person, so the stage is
                  Non-code. This wins over everything below it: the owner is a
                  property of the work, it survives every blocker closing, and
                  no sweep may release it into a pool that cannot do it.
      requested   the spec named a `state`. A person asking for `parked` or
                  `refinement` is a decision, and a decision outranks the
                  inference below it.
      unowned     `scope` is None, so the org's `Ownership` field says nothing
                  this workflow recognises. Nothing can route the issue -- the
                  picker will not offer it to a code agent and no view groups
                  it -- so it goes to Needs refinement rather than into a pool
                  it would sit in unpickable.
      blocked     at least one native edge points at an open issue.
      pickable    none of the above, so Backlog, which is what available means.

    `stage-backlog` is written rather than left blank. Both mean available, and
    the written value is the one a board groups under a column a person
    recognises instead of `No Stage`.
    """
    if scope in (SCOPE_BROWSER, SCOPE_HUMAN):
        return 'stage-non-code'
    if requested:
        return requested
    if scope is None:
        return 'stage-refinement'
    return 'stage-blocked' if open_blockers else 'stage-backlog'


def may_set_stage(current_stage, requested=None):
    """Whether `issue-apply` may write this issue's `Stage`. (allowed, why_not).

    A blank `Stage` is always written: it is available, and writing the stage
    the rule names is only saying so explicitly.
    """
    if requested:
        return True, None
    current = (current_stage or '').strip()
    if not current:
        return True, None
    if current in AUTO_MANAGED_STAGES:
        return True, None
    return False, current


# Stages `board-sync` never writes, whatever the issue looks like. Each one is a
# person's decision, and nothing readable on the issue can show it was undone.
SYNC_PROTECTED_STAGES = frozenset({'Parked', 'Needs refinement',
                                   'Needs attention', 'Non-code'})


def reconcile_stage(is_open, stage, blockers, open_blockers, assigned, claimed,
                    open_prs=(), scope=None):
    """The stage `board-sync` writes for one issue, or None to leave it alone.

    `blockers` and `open_blockers` count the issue's native blocked-by edges,
    all and still open. `open_prs` is every open pull request that closes the
    issue, each as `{'isDraft': bool}`. `claimed` is whether
    `refs/claims/issue-N` exists, and a caller that could not read the claim
    refs passes True, so an unreadable lock never releases work somebody holds.
    `scope` is the issue's `Ownership` read by `ownership_scope`.

    The rules, in the order they are tried:

      protected   Parked, Needs refinement, Needs attention and Non-code are
                  left alone, and so is a value that is not a stage at all.
      closed      a closed issue is Done.
      non-code    work owned by a browser agent or a person that is blank,
                  Backlog or Blocked goes to Non-code, as `stage_for` puts it
                  when the issue is written. Once a person has moved such work
                  on to In Progress or In Review it stays there, with or
                  without an assignee, because nothing the sync reads records
                  that manual work has started.
      started     a blank or Backlog issue somebody has started goes to In
                  Review for a ready pull request, or In Progress for a draft
                  one or an assignee. This is `stage_drift_target`, the rule
                  `preflight --fix` repairs `stage-drift` with, so the sync and
                  preflight never disagree. It is tried before Blocked, because
                  work under way is stronger evidence than a blocker.
      handed off  In Progress with a ready pull request goes to In Review.
      abandoned   In Progress or In Review with no assignee, no claim ref and
                  no open pull request goes back to Backlog, or to Blocked when
                  an edge is still open, so the next run has nothing to add.
      blocked     blank or Backlog with an open edge becomes Blocked.
      unblocked   Blocked whose edges have all closed is released: to Backlog,
                  or straight to where `started` puts it if somebody already
                  has. Blocked with no edge at all was set by a person and
                  stays.
      filed       a blank stage that no rule above moved becomes Backlog, so
                  no board card sits under "No Stage". The plugin still reads
                  blank as available; only the sync fills it in.

    Every result is a fixed point: feeding the stage it returns back in, with
    the same facts, returns None. That is what makes a second run a no-op.
    """
    current = stage_name(stage) or ''
    if (stage or '').strip() and not current:
        return None
    if current in SYNC_PROTECTED_STAGES:
        return None
    done = STAGE_NAMES['stage-done']
    if not is_open:
        return None if current == done else done

    prs = list(open_prs or ())
    backlog = STAGE_NAMES['stage-backlog']
    blocked = STAGE_NAMES['stage-blocked']
    in_progress = STAGE_NAMES['stage-in-progress']
    in_review = STAGE_NAMES['stage-in-review']
    non_code = STAGE_NAMES['stage-non-code'] if scope in (SCOPE_BROWSER, SCOPE_HUMAN) else None
    if non_code and current in ('', backlog, blocked):
        return non_code
    started = stage_drift_target(current, assigned=assigned, open_prs=prs)
    if started:
        return STAGE_NAMES[started]
    if current == in_progress and any(not pr.get('isDraft') for pr in prs):
        return in_review
    if current in (in_progress, in_review) and not (assigned or claimed or prs):
        return None if non_code else (blocked if open_blockers else backlog)
    if current in ('', backlog) and open_blockers:
        return blocked
    if current == blocked and blockers and not open_blockers:
        # Judged as if already released, so work somebody started lands where
        # it belongs in one write rather than via Backlog on the next run.
        released = stage_drift_target(backlog, assigned=assigned, open_prs=prs)
        return STAGE_NAMES[released or POOL_STAGE]
    if not current:
        return backlog
    return None


# ── stage drift ──────────────────────────────────────────────────────────────
# An issue whose `Stage` says it is available while GitHub says somebody has it.
# Two ways to get one. A run on a version before 12.0.0 never wrote the field,
# which on CadenceReader left four issues reading `Backlog` while they were in
# progress and in review. And a `Stage`
# write can fail after its claim landed, which every writer reports and none
# retries. Either way every view grouped by `Stage` shows the work as free.

DRIFT_STAGES = frozenset({'', STAGE_NAMES[POOL_STAGE].lower()})


def stage_drift_target(stage, assigned=False, open_prs=()):
    """The stage purpose key an issue's own GitHub state puts it in, or None.

    Only a blank or `Backlog` stage is judged. Every other stage was written
    on purpose by a run or a person, and an assignee or a pull request does not
    overrule `Blocked`, `Parked` or `Needs attention`.

    `open_prs` is every open pull request that closes the issue, each as
    `{'isDraft': bool}`. The order is the rule:

      in review    a ready pull request closes it, which is what hand-off means
      in progress  a draft pull request closes it, or somebody is assigned,
                   which is what a claim leaves behind
    """
    if (stage or '').strip().lower() not in DRIFT_STAGES:
        return None
    prs = list(open_prs or ())
    if any(not pr.get('isDraft') for pr in prs):
        return 'stage-in-review'
    if prs or assigned:
        return 'stage-in-progress'
    return None
