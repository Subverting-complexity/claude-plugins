#!/usr/bin/env python3
"""
Fast, offline tests for workflow decision logic.

Covers the three pure-logic areas described in the workflow templates:
  - Story selection (priority sort, mode/refinement/gating filters)
  - Label resolution (project map lookup with default fallback)
  - Backlog-mode detection (sprint vs flat from milestone presence)

No GitHub API calls, no file I/O.  Feed fixture data in, assert outputs.
Reference: github-workflow/templates/default-labels.md
"""
import datetime
import os
import sys
import unittest

# ── Subject under test ───────────────────────────────────────────────────────
# The decision rules now live in the `wf` CLI's pure core
# (github-workflow/scripts/wf_core.py), which is the single canonical,
# executable encoding of the logic the workflow templates describe. The CLI's
# I/O shell (wf.py) imports the same module, so these offline tests exercise
# exactly the code that runs in production — no second copy to drift.

sys.path.insert(
    0,
    os.path.join(os.path.dirname(__file__), '..', 'github-workflow', 'scripts'),
)
from wf_core import (  # noqa: E402
    BULK_MAX,
        actionable_update_label,
    blocking_dependencies,
    branch_name,
    branch_slug,
    closing_issue_numbers,
    retired_labels_on,
    detect_backlog_mode,
    filter_by_native_type,
    get_sprint_candidates,
    is_maintenance_classification,
    plan_bulk_order,
    reconcile_review_labels,
    resolve_label,
    resolve_review_label,
    review_label_missing,
    review_names,
    select_pool,
    select_review_pool,
    select_story,
    select_update_pool,
)
# parse_claude_project lives in the I/O shell (wf.py) but does no I/O itself —
# it is pure text parsing, so it is exercised offline here alongside the core.
from wf import parse_claude_project, _graphql_args  # noqa: E402
import wf_core  # noqa: E402  (module handle for the value-map tables)


# ── Tests ────────────────────────────────────────────────────────────────────

# The picker reads structured fields, so a fixture issue carries them. The two
# that decide anything are `Priority` (the whole of the sort) and `Ownership`
# (the whole of the availability filter); `owner` defaults to code work because
# that is what the overwhelming majority of a backlog is, and the tests that
# care about the other two owners say so.
def _issue(number, labels=(), body='', milestone=None,
           priority=None, owner='Code agent'):
    return {'number': number, 'labels': list(labels), 'body': body,
            'milestone': milestone, '_priority': priority, '_owner': owner}


def _maps(candidates):
    """The `Priority` and `Ownership` maps a real run reads from the org."""
    return (
        {c['number']: c['_priority'] for c in candidates
         if c.get('_priority')},
        {c['number']: c['_owner'] for c in candidates if c.get('_owner')},
    )


def _pool(candidates, **kw):
    priority, ownership = _maps(candidates)
    kw.setdefault('priority_map', priority)
    kw.setdefault('ownership_map', ownership)
    return select_pool(candidates, **kw)


def _story(candidates, **kw):
    priority, ownership = _maps(candidates)
    kw.setdefault('priority_map', priority)
    kw.setdefault('ownership_map', ownership)
    return select_story(candidates, **kw)


class TestStorySelection(unittest.TestCase):
    """Priority sort, mode filter, ownership filter, and agent-gating."""

    # Priority sort. The org's `Priority` field is the only input: the
    # `priority-*` label fallback went in 10.0.0 because two answers to "how
    # urgent is this" drift, and the drift silently reorders a backlog.

    def test_higher_priority_beats_lower_issue_number(self):
        candidates = [
            _issue(1, priority='Medium'),
            _issue(10, priority='High'),
        ]
        self.assertEqual(_story(candidates)['number'], 10)

    def test_same_priority_lower_number_wins(self):
        candidates = [
            _issue(20, priority='Medium'),
            _issue(5, priority='Medium'),
        ]
        self.assertEqual(_story(candidates)['number'], 5)

    def test_full_priority_order_urgent_high_medium_low(self):
        candidates = [
            _issue(4, priority='Low'),
            _issue(3, priority='Medium'),
            _issue(2, priority='High'),
            _issue(1, priority='Urgent'),
        ]
        self.assertEqual(_story(candidates)['number'], 1)

    def test_an_issue_with_no_priority_value_sorts_after_explicit_low(self):
        candidates = [
            _issue(1),                       # no Priority value at all
            _issue(2, priority='Low'),
        ]
        self.assertEqual(_story(candidates)['number'], 2)

    def test_a_priority_label_no_longer_orders_anything(self):
        """The label used to be the fallback. It is now inert.

        An issue carrying `priority-critical` and no `Priority` value sorts
        last, behind an issue whose field says `Low`. That is the intended
        behaviour and not a regression: `config-audit` fails when the org has
        no `Priority` field, and `issue-audit` names every issue missing a
        value, so an unranked issue is a reported gap rather than a quiet
        reordering on the strength of a label nobody maintains.
        """
        candidates = [
            _issue(1, ['priority-critical']),
            _issue(2, priority='Low'),
        ]
        self.assertEqual(_story(candidates)['number'], 2)

    def test_empty_pool_returns_none(self):
        self.assertIsNone(_story([]))

    # Availability. The pool handed to `select_pool` is the board's Backlog
    # column, and `Status` holds one value, so an issue that is parked, in
    # progress, in review, blocked, done or awaiting refinement is in that
    # column and never reaches here. What is left to exclude is the one thing
    # a column cannot express: who can actually do the work.

    def test_a_status_label_no_longer_takes_an_issue_out_of_the_pool(self):
        """There is no such label any more, and a leftover one decides nothing.

        This is the opt-in model going away. `status-ready` used to be the only
        lifecycle label meaning "pick me", so an issue nobody had marked was
        invisible — which is exactly what happened on this plugin's own
        repository, where three workable issues sat in the backlog while the
        picker reported an empty pool. An issue still carrying one of the
        retired labels is picked on its fields like any other, and the write
        path takes the label off when it touches it.
        """
        for stale in ('status-parked', 'status-blocked', 'status-in-progress',
                      'status-in-review', 'status-needs-attention',
                      'status-ready', 'needs-refinement'):
            with self.subTest(stale=stale):
                picked = _story([_issue(1, [stale], priority='Urgent')])
                self.assertEqual(picked['number'], 1)

    def test_work_a_code_agent_cannot_do_is_excluded(self):
        for owner in ('Browser agent', 'Human'):
            with self.subTest(owner=owner):
                self.assertIsNone(_story([_issue(1, priority='Urgent',
                                                 owner=owner)]))

    def test_an_issue_with_no_ownership_value_is_excluded(self):
        """Not "probably code". The blank is a gap, and guessing at it is what
        handed a `[Manual]` device-pass job to a code agent."""
        self.assertIsNone(_story([_issue(1, priority='Urgent', owner=None)]))

    def test_an_unrecognised_ownership_option_is_excluded(self):
        """An org that renamed its options gets nothing rather than a guess."""
        self.assertIsNone(_story([_issue(1, priority='High', owner='Robot')]))

    def test_a_scope_label_no_longer_excludes_anything(self):
        """`browser-agent` was the fallback until 10.0.0. `Ownership` decides."""
        picked = _story([_issue(1, ['browser-agent'], priority='High')])
        self.assertEqual(picked['number'], 1)

    # Mode filter

    def test_story_mode_accepts_any_type(self):
        """In story mode there is no type filter — all issue kinds are eligible."""
        candidates = [
            _issue(1, priority='Medium'),
            _issue(2, priority='Medium'),
        ]
        self.assertEqual(_story(candidates, mode='story')['number'], 1)

    # A `type-*` label classifies nothing any more, on any org. An org that
    # has not enabled native issue types cannot answer a feature/maintenance
    # question at all, and saying so is the point -- guessing from labels is
    # what put a `[CHORE]` in the feature pool.

    def test_feature_mode_without_native_types_selects_nothing(self):
        candidates = [
            _issue(1, ['type-bug'], priority='High'),
            _issue(2, ['type-story'], priority='Medium'),
        ]
        self.assertIsNone(_story(candidates, mode='feature'))

    def test_maintenance_mode_without_native_types_selects_nothing(self):
        candidates = [_issue(1, ['type-bug'], priority='Medium')]
        self.assertIsNone(_story(candidates, mode='maintenance'))

    def test_the_unanswerable_candidates_are_named_not_dropped(self):
        unclassified = []
        candidates = [_issue(1, ['type-bug']), _issue(2, ['type-story'])]
        pool = _pool(candidates, mode='maintenance', unclassified=unclassified)
        self.assertEqual(pool, [])
        self.assertEqual(unclassified, [1, 2])

    def test_story_mode_still_needs_no_types_at_all(self):
        """Story mode asks no type question, so it is unaffected."""
        self.assertEqual(_story([_issue(1, priority='High')])['number'], 1)

    def test_no_label_on_an_issue_changes_whether_it_is_picked(self):
        """The whole of the 10.0.0 selection change, stated once.

        `claude-ready` was the human-approval gate and the last label the
        picker read. Approval is the card's column now: a person approves an
        issue by moving it into Backlog and withholds approval by leaving it
        elsewhere. Every label below used to decide something here and none of
        them decides anything now.
        """
        candidates = [
            _issue(1, ['status-parked', 'human-required', 'priority-low'],
                   priority='High'),
            _issue(2, ['claude-ready', 'priority-critical'], priority='Low'),
        ]
        self.assertEqual([c['number'] for c in _pool(candidates)], [1, 2])


class TestSelectionHonoursProjectLabelMap(unittest.TestCase):
    """No label is left in the fast path, whatever the project calls it.

    This class used to cover four filters: the priority sort, the scope filter,
    the refinement filter and agent gating. Every one of them read a label, and
    every one of them could be silently defeated by a project that renamed it
    -- a filter matching a default name that no issue carried, returning a pool
    of nothing and reporting a finished backlog. All four read a structured
    field now, and a field has no per-project name to get wrong.

    The tests stay, inverted: each one hands the selector a project map that
    renames the label it used to depend on, and proves the pool is unmoved.
    """

    def test_a_renamed_status_label_no_longer_empties_the_pool(self):
        """Regression, twice over. A lifecycle filter that did not know the
        project's own names emptied this pool to no-candidates; then the filter
        itself went, because the label was never what parked an issue -- the
        board column it sits in is, and a column has one value."""
        candidates = [
            _issue(5, priority='High'),
            _issue(6, ['triage'], priority='Medium'),   # renamed needs-refinement
        ]
        pool = _pool(candidates, project_map={'needs-refinement': 'triage'})
        self.assertEqual([c['number'] for c in pool], [5, 6])

    def test_a_renamed_approval_label_no_longer_gates_anything(self):
        """There is no gate. A project that still maps `claude-ready` to its own
        name gets the same pool as one that never had the label."""
        candidates = [
            _issue(1, priority='High'),
            _issue(2, ['bot-ok'], priority='Medium'),
        ]
        self.assertEqual(
            [c['number'] for c in
             _pool(candidates, project_map={'claude-ready': 'bot-ok'})],
            [1, 2])

    def test_a_renamed_priority_label_no_longer_orders_anything(self):
        """The sort reads the field, so a project's own label names cannot
        reorder it and cannot silently fail to."""
        candidates = [
            _issue(1, ['P2'], priority='Medium'),
            _issue(10, ['P1'], priority='High'),
        ]
        self.assertEqual(
            _story(candidates, project_map={'priority-high': 'P1',
                                            'priority-medium': 'P2'})['number'],
            10)


class TestLabelResolution(unittest.TestCase):
    """Purpose-key → concrete-name resolution with project map and default fallback."""

    def test_resolves_from_project_map(self):
        project_map = {'status-ready': 'custom-ready', 'priority-high': 'urgent'}
        self.assertEqual(resolve_label('status-ready', project_map), 'custom-ready')
        self.assertEqual(resolve_label('priority-high', project_map), 'urgent')

    def test_project_map_takes_precedence_over_defaults(self):
        project_map = {'priority-medium': 'medium-prio'}
        # Overrides the default 'priority-medium' name
        self.assertEqual(resolve_label('priority-medium', project_map), 'medium-prio')

    def test_falls_back_to_defaults_when_missing_from_project_map(self):
        project_map = {}
        self.assertEqual(resolve_label('status-ready', project_map), 'status-ready')
        self.assertEqual(resolve_label('priority-critical', project_map), 'priority-critical')

    def test_unknown_purpose_key_returns_the_key_itself(self):
        """Callers always get a non-empty string; unknown keys never silently disappear."""
        project_map = {}
        self.assertEqual(resolve_label('some-unknown-purpose', project_map), 'some-unknown-purpose')

    def test_partial_project_map_mixes_custom_and_defaults(self):
        project_map = {'status-ready': 'my-ready'}
        self.assertEqual(resolve_label('status-ready', project_map), 'my-ready')
        # Unmapped key falls through to default
        self.assertEqual(resolve_label('status-blocked', project_map), 'status-blocked')

    def test_all_lifecycle_purpose_keys_resolve_to_non_empty_string(self):
        lifecycle_keys = [
            'status-ready', 'needs-refinement', 'status-in-progress',
            'status-parked', 'status-blocked', 'status-in-review', 'status-needs-attention',
        ]
        for key in lifecycle_keys:
            result = resolve_label(key, {})
            self.assertNotEqual(result, '', msg=f"purpose key '{key}' resolved to empty string")

    def test_all_priority_purpose_keys_resolve_to_their_default_names(self):
        for key in ['priority-critical', 'priority-high', 'priority-medium', 'priority-low']:
            self.assertEqual(resolve_label(key, {}), key)


class TestBacklogMode(unittest.TestCase):
    """Sprint-vs-flat detection and sprint candidate narrowing."""

    def test_no_milestones_is_flat_mode(self):
        candidates = [
            _issue(1, [], milestone=None),
            _issue(2, [], milestone=None),
        ]
        self.assertEqual(detect_backlog_mode(candidates), 'flat')

    def test_any_milestone_triggers_sprint_mode(self):
        candidates = [
            _issue(1, [], milestone='Sprint 3'),
            _issue(2, [], milestone=None),
        ]
        self.assertEqual(detect_backlog_mode(candidates), 'sprint')

    def test_all_milestones_is_sprint_mode(self):
        candidates = [
            _issue(1, [], milestone='Sprint 3'),
            _issue(2, [], milestone='Sprint 3'),
        ]
        self.assertEqual(detect_backlog_mode(candidates), 'sprint')

    def test_empty_candidate_list_is_flat(self):
        self.assertEqual(detect_backlog_mode([]), 'flat')

    def test_sprint_filter_keeps_only_matching_milestone(self):
        candidates = [
            _issue(1, [], milestone='Sprint 3'),
            _issue(2, [], milestone='Sprint 4'),   # different sprint
            _issue(3, [], milestone=None),
        ]
        result = get_sprint_candidates(candidates, 'Sprint 3')
        self.assertEqual([c['number'] for c in result], [1])

    def test_sprint_selection_respects_priority_within_sprint(self):
        """After narrowing to a sprint, the priority sort still picks the best issue."""
        candidates = [
            _issue(1, priority='Low', milestone='Sprint 5'),
            _issue(2, priority='High', milestone='Sprint 5'),
            _issue(3, priority='Urgent', milestone='Sprint 6'),  # wrong sprint
        ]
        sprint_pool = get_sprint_candidates(candidates, 'Sprint 5')
        result = _story(sprint_pool)
        self.assertEqual(result['number'], 2)


class TestSelectPool(unittest.TestCase):
    """select_pool returns the full ordered list; select_story is its head."""

    def test_pool_is_sorted_best_first(self):
        candidates = [
            _issue(5, ['priority-low']),
            _issue(3, ['priority-critical']),
            _issue(4, ['priority-medium']),
        ]
        pool = _pool(candidates)
        self.assertEqual([c['number'] for c in pool], [3, 4, 5])

    def test_pool_head_matches_select_story(self):
        candidates = [
            _issue(2, ['priority-high']),
            _issue(1, ['priority-low']),
        ]
        self.assertEqual(_pool(candidates)[0]['number'], _story(candidates)['number'])

    def test_empty_pool_is_empty_list(self):
        self.assertEqual(_pool([]), [])


class TestParentParsing(unittest.TestCase):
    """The phrasings that name an issue's parent."""

    def test_each_accepted_phrasing(self):
        for body, expected in (
            ("Part of the Cadence Plus epic (#959).", 959),
            ("Part of #1124.", 1124),
            ("Sub-issue of #1124.", 1124),
            ("Subissue of #1124.", 1124),
            ("**Parent**: #959", 959),
            ("Epic: #959", 959),
        ):
            self.assertEqual(wf_core.parse_parent(body), expected, body)

    def test_the_epic_phrasing_wins_over_a_looser_one_elsewhere(self):
        """#1095's shape: the epic on line 1, an abandoned plan forty down."""
        body = ("Part of the Cadence Plus epic (#959).\n\n"
                "...\n\nThe pages would move to the new domain as part of #1005.")
        self.assertEqual(wf_core.parse_parent(body), 959)

    def test_two_candidates_at_the_same_precedence_answer_nothing(self):
        body = "Part of #1124.\n\nAlso part of #1125."
        self.assertIsNone(wf_core.parse_parent(body))

    def test_a_cross_reference_is_not_a_parent(self):
        self.assertIsNone(wf_core.parse_parent("Split out of #1032."))
        self.assertIsNone(wf_core.parse_parent("See #959 for the wider plan."))

    def test_empty_body(self):
        self.assertIsNone(wf_core.parse_parent(''))
        self.assertIsNone(wf_core.parse_parent(None))


def _audit_node(number, title='[STORY] Something', body='', parent=None,
                blocked_by=(), field_values=(), issue_type='User Story'):
    """A read-back issue node, shaped as the audit query returns it."""
    return {
        'number': number,
        'title': title,
        'body': body,
        'labels': {'nodes': []},
        'issueType': {'name': issue_type} if issue_type else None,
        'issueFieldValues': {'nodes': list(field_values)},
        'blockedBy': {'nodes': [{'number': n} for n in blocked_by]},
        'parent': {'number': parent} if parent else None,
    }


_AUDIT_FIELDS = {'Priority': {}, 'Effort': {}, 'Classification': {},
                 'Origin': {}, 'Ownership': {}}


def _gap_kinds(entry):
    return sorted(g['kind'] for g in entry['gaps'])


class TestParentGaps(unittest.TestCase):
    """The audit half, under `--parents`: an issue that names its epic."""

    def test_a_claimed_parent_with_no_native_parent_is_proposed(self):
        node = _audit_node(1131, body="Part of the Cadence Plus epic (#959).")
        entry = wf_core.audit_issue(node, _AUDIT_FIELDS, open_numbers={1131, 959},
                                    parents=True)
        self.assertIn('missing-parent', _gap_kinds(entry))
        self.assertEqual(entry['proposed']['parent'], 959)

    def test_an_issue_that_already_has_a_parent_is_left_alone(self):
        """A deeper parent is the more specific truth; do not flatten it."""
        node = _audit_node(1126, body="Part of the Cadence Plus epic (#959).",
                           parent=1124)
        entry = wf_core.audit_issue(node, _AUDIT_FIELDS,
                                    open_numbers={1126, 959, 1124},
                                    parents=True)
        self.assertIn('parent-differs', _gap_kinds(entry))
        self.assertNotIn('parent', entry['proposed'])

    def test_a_matching_parent_is_not_a_gap(self):
        node = _audit_node(1126, body="Part of #1124.", parent=1124)
        entry = wf_core.audit_issue(node, _AUDIT_FIELDS, open_numbers={1126, 1124},
                                    parents=True)
        self.assertNotIn('parent-differs', _gap_kinds(entry))
        self.assertNotIn('missing-parent', _gap_kinds(entry))

    def test_a_closed_parent_is_reported_but_not_proposed(self):
        node = _audit_node(1131, body="Part of #959.")
        entry = wf_core.audit_issue(node, _AUDIT_FIELDS, open_numbers={1131},
                                    parents=True)
        self.assertIn('parent-closed', _gap_kinds(entry))
        self.assertNotIn('parent', entry['proposed'])


class TestParentsAreOptIn(unittest.TestCase):
    """Without `--parents` the body's claim is not read at all.

    An issue created from a `feature-discovery` spec already carries its
    parent, so a routine audit that re-derived it from the first line would
    report a gap on every issue that names its epic and propose a value the
    pipeline had already written.
    """

    BODY = "Part of the Cadence Plus epic (#959)."

    def test_no_parent_gap_by_default(self):
        node = _audit_node(1131, body=self.BODY)
        entry = wf_core.audit_issue(node, _AUDIT_FIELDS, open_numbers={1131, 959})
        for kind in ('missing-parent', 'parent-closed', 'parent-differs'):
            self.assertNotIn(kind, _gap_kinds(entry))

    def test_no_parent_proposed_by_default(self):
        node = _audit_node(1131, body=self.BODY)
        entry = wf_core.audit_issue(node, _AUDIT_FIELDS, open_numbers={1131, 959})
        self.assertNotIn('parent', entry['proposed'])

class TestNativeTypePreference(unittest.TestCase):
    """`tech debt` is `Chore` on an org that has one, `Feature` otherwise."""

    def test_the_preferred_type_is_used_when_the_org_has_it(self):
        self.assertEqual(
            wf_core.native_type_for('tech debt', {'Feature': 1, 'Chore': 2}),
            'Chore')

    def test_the_default_stands_when_the_org_has_no_chore(self):
        self.assertEqual(wf_core.native_type_for('tech debt', {'Feature': 1}),
                         'Feature')
        self.assertEqual(wf_core.native_type_for('tech debt', None), 'Feature')

    def test_kinds_with_no_preference_are_untouched(self):
        rich = {'Feature': 1, 'Chore': 2, 'Bug': 3, 'User Story': 4}
        self.assertEqual(wf_core.native_type_for('bug', rich), 'Bug')
        self.assertEqual(wf_core.native_type_for('feature', rich), 'Feature')
        self.assertEqual(wf_core.native_type_for('architecture', rich), 'Feature')

    def test_an_unknown_kind_has_no_type(self):
        self.assertIsNone(wf_core.native_type_for('nonsense', {'Chore': 1}))

    def test_every_preference_names_a_real_kind(self):
        for kind in wf_core.NATIVE_TYPE_PREFERENCES:
            self.assertIn(kind, wf_core.NATIVE_TYPE_MAP, kind)

    def test_the_audit_reads_the_org_type_map(self):
        """Without this a Chore-typed debt issue reads as a contradiction."""
        node = _audit_node(700, title='[DEBT] Rate-limit the sign-in route',
                           issue_type='Chore')
        entry = wf_core.audit_issue(node, _AUDIT_FIELDS,
                                    type_map={'Feature': 1, 'Chore': 2})
        self.assertNotIn('type-contradiction', _gap_kinds(entry))
        entry = wf_core.audit_issue(node, _AUDIT_FIELDS,
                                    type_map={'Feature': 1})
        self.assertIn('type-contradiction', _gap_kinds(entry))

    def test_resolve_entry_type_follows_the_same_preference(self):
        self.assertEqual(
            wf_core.resolve_entry_type({'kind': 'tech debt'},
                                       {'Feature': 1, 'Chore': 2}),
            ('Chore', None))
        self.assertEqual(
            wf_core.resolve_entry_type({'kind': 'tech debt'}, {'Feature': 1}),
            ('Feature', None))

    def test_an_explicit_type_on_the_entry_wins(self):
        self.assertEqual(
            wf_core.resolve_entry_type({'kind': 'tech debt', 'type': 'Bug'},
                                       {'Chore': 1}),
            ('Bug', None))


class TestMandatoryFieldCarryThrough(unittest.TestCase):
    """A parent-only proposal must still satisfy `issue-apply`'s field check."""

    FILLED = (
        {'field': {'name': 'Priority'}, 'name': 'High'},
        {'field': {'name': 'Effort'}, 'name': 'M'},
        {'field': {'name': 'Classification'}, 'options': [{'name': 'New Feature'}]},
        {'field': {'name': 'Origin'}, 'name': 'Planned'},
        {'field': {'name': 'Ownership'}, 'name': 'Code agent'},
    )

    def test_values_the_issue_already_holds_are_repeated_in_the_proposal(self):
        node = _audit_node(1131, body="Part of the Cadence Plus epic (#959).",
                           field_values=self.FILLED)
        entry = wf_core.audit_issue(node, _AUDIT_FIELDS, open_numbers={1131, 959})
        fields = entry['proposed']['fields']
        for purpose in wf_core.MANDATORY_FIELD_KEYS:
            self.assertIn(purpose, fields, purpose)
        self.assertEqual(fields['field-priority'], 'High')

    def test_a_filled_field_is_not_reported_as_a_gap(self):
        node = _audit_node(1131, field_values=self.FILLED)
        entry = wf_core.audit_issue(node, _AUDIT_FIELDS)
        self.assertNotIn('missing-field', _gap_kinds(entry))


class TestBranchNaming(unittest.TestCase):
    """Deterministic slug + convention rendering from execute SKILL.md."""

    def test_slug_example_from_template(self):
        self.assertEqual(branch_slug('Fix: User login broken!!!'), 'fix-user-login-broken')

    def test_slug_collapses_and_trims(self):
        self.assertEqual(branch_slug('  --Multiple   Spaces-- '), 'multiple-spaces')

    def test_slug_truncates_to_40_chars_without_trailing_hyphen(self):
        slug = branch_slug('a' * 30 + ' ' + 'b' * 30)
        self.assertLessEqual(len(slug), 40)
        self.assertFalse(slug.endswith('-'))

    def test_branch_name_renders_convention(self):
        self.assertEqual(
            branch_name('feature/{number}/{short-desc}', 42, 'Add login button'),
            'feature/42/add-login-button',
        )

    def test_branch_name_leaves_unknown_placeholders(self):
        self.assertEqual(
            branch_name('wip/{number}/{user}/{short-desc}', 7, 'Tidy up'),
            'wip/7/{user}/tidy-up',
        )

    def test_branch_name_renders_spelled_out_slug_placeholder(self):
        """A config that spells the slug as {short-description} must not leak it."""
        self.assertEqual(
            branch_name('feature/{number}/{short-description}', 73, 'Fix label'),
            'feature/73/fix-label',
        )

    def test_branch_name_renders_every_slug_alias(self):
        for token in ('{short-desc}', '{short-description}', '{short_desc}',
                      '{description}', '{desc}', '{slug}', '{title}'):
            self.assertEqual(
                branch_name('feat/{number}/%s' % token, 5, 'Do a thing'),
                'feat/5/do-a-thing',
                msg=token,
            )
            self.assertNotIn('{', branch_name('feat/{number}/%s' % token, 5, 'Do a thing'))


class TestRetiredLabelsOn(unittest.TestCase):
    """The labels a command strips off whatever issue it touches.

    There is no "current lifecycle label" to find any more: state lives in the
    board column. What is left is a migration sweep -- an issue written under
    the label workflow carries names nothing reads, and the write path takes
    them off as it goes so the backlog cleans itself without a bulk edit.
    """

    def test_finds_the_retired_status_labels(self):
        labels = ['priority-high', 'status-blocked', 'type-story']
        self.assertEqual(retired_labels_on(labels, {}),
                         ['status-blocked', 'priority-high'])

    def test_finds_a_retired_ready_label(self):
        self.assertEqual(retired_labels_on(['status-ready'], {}), ['status-ready'])

    def test_respects_a_project_custom_name(self):
        self.assertEqual(
            retired_labels_on(['on-hold'], {'status-parked': 'on-hold'}),
            ['on-hold'])

    def test_the_scope_labels_are_retired_too(self):
        self.assertEqual(retired_labels_on(['browser-agent'], {}),
                         ['browser-agent'])

    def test_a_label_the_workflow_still_uses_is_left_alone(self):
        """`claude-authored` and the review labels are not workflow state."""
        self.assertEqual(retired_labels_on(['claude-authored'], {}), [])

    def test_returns_nothing_for_an_issue_carrying_none(self):
        self.assertEqual(retired_labels_on(['type-story'], {}), [])


def _pr(number, labels):
    return {'number': number, 'labels': labels}


# Resolve review-state names through the default (`review-`) path once.
_RN = review_names()


class TestReviewLabelResolution(unittest.TestCase):
    def test_defaults_use_review_prefix(self):
        self.assertEqual(resolve_review_label('changes-requested'), 'review-changes-requested')
        self.assertEqual(resolve_review_label('reviewing'), 'review-reviewing')

    def test_project_override_wins(self):
        self.assertEqual(
            resolve_review_label('approved', {'approved': 'ship-it'}), 'ship-it')

    def test_review_names_covers_every_purpose(self):
        for purpose in ('needs-review', 'reviewing', 'approved', 'changes-requested',
                        'needs-discussion', 'needs-re-review', 'failed', 'updating'):
            self.assertTrue(_RN[purpose])


class TestUpdatePool(unittest.TestCase):
    """code-review rework pool: my PRs with actionable feedback, prioritised."""

    def test_changes_requested_beats_needs_re_review(self):
        prs = [
            _pr(10, [_RN['needs-re-review']]),
            _pr(11, [_RN['changes-requested']]),
        ]
        self.assertEqual([p['number'] for p in select_update_pool(prs, _RN)], [11, 10])

    def test_priority_then_lowest_number(self):
        prs = [
            _pr(5, [_RN['needs-discussion']]),
            _pr(3, [_RN['changes-requested']]),
            _pr(9, [_RN['changes-requested']]),
        ]
        self.assertEqual([p['number'] for p in select_update_pool(prs, _RN)], [3, 9, 5])

    def test_skips_reviewing_updating_approved_needsreview_failed(self):
        for skip in ('reviewing', 'updating', 'approved', 'needs-review', 'failed'):
            prs = [_pr(1, [_RN[skip], _RN['changes-requested']])]
            self.assertEqual(select_update_pool(prs, _RN), [], msg=skip)

    def test_pr_without_actionable_label_excluded(self):
        self.assertEqual(select_update_pool([_pr(1, ['unrelated'])], _RN), [])

    def test_actionable_label_reports_highest_priority(self):
        labels = [_RN['needs-re-review'], _RN['changes-requested']]
        self.assertEqual(actionable_update_label(labels, _RN), _RN['changes-requested'])

    def test_actionable_label_none_when_absent(self):
        self.assertIsNone(actionable_update_label(['x'], _RN))


class TestReviewPool(unittest.TestCase):
    """code-review pool: open PRs needing review, re-review first."""

    def test_needs_re_review_before_needs_review(self):
        prs = [
            _pr(2, [_RN['needs-review']]),
            _pr(8, [_RN['needs-re-review']]),
        ]
        self.assertEqual([p['number'] for p in select_review_pool(prs, _RN)], [8, 2])

    def test_same_tier_lowest_number(self):
        prs = [_pr(7, [_RN['needs-review']]), _pr(4, [_RN['needs-review']])]
        self.assertEqual([p['number'] for p in select_review_pool(prs, _RN)], [4, 7])

    def test_skips_reviewing_and_updating(self):
        for skip in ('reviewing', 'updating'):
            prs = [_pr(1, [_RN[skip], _RN['needs-review']])]
            self.assertEqual(select_review_pool(prs, _RN), [], msg=skip)

    def test_approved_excluded_unless_needs_re_review(self):
        self.assertEqual(select_review_pool([_pr(1, [_RN['approved'], _RN['needs-review']])], _RN), [])
        # approved + new commits (needs-re-review) stays in the pool
        kept = select_review_pool([_pr(1, [_RN['approved'], _RN['needs-re-review']])], _RN)
        self.assertEqual([p['number'] for p in kept], [1])

    def test_pr_without_review_label_excluded(self):
        self.assertEqual(select_review_pool([_pr(1, ['type-bug'])], _RN), [])


class TestReviewFinish(unittest.TestCase):
    """review-finish label dance: strip stale state labels, leave the verdict."""

    def test_each_verdict_applies_exactly_its_label(self):
        # Start from a typical in-review PR (reviewing + the entry needs-review)
        # and confirm each verdict adds its own label and removes the rest.
        for verdict in ('approved', 'changes-requested', 'needs-discussion'):
            current = [_RN['reviewing'], _RN['needs-review']]
            add, remove = reconcile_review_labels(current, verdict, _RN)
            self.assertEqual(add, [_RN[verdict]], msg=verdict)
            self.assertEqual(set(remove), {_RN['reviewing'], _RN['needs-review']}, msg=verdict)

    def test_removes_every_other_state_label_but_keeps_verdict(self):
        # All seven state labels present (pathological) → remove the six that
        # are not the verdict, and do not re-add the one already present.
        current = [_RN[k] for k in (
            'needs-review', 'reviewing', 'approved', 'changes-requested',
            'needs-discussion', 'needs-re-review', 'failed')]
        add, remove = reconcile_review_labels(current, 'approved', _RN)
        self.assertEqual(add, [])  # approved already present
        self.assertNotIn(_RN['approved'], remove)
        self.assertEqual(len(remove), 6)

    def test_unrelated_labels_untouched(self):
        current = [_RN['reviewing'], 'priority-high', 'type-debt']
        add, remove = reconcile_review_labels(current, 'changes-requested', _RN)
        self.assertEqual(add, [_RN['changes-requested']])
        self.assertEqual(remove, [_RN['reviewing']])  # non-state labels left alone

    def test_fixes_applied_added_when_flagged_and_absent(self):
        current = [_RN['reviewing']]
        add, remove = reconcile_review_labels(current, 'approved', _RN, fixes_applied=True)
        self.assertIn(_RN['fixes-applied'], add)
        self.assertIn(_RN['approved'], add)

    def test_fixes_applied_not_duplicated_when_present(self):
        current = [_RN['reviewing'], _RN['fixes-applied']]
        add, remove = reconcile_review_labels(current, 'approved', _RN, fixes_applied=True)
        self.assertNotIn(_RN['fixes-applied'], add)        # already there, not re-added
        self.assertNotIn(_RN['fixes-applied'], remove)     # sticky, never removed

    def test_fixes_applied_never_removed_even_without_flag(self):
        current = [_RN['reviewing'], _RN['fixes-applied']]
        _, remove = reconcile_review_labels(current, 'approved', _RN, fixes_applied=False)
        self.assertNotIn(_RN['fixes-applied'], remove)

    def test_unknown_verdict_raises(self):
        with self.assertRaises(ValueError):
            reconcile_review_labels([_RN['reviewing']], 'shipped', _RN)

    def test_project_override_resolves_verdict_label(self):
        names = review_names({'approved': 'ship-it'})
        add, _ = reconcile_review_labels([names['reviewing']], 'approved', names)
        self.assertEqual(add, ['ship-it'])

    def test_create_if_missing_decision(self):
        # The verdict label did not stick → its name is returned for create.
        self.assertEqual(
            review_label_missing([_RN['reviewing']], 'approved', _RN), _RN['approved'])
        # It stuck → nothing to create.
        self.assertIsNone(
            review_label_missing([_RN['approved']], 'approved', _RN))


class TestProjectBoardParsing(unittest.TestCase):
    """parse_claude_project must resolve the board even when the template's
    `## Project Board (optional)` authoring qualifier is left on the heading."""

    _BOARD_TABLE = (
        "| Setting         | Value        |\n"
        "| --------------- | ------------ |\n"
        "| project-node-id | `PVT_abc123` |\n"
        "| project-title   | `My Board`   |\n"
    )

    def test_optional_qualifier_heading_is_parsed(self):
        text = "## Project Board (optional)\n\n" + self._BOARD_TABLE
        board = parse_claude_project(text)['board']
        self.assertEqual(board['project_node_id'], 'PVT_abc123')
        self.assertEqual(board['project_title'], 'My Board')

    def test_plain_heading_still_parsed(self):
        text = "## Project Board\n\n" + self._BOARD_TABLE
        self.assertEqual(parse_claude_project(text)['board']['project_node_id'], 'PVT_abc123')

    def test_na_node_id_resolves_to_none(self):
        text = ("## Project Board (optional)\n\n"
                "| Setting         | Value |\n"
                "| --------------- | ----- |\n"
                "| project-node-id | `n/a` |\n")
        self.assertIsNone(parse_claude_project(text)['board']['project_node_id'])

    def test_branch_convention_strips_example_backticks(self):
        """When the fenced pattern is unfilled, the backtick-wrapped example is
        used — its backticks must not survive into the convention."""
        text = ("## Branch Convention\n\n"
                "```\n{branch_pattern}\n```\n\n"
                "Example: `feature/{number}/{short-desc}`\n")
        self.assertEqual(
            parse_claude_project(text)['branch_convention'],
            'feature/{number}/{short-desc}',
        )


class TestReadyGateIsGone(unittest.TestCase):
    """There is one pool now — the board's Backlog column — and no gate.

    A project that still carries a `## Ready Gate` section is out of date
    rather than broken, so parsing ignores it entirely. Reading it would be
    worse than ignoring it: the value would describe a pool that no longer
    exists, and the most common value, `label`, described the opt-in model this
    release removed.
    """

    GATE = '\n'.join([
        '## Ready Gate',
        '',
        '| Setting    | Value   |',
        '| ---------- | ------- |',
        '| ready-gate | `label` |',
    ])

    def test_a_surviving_section_sets_nothing(self):
        self.assertNotIn('ready_gate', parse_claude_project(self.GATE))

    def test_a_project_without_the_section_is_no_different(self):
        self.assertNotIn('ready_gate', parse_claude_project('## Identity\n'))


    def test_label_map_resolves_purpose_keys(self):
        """The label map drives the purpose-key resolution the fast-path filters
        now rely on — a renamed label must land in cfg['labels']."""
        text = ("## Label Map\n\n"
                "| Purpose          | Label       |\n"
                "| ---------------- | ----------- |\n"
                "| status-ready     | `my-ready`  |\n"
                "| needs-refinement | `triage`    |\n")
        labels = parse_claude_project(text)['labels']
        self.assertEqual(labels['status-ready'], 'my-ready')
        self.assertEqual(labels['needs-refinement'], 'triage')


class TestBoardConfigParsing(unittest.TestCase):
    """parse_claude_project must read the board config including the new
    status-field-name setting so wf.py queries the correct field."""

    def _board(self, table_rows):
        text = ("## Project Board\n\n"
                "| Setting             | Value      |\n"
                "| ------------------- | ---------- |\n"
                + table_rows)
        return parse_claude_project(text)['board']

    def test_status_field_name_parsed(self):
        board = self._board("| status-field-name   | `Estado`   |\n")
        self.assertEqual(board['status_field_name'], 'Estado')

    def test_status_field_name_defaults_to_status(self):
        board = self._board("| project-node-id     | `PVT_abc`  |\n")
        self.assertEqual(board['status_field_name'], 'Status')

    def test_missing_board_section_defaults_to_status(self):
        cfg = parse_claude_project('## Identity\n')
        self.assertEqual(cfg['board']['status_field_name'], 'Status')

    def test_project_node_id_parsed(self):
        board = self._board("| project-node-id     | `PVT_abc`  |\n")
        self.assertEqual(board['project_node_id'], 'PVT_abc')

    def test_project_node_id_na_is_none(self):
        board = self._board("| project-node-id     | `n/a`      |\n")
        self.assertIsNone(board['project_node_id'])


class TestPriorityFieldOrdering(unittest.TestCase):
    """The org's `Priority` field orders the pool, and nothing else does.

    Priority used to be dual-tracked -- the label decided pick order, the field
    decided what the portal showed -- so setting Priority in the portal, which
    is where a person actually sets it, changed the views and left the picker
    reading a label nobody had touched. The field became the source of truth in
    9.0.0 with the label as a fallback; the fallback went in 10.0.0, because a
    fallback is still a second answer and it still disagreed.
    """

    def _order(self, candidates, priority_map):
        return [c['number'] for c in
                select_pool(candidates, priority_map=priority_map,
                            ownership_map={c['number']: 'Code agent'
                                           for c in candidates})]

    def test_the_field_is_what_orders(self):
        candidates = [_issue(1), _issue(2)]
        self.assertEqual(self._order(candidates, {1: 'Urgent', 2: 'Low'}), [1, 2])

    def test_the_full_field_order_is_urgent_high_medium_low(self):
        candidates = [_issue(n) for n in (1, 2, 3, 4)]
        order = {1: 'Low', 2: 'Medium', 3: 'High', 4: 'Urgent'}
        self.assertEqual(self._order(candidates, order), [4, 3, 2, 1])

    def test_an_issue_with_no_field_value_sorts_last(self):
        """Not "probably medium". An issue nobody has ranked is a gap the audit
        reports, and ranking it from a label is the drift this removed."""
        candidates = [_issue(1, ['priority-critical']), _issue(2), _issue(3)]
        self.assertEqual(self._order(candidates, {3: 'Low'}), [3, 1, 2])

    def test_the_option_name_is_matched_case_insensitively(self):
        candidates = [_issue(1), _issue(2)]
        self.assertEqual(self._order(candidates, {2: 'urgent'}), [2, 1])

    def test_an_unrecognised_option_sorts_last(self):
        """An org that renamed its options gets a reported gap, not a guess."""
        candidates = [_issue(1), _issue(2)]
        self.assertEqual(self._order(candidates, {1: 'P0', 2: 'Low'}), [2, 1])

    def test_a_priority_label_orders_nothing(self):
        candidates = [_issue(1, ['priority-low']),
                      _issue(2, ['priority-critical'])]
        self.assertEqual(self._order(candidates, None), [1, 2])

    def test_every_field_option_the_tooling_writes_has_a_rank(self):
        """The value `issue-apply` writes must be one the picker can order."""
        for option in wf_core.PRIORITY_FIELD_OPTIONS.values():
            self.assertIn(option.lower(), wf_core.PRIORITY_FIELD_RANK, option)


class TestClassificationValues(unittest.TestCase):
    """`Classification` is a multi-select, so a value is a list as often as a string."""

    def test_a_single_maintenance_option_counts(self):
        self.assertTrue(is_maintenance_classification('Tech Debt'))

    def test_one_maintenance_option_among_several_counts(self):
        self.assertTrue(is_maintenance_classification(['New Feature', 'Architecture']))

    def test_a_list_with_no_maintenance_option_does_not(self):
        self.assertFalse(is_maintenance_classification(['New Feature']))

    def test_an_empty_value_does_not(self):
        self.assertFalse(is_maintenance_classification([]))
        self.assertFalse(is_maintenance_classification(None))


class TestNativeTypeFiltering(unittest.TestCase):
    """Native issue type filtering for type-capable orgs.

    On a type-capable org, feature/maintenance modes filter by the native
    issueType field instead of the type-* label. The type_map is built from
    a GraphQL query in wf.py and passed through select_pool.
    """

    TYPE_MAP = {
        1: 'User Story',
        2: 'Bug',
        3: 'Feature',
        4: 'Feature',
        5: 'User Story',
        6: 'Epic',
    }

    def test_story_mode_returns_all(self):
        candidates = [_issue(1, []), _issue(2, []), _issue(3, [])]
        result = filter_by_native_type(candidates, 'story', self.TYPE_MAP)
        self.assertEqual(len(result), 3)

    def test_story_mode_never_offers_an_epic(self):
        """Found live: the pool offered a freshly filed epic beside its own
        stories. An epic is the outcome, not a piece of work."""
        candidates = [_issue(1, []), _issue(6, []), _issue(7, [])]
        result = filter_by_native_type(candidates, 'story', self.TYPE_MAP)
        self.assertEqual([c['number'] for c in result], [1, 7])

    def test_the_story_pool_never_offers_an_epic(self):
        """The filter above is only half of it: the pool itself skipped type
        filtering in story mode, which is how the epic still reached `pick`."""
        candidates = [_issue(1, []), _issue(6, [])]
        owners = {1: 'Code agent', 6: 'Code agent'}
        pool = wf_core.select_pool(candidates, mode='story',
                                   type_map=self.TYPE_MAP, ownership_map=owners)
        self.assertEqual([c['number'] for c in pool], [1])
        untyped = wf_core.select_pool(candidates, mode='story', type_map=None,
                                      ownership_map=owners)
        self.assertEqual(len(untyped), 2)

    def test_feature_mode_keeps_user_story(self):
        candidates = [_issue(1, []), _issue(2, []), _issue(3, []),
                       _issue(5, []), _issue(6, [])]
        result = filter_by_native_type(candidates, 'feature', self.TYPE_MAP)
        numbers = [c['number'] for c in result]
        self.assertEqual(numbers, [1, 5])

    def test_feature_mode_excludes_bug_feature_epic(self):
        candidates = [_issue(2, []), _issue(3, []), _issue(6, [])]
        result = filter_by_native_type(candidates, 'feature', self.TYPE_MAP)
        self.assertEqual(result, [])

    def test_maintenance_mode_keeps_bug(self):
        candidates = [_issue(1, []), _issue(2, []), _issue(5, [])]
        result = filter_by_native_type(candidates, 'maintenance', self.TYPE_MAP)
        self.assertEqual([c['number'] for c in result], [2])

    def test_maintenance_mode_includes_feature_without_classification(self):
        """Without classification data, all Feature-typed issues are included."""
        candidates = [_issue(2, []), _issue(3, []), _issue(4, [])]
        result = filter_by_native_type(candidates, 'maintenance', self.TYPE_MAP)
        self.assertEqual([c['number'] for c in result], [2, 3, 4])

    def test_maintenance_mode_with_classification_filters_feature(self):
        classification_map = {3: 'Tech Debt', 4: 'New Feature'}
        candidates = [_issue(2, []), _issue(3, []), _issue(4, [])]
        result = filter_by_native_type(candidates, 'maintenance',
                                        self.TYPE_MAP, classification_map)
        numbers = [c['number'] for c in result]
        self.assertIn(2, numbers)
        self.assertIn(3, numbers)
        self.assertNotIn(4, numbers)

    def test_maintenance_classification_accepts_architecture_and_security(self):
        classification_map = {3: 'Architecture', 4: 'Security'}
        candidates = [_issue(3, []), _issue(4, [])]
        result = filter_by_native_type(candidates, 'maintenance',
                                        self.TYPE_MAP, classification_map)
        self.assertEqual([c['number'] for c in result], [3, 4])

    def test_a_multi_select_classification_is_read_as_a_list(self):
        """The live API returns Classification as an option list, not a string."""
        classification_map = {3: ['Architecture', 'New Feature'],
                              4: ['New Feature']}
        candidates = [_issue(3, []), _issue(4, [])]
        result = filter_by_native_type(candidates, 'maintenance',
                                       self.TYPE_MAP, classification_map)
        self.assertEqual([c['number'] for c in result], [3])

    def test_an_unclassified_feature_is_left_out_and_named(self):
        """The field exists, this issue has no value: unanswerable.

        It is not guessed at from a `type-*` label, and not dropped in
        silence either -- its number comes back so the run can say so.
        """
        classification_map = {4: ['New Feature']}
        candidates = [_issue(3, ['type-debt']), _issue(4, [])]
        unclassified = []
        result = filter_by_native_type(candidates, 'maintenance', self.TYPE_MAP,
                                       classification_map, None, unclassified)
        self.assertEqual(result, [])
        self.assertEqual(unclassified, [3])

    def test_an_unclassified_feature_claiming_nothing_is_still_excluded(self):
        classification_map = {4: ['New Feature']}
        candidates = [_issue(3, []), _issue(4, [])]
        result = filter_by_native_type(candidates, 'maintenance', self.TYPE_MAP,
                                       classification_map)
        self.assertEqual(result, [])

    def test_candidate_without_type_info_excluded(self):
        candidates = [_issue(99, [])]
        result = filter_by_native_type(candidates, 'feature', self.TYPE_MAP)
        self.assertEqual(result, [])

    # The native type is the only classifier on a type-capable org. Reading a
    # `type-*` label or a `[PREFIX]` title here would be reading exhaust the
    # workflow no longer writes, and it used to give wrong answers.

    def test_a_type_label_does_not_classify_an_untyped_issue(self):
        candidates = [_issue(99, ['type-story'])]
        self.assertEqual(
            filter_by_native_type(candidates, 'feature', self.TYPE_MAP), [])
        self.assertEqual(
            filter_by_native_type([_issue(98, ['type-bug'])], 'maintenance',
                                  self.TYPE_MAP), [])

    def test_a_title_prefix_does_not_classify_an_untyped_issue(self):
        candidates = [dict(_issue(99, []), title='[BUG] Crash on save')]
        self.assertEqual(
            filter_by_native_type(candidates, 'maintenance', self.TYPE_MAP), [])

    def test_an_untyped_issue_is_named_rather_than_dropped_in_silence(self):
        """A short pool has to read as a gap in the data, not a clean backlog."""
        unclassified = []
        candidates = [_issue(1, []), _issue(99, ['type-story'])]
        result = filter_by_native_type(candidates, 'feature', self.TYPE_MAP,
                                       unclassified=unclassified)
        self.assertEqual([c['number'] for c in result], [1])
        self.assertEqual(unclassified, [99])

    def test_nothing_is_recorded_when_every_candidate_is_typed(self):
        unclassified = []
        filter_by_native_type([_issue(1, [])], 'feature', self.TYPE_MAP,
                              unclassified=unclassified)
        self.assertEqual(unclassified, [])

    def test_select_pool_reports_what_it_left_out(self):
        unclassified = []
        candidates = [_issue(2, []), _issue(99, ['type-bug'])]
        pool = _pool(candidates, mode='maintenance', type_map=self.TYPE_MAP,
                           unclassified=unclassified)
        self.assertEqual({c['number'] for c in pool}, {2})
        self.assertEqual(unclassified, [99])

    def test_select_pool_uses_type_map_when_provided(self):
        """select_pool routes through native-type filter when type_map is set."""
        candidates = [
            _issue(1, ['priority-high']),
            _issue(2, ['priority-medium']),
            _issue(3, ['priority-low']),
        ]
        pool = _pool(candidates, mode='feature', type_map=self.TYPE_MAP)
        numbers = [c['number'] for c in pool]
        self.assertEqual(numbers, [1])

    def test_select_pool_ignores_type_map_for_story_mode(self):
        """story mode never filters by type, even when type_map is provided."""
        candidates = [_issue(1, []), _issue(2, []), _issue(3, [])]
        pool = _pool(candidates, mode='story', type_map=self.TYPE_MAP)
        self.assertEqual(len(pool), 3)

    def test_select_pool_without_a_type_map_classifies_nothing(self):
        """No native types, no answer -- and every candidate is named."""
        candidates = [
            _issue(1, ['priority-high', 'type-story']),
            _issue(2, ['priority-medium', 'type-bug']),
        ]
        unclassified = []
        pool = _pool(candidates, mode='feature', unclassified=unclassified)
        self.assertEqual(pool, [])
        self.assertEqual(unclassified, [1, 2])


class TestClosingIssueNumbers(unittest.TestCase):
    """Normalising `closingIssuesReferences` across the two API shapes.

    Regression guard for the cmd_post_merge crash where the flat list returned
    by `gh pr view --json` was fed to `.get('nodes')` as if it were the GraphQL
    connection shape, raising `'list' object has no attribute 'get'`.
    """

    def test_gh_cli_flat_list_shape(self):
        """`gh pr view --json` returns a flat list of issue objects."""
        refs = [{'number': 5}, {'number': 12}]
        self.assertEqual(closing_issue_numbers(refs), [5, 12])

    def test_graphql_nodes_shape(self):
        """The GraphQL API wraps the same data in a `nodes` connection."""
        refs = {'nodes': [{'number': 5}, {'number': 12}]}
        self.assertEqual(closing_issue_numbers(refs), [5, 12])

    def test_empty_and_missing(self):
        self.assertEqual(closing_issue_numbers(None), [])
        self.assertEqual(closing_issue_numbers([]), [])
        self.assertEqual(closing_issue_numbers({'nodes': []}), [])
        self.assertEqual(closing_issue_numbers({}), [])

    def test_skips_entries_without_a_number(self):
        self.assertEqual(closing_issue_numbers([{'number': 7}, {}, {'title': 'x'}]), [7])


class TestGraphqlArgTyping(unittest.TestCase):
    """`gh api graphql` argv typing.

    Regression guard for the post-merge move-to-Done failure: a digit-only
    single-select option id (e.g. the board's Done column `98236657`) was passed
    via `-F`, which coerces all-digit values to ints, so the `$o:String!` /
    `ID!` variable arrived as an Int and GitHub rejected it with "Variable $o of
    type String! was provided invalid value". String/ID fields must use `-f`;
    only genuine Int args use `-F`.
    """

    @staticmethod
    def _pairs(args):
        """Collect (flag, key, value) for each variable, skipping the query."""
        out = []
        i = 0
        while i < len(args):
            if args[i] in ('-f', '-F') and not args[i + 1].startswith('query='):
                key, _, val = args[i + 1].partition('=')
                out.append((args[i], key, val))
            i += 2 if args[i] in ('-f', '-F') else 1
        return out

    def test_digit_only_string_id_uses_lowercase_f(self):
        """A digit-only option id stays a string (`-f`), not a coerced int."""
        args = _graphql_args('mutation($o:String!){ x }', {'o': '98236657'})
        self.assertIn(('-f', 'o', '98236657'), self._pairs(args))

    def test_alphanumeric_id_uses_lowercase_f(self):
        args = _graphql_args('mutation($id:ID!){ x }', {'id': 'PVT_kwDO'})
        self.assertIn(('-f', 'id', 'PVT_kwDO'), self._pairs(args))

    def test_int_uses_uppercase_f(self):
        """A real Int! arg (Python int) keeps typed `-F`."""
        args = _graphql_args('query($number:Int!){ x }', {'number': 73})
        self.assertIn(('-F', 'number', '73'), self._pairs(args))

    def test_bool_uses_uppercase_f_lowercased(self):
        args = _graphql_args('mutation($b:Boolean!){ x }', {'b': True})
        self.assertIn(('-F', 'b', 'true'), self._pairs(args))

    def test_query_is_first_arg_via_lowercase_f(self):
        args = _graphql_args('query { x }', {})
        self.assertEqual(args[:4], ['gh', 'api', 'graphql', '-f'])
        self.assertEqual(args[4], 'query=query { x }')


class TestBulkDependencyCarveOut(unittest.TestCase):
    """`blocking_dependencies` — a sibling in the same bulk set does not block.

    `execute`'s rule is "do not build on unmerged work you cannot see". A
    story in the same set is work the same run writes on the same branch, so
    it is exempt; anything else open still blocks, exactly as before.
    """

    def test_open_dependency_outside_the_set_still_blocks(self):
        self.assertEqual(blocking_dependencies([7], open_numbers=[7]), [7])

    def test_closed_dependency_never_blocks(self):
        self.assertEqual(blocking_dependencies([7], open_numbers=[]), [])

    def test_open_dependency_on_a_sibling_does_not_block(self):
        self.assertEqual(
            blocking_dependencies([7], open_numbers=[7], siblings=[7]), [])

    def test_sibling_carve_out_is_per_dependency(self):
        """One sibling dep and one external dep → only the external one blocks."""
        self.assertEqual(
            blocking_dependencies([7, 9], open_numbers=[7, 9], siblings=[7]), [9])

    def test_blocking_order_follows_the_dependency_list(self):
        self.assertEqual(
            blocking_dependencies([9, 7], open_numbers=[7, 9]), [9, 7])

    def test_no_siblings_matches_the_single_story_behaviour(self):
        """The default (no siblings) must be the pre-bulk behaviour verbatim."""
        self.assertEqual(blocking_dependencies([1, 2, 3], open_numbers=[2, 3]), [2, 3])

    def test_string_numbers_are_compared_numerically(self):
        self.assertEqual(
            blocking_dependencies([7], open_numbers=['7'], siblings=['7']), [])


class TestBulkSetOrdering(unittest.TestCase):
    """`plan_bulk_order` — trim to size, then build dependencies first."""

    @staticmethod
    def _story(number, *blocked_by):
        return {'number': number, 'blocked_by': list(blocked_by)}

    def _numbers(self, ordered):
        return [s['number'] for s in ordered]

    def test_independent_set_keeps_input_order(self):
        stories = [self._story(1), self._story(2), self._story(3)]
        ordered, notes = plan_bulk_order(stories)
        self.assertEqual(self._numbers(ordered), [1, 2, 3])
        self.assertEqual(notes, [])

    def test_dependency_inside_the_set_is_built_first(self):
        stories = [self._story(1), self._story(2, 3), self._story(3)]
        ordered, _ = plan_bulk_order(stories)
        self.assertEqual(self._numbers(ordered), [1, 3, 2])

    def test_chain_is_ordered_end_to_end(self):
        stories = [self._story(1, 2),
                   self._story(2, 3),
                   self._story(3)]
        self.assertEqual(self._numbers(plan_bulk_order(stories)[0]), [3, 2, 1])

    def test_dependency_outside_the_set_does_not_reorder(self):
        """A dep on an issue not in the set is the claim step's problem, not ours."""
        stories = [self._story(1, 99), self._story(2)]
        ordered, notes = plan_bulk_order(stories)
        self.assertEqual(self._numbers(ordered), [1, 2])
        self.assertEqual(notes, [])

    def test_oversized_set_is_trimmed_and_the_cut_reported(self):
        stories = [self._story(n) for n in range(1, 8)]
        ordered, notes = plan_bulk_order(stories)
        self.assertEqual(len(ordered), BULK_MAX)
        self.assertEqual(self._numbers(ordered), [1, 2, 3, 4, 5])
        self.assertEqual([(n['number'], n['reason']) for n in notes],
                         [(6, 'trimmed'), (7, 'trimmed')])

    def test_explicit_max_size_overrides_the_default(self):
        stories = [self._story(n) for n in range(1, 5)]
        ordered, notes = plan_bulk_order(stories, max_size=2)
        self.assertEqual(self._numbers(ordered), [1, 2])
        self.assertEqual(len(notes), 2)

    def test_trimming_happens_before_ordering(self):
        """A dep cut by the trim must not drag its dependent out of order."""
        stories = [self._story(1, 4), self._story(2), self._story(3),
                   self._story(4)]
        ordered, notes = plan_bulk_order(stories, max_size=3)
        self.assertEqual(self._numbers(ordered), [1, 2, 3])
        self.assertEqual([n['number'] for n in notes], [4])

    def test_cycle_is_reported_and_still_returns_every_story(self):
        stories = [self._story(1, 2), self._story(2, 1)]
        ordered, notes = plan_bulk_order(stories)
        self.assertEqual(sorted(self._numbers(ordered)), [1, 2])
        self.assertEqual({n['reason'] for n in notes}, {'dependency-cycle'})

    def test_self_reference_is_not_a_cycle(self):
        stories = [self._story(1, 1), self._story(2)]
        ordered, notes = plan_bulk_order(stories)
        self.assertEqual(self._numbers(ordered), [1, 2])
        self.assertEqual(notes, [])

    def test_empty_set_is_handled(self):
        self.assertEqual(plan_bulk_order([]), ([], []))


# ── issue type + org field value maps ────────────────────────────────────────

class TestFieldNameResolution(unittest.TestCase):
    """Field names resolve project-map first, then defaults, then the key."""

    def test_project_map_wins(self):
        self.assertEqual(
            wf_core.resolve_field_name('field-priority', {'field-priority': 'Urgency'}),
            'Urgency')

    def test_default_used_when_unmapped(self):
        self.assertEqual(wf_core.resolve_field_name('field-type', {}), 'Classification')

    def test_unknown_key_returns_itself(self):
        self.assertEqual(wf_core.resolve_field_name('field-nonsense', {}), 'field-nonsense')

    def test_empty_project_value_falls_through(self):
        self.assertEqual(wf_core.resolve_field_name('field-effort', {'field-effort': ''}),
                         'Effort')

    def test_reverse_lookup_finds_the_purpose(self):
        self.assertEqual(wf_core.field_purpose_for_name('Classification', {}), 'field-type')
        self.assertEqual(
            wf_core.field_purpose_for_name('Urgency', {'field-priority': 'Urgency'}),
            'field-priority')

    def test_reverse_lookup_of_an_unmapped_field_is_none(self):
        """This is how preflight notices a newly added org field."""
        self.assertIsNone(wf_core.field_purpose_for_name('Squad', {}))


class TestIssueValueMaps(unittest.TestCase):
    """The maps that were markdown tables, now validatable."""

    def test_every_native_type_entry_is_complete(self):
        for kind, entry in wf_core.NATIVE_TYPE_MAP.items():
            self.assertEqual(set(entry), {'type', 'classification'}, kind)

    def test_every_classification_is_a_valid_option(self):
        for kind, entry in wf_core.NATIVE_TYPE_MAP.items():
            self.assertIn(entry['classification'], wf_core.CLASSIFICATION_OPTIONS, kind)

    def test_no_kind_names_a_fallback_label(self):
        """There is no label path left to fall back to."""
        for kind, entry in wf_core.NATIVE_TYPE_MAP.items():
            self.assertNotIn('label', entry, kind)

    def test_the_label_map_defines_no_type_label(self):
        self.assertEqual(
            [k for k in wf_core._DEFAULT_LABELS if k.startswith('type-')], [])

    def test_every_field_key_has_a_name_and_a_data_type(self):
        self.assertEqual(set(wf_core.FIELD_NAME_DEFAULTS), set(wf_core.FIELD_DATA_TYPES))

    def test_mandatory_keys_are_real_fields(self):
        for key in wf_core.MANDATORY_FIELD_KEYS:
            self.assertIn(key, wf_core.FIELD_NAME_DEFAULTS, key)

    def test_priority_options_cover_every_priority_label(self):
        self.assertEqual(set(wf_core.PRIORITY_FIELD_OPTIONS),
                         {'priority-critical', 'priority-high',
                          'priority-medium', 'priority-low'})


# ── issue-spec validation ────────────────────────────────────────────────────
# `wf issue-apply` refuses a bad spec before it writes anything, so all of the
# refusing is pure and testable here. The org shape below is deliberately not
# the full inventory: it omits `Origin`, which is how an org with fewer fields
# than the defaults is exercised.

# Every mandatory field, because since 10.0.0 an org that does not define one
# cannot have an issue filed against it at all: the picker reads these five and
# nothing else, so a missing one is a decision with no input.
_FIELD_MAP = {
    'Priority': {'id': 'F_pri', 'data_type': 'single-select',
                 'options': {'High': 'o_hi', 'Medium': 'o_med'}},
    'Effort': {'id': 'F_eff', 'data_type': 'single-select',
               'options': {'Medium': 'o_effmed'}},
    'Classification': {'id': 'F_cls', 'data_type': 'multi-select',
                       'options': {'New Feature': 'o_nf', 'Bug Fix': 'o_bf'}},
    'Origin': {'id': 'F_org', 'data_type': 'single-select',
               'options': {'Development': 'o_dev'}},
    'Ownership': {'id': 'F_own', 'data_type': 'single-select',
                  'options': {'Code agent': 'o_code', 'Human': 'o_human'}},
}
_TYPE_MAP = {'User Story': 'IT_story', 'Epic': 'IT_epic', 'Bug': 'IT_bug'}


def _entry(**over):
    entry = {'key': 'a', 'title': 'A story', 'kind': 'story',
             'fields': {'field-priority': 'High', 'field-effort': 'Medium',
                        'field-origin': 'Development',
                        'field-ownership': 'Code agent'}}
    entry.update(over)
    return entry


class TestValidateSpec(unittest.TestCase):
    """The gate that stops blank metadata reaching GitHub."""

    def test_a_complete_entry_produces_a_plan_and_no_errors(self):
        errors, skipped, plans = wf_core.validate_spec(
            [_entry()], _FIELD_MAP, _TYPE_MAP)
        self.assertEqual(errors, [])
        self.assertEqual(plans[0]['type'], 'User Story')
        self.assertEqual(plans[0]['fields']['Priority']['input'],
                         {'fieldId': 'F_pri', 'singleSelectOptionId': 'o_hi'})

    def test_kind_supplies_the_classification_the_entry_did_not_name(self):
        """A `kind` is the whole point of the map: it implies both type and class."""
        _, _, plans = wf_core.validate_spec([_entry()], _FIELD_MAP, _TYPE_MAP)
        self.assertEqual(plans[0]['fields']['Classification']['input'],
                         {'fieldId': 'F_cls', 'multiSelectOptionIds': ['o_nf']})

    def test_a_missing_mandatory_field_names_the_issue_and_the_field(self):
        entry = _entry(fields=dict(_entry()['fields']))
        del entry['fields']['field-priority']
        errors, _, _ = wf_core.validate_spec([entry], _FIELD_MAP, _TYPE_MAP)
        self.assertEqual(len(errors), 1)
        self.assertIn('a', errors[0])
        self.assertIn('Priority', errors[0])

    def test_a_placeholder_counts_as_missing(self):
        """`TODO` is what an audit writes; it must not be able to pass as a value."""
        entry = _entry(fields=dict(_entry()['fields'],
                                   **{'field-priority': wf_core.SPEC_PLACEHOLDER}))
        errors, _, _ = wf_core.validate_spec([entry], _FIELD_MAP, _TYPE_MAP)
        self.assertEqual(len(errors), 1)
        self.assertIn('Priority', errors[0])

    def test_a_required_field_the_org_never_created_is_refused(self):
        """Not skipped. This is the 10.0.0 change, and it is the point.

        Skipping is what let a repository run for weeks with no `Ownership`
        field while `config-audit` reported a clean configuration and the
        picker had no way to tell a device-pass job from code work.
        """
        without = {k: v for k, v in _FIELD_MAP.items() if k != 'Ownership'}
        errors, _, _ = wf_core.validate_spec([_entry()], without, _TYPE_MAP)
        self.assertEqual(len(errors), 1)
        self.assertIn('Ownership', errors[0])
        self.assertIn('create it', errors[0])

    def test_an_optional_field_the_org_never_created_is_not_refused(self):
        """`Classification` and `Origin` are worth having and not worth
        refusing an issue over. Nothing selects on either."""
        without = {k: v for k, v in _FIELD_MAP.items() if k != 'Origin'}
        errors, _, plans = wf_core.validate_spec([_entry()], without, _TYPE_MAP)
        self.assertEqual(errors, [])
        self.assertEqual(plans[0]['unset_optional'], [])

    def test_an_optional_field_left_empty_is_recorded_for_a_comment(self):
        """The writer turns this into a comment on the issue, so the gap is
        visible to whoever opens it rather than only to whoever ran the
        command."""
        entry = _entry(kind=None,
                       fields={'field-priority': 'High',
                               'field-effort': 'Medium',
                               'field-ownership': 'Code agent'})
        _, _, plans = wf_core.validate_spec([entry], _FIELD_MAP, _TYPE_MAP)
        self.assertEqual(plans[0]['unset_optional'],
                         ['Classification', 'Origin'])

    def test_a_situational_field_the_org_does_not_define_is_still_skipped(self):
        """An org is allowed fewer fields than the default inventory; it is the
        mandatory five it may not be missing."""
        entry = _entry(fields=dict(_entry()['fields'],
                                   **{'field-target': '2026-01-01'}))
        errors, skipped, plans = wf_core.validate_spec([entry], _FIELD_MAP, _TYPE_MAP)
        self.assertEqual(errors, [])
        self.assertEqual(skipped, {'Target date'})
        self.assertNotIn('Target date', plans[0]['fields'])

    def test_an_option_the_field_does_not_offer_is_an_error(self):
        entry = _entry(fields=dict(_entry()['fields'],
                                   **{'field-priority': 'Blocker'}))
        errors, _, _ = wf_core.validate_spec([entry], _FIELD_MAP, _TYPE_MAP)
        self.assertEqual(len(errors), 1)
        self.assertIn('Blocker', errors[0])

    def test_a_type_the_org_has_not_enabled_is_an_error(self):
        entry = _entry(type='Feature')
        errors, _, _ = wf_core.validate_spec([entry], _FIELD_MAP, _TYPE_MAP)
        self.assertTrue(any('Feature' in e for e in errors), errors)

    def test_an_unknown_kind_is_an_error(self):
        errors, _, _ = wf_core.validate_spec([_entry(kind='saga')],
                                             _FIELD_MAP, _TYPE_MAP)
        self.assertTrue(any('saga' in e for e in errors), errors)

    def test_an_entry_with_neither_title_nor_number_is_an_error(self):
        entry = _entry(title=None)
        entry.pop('title')
        errors, _, _ = wf_core.validate_spec([entry], _FIELD_MAP, _TYPE_MAP)
        self.assertTrue(any('title' in e for e in errors), errors)

    def test_a_duplicate_key_is_an_error(self):
        errors, _, _ = wf_core.validate_spec([_entry(), _entry()],
                                             _FIELD_MAP, _TYPE_MAP)
        self.assertTrue(any('duplicate key' in e for e in errors), errors)

    def test_a_project_field_rename_is_honoured(self):
        """A project that calls Priority something else still validates against it."""
        field_map = dict(_FIELD_MAP)
        field_map['Severity'] = field_map.pop('Priority')
        errors, _, plans = wf_core.validate_spec(
            [_entry()], field_map, _TYPE_MAP, {'field-priority': 'Severity'})
        self.assertEqual(errors, [])
        self.assertIn('Severity', plans[0]['fields'])


class TestFieldValueInput(unittest.TestCase):
    """The value key depends on the field's data type, not the value's shape."""

    def test_each_data_type_uses_its_own_key(self):
        cases = [
            ({'id': 'f', 'data_type': 'date'}, '2026-01-01',
             {'fieldId': 'f', 'dateValue': '2026-01-01'}),
            ({'id': 'f', 'data_type': 'text'}, 'note',
             {'fieldId': 'f', 'textValue': 'note'}),
            ({'id': 'f', 'data_type': 'number'}, 3,
             {'fieldId': 'f', 'numberValue': 3.0}),
        ]
        for meta, value, expected in cases:
            shaped, err = wf_core.field_value_input(meta, value)
            self.assertEqual(err, None)
            self.assertEqual(shaped, expected)

    def test_a_single_select_refuses_two_values(self):
        meta = {'id': 'f', 'data_type': 'single-select',
                'options': {'A': 'a', 'B': 'b'}}
        _, err = wf_core.field_value_input(meta, ['A', 'B'])
        self.assertIn('exactly one', err)

    def test_a_multi_select_accepts_a_bare_string(self):
        meta = {'id': 'f', 'data_type': 'multi-select', 'options': {'A': 'a'}}
        shaped, err = wf_core.field_value_input(meta, 'A')
        self.assertEqual(err, None)
        self.assertEqual(shaped, {'fieldId': 'f', 'multiSelectOptionIds': ['a']})


class TestSpecCycles(unittest.TestCase):
    """A cycle cannot be applied; finding it half-way through is much worse."""

    def test_a_two_entry_cycle_is_reported(self):
        entries = [{'key': 'a', 'blocked_by': ['b']},
                   {'key': 'b', 'blocked_by': ['a']}]
        self.assertEqual(len(wf_core.spec_cycles(entries)), 1)

    def test_a_chain_is_not_a_cycle(self):
        entries = [{'key': 'a', 'blocked_by': ['b']},
                   {'key': 'b', 'blocked_by': ['c']},
                   {'key': 'c'}]
        self.assertEqual(wf_core.spec_cycles(entries), [])

    def test_a_reference_outside_the_spec_is_not_a_cycle(self):
        """An existing issue number is a real dependency, not this spec's problem."""
        entries = [{'key': 'a', 'blocked_by': [187]}]
        self.assertEqual(wf_core.spec_cycles(entries), [])


class TestSpecLevels(unittest.TestCase):
    """Aliases cannot reference each other, so parents must land a request early."""

    def test_a_tree_splits_into_one_level_per_generation(self):
        entries = [{'key': 'epic'}, {'key': 'f1', 'parent': 'epic'},
                   {'key': 's1', 'parent': 'f1'}]
        levels, unplaceable = wf_core.spec_levels(entries)
        self.assertEqual([[e['key'] for e in l] for l in levels],
                         [['epic'], ['f1'], ['s1']])
        self.assertEqual(unplaceable, [])

    def test_siblings_share_a_level_so_they_share_a_request(self):
        entries = [{'key': 'epic'}, {'key': 'a', 'parent': 'epic'},
                   {'key': 'b', 'parent': 'epic'}]
        levels, _ = wf_core.spec_levels(entries)
        self.assertEqual(len(levels), 2)
        self.assertEqual([e['key'] for e in levels[1]], ['a', 'b'])

    def test_a_parent_outside_the_spec_is_a_root_here(self):
        """An existing epic already has a node id; nothing has to be created first."""
        levels, _ = wf_core.spec_levels([{'key': 'a', 'parent': 186}])
        self.assertEqual(len(levels), 1)

    def test_an_existing_issue_can_parent_a_new_one_within_the_spec(self):
        entries = [{'number': 42}, {'key': 'child', 'parent': 42}]
        levels, _ = wf_core.spec_levels(entries)
        self.assertEqual([[e.get('key') or e['number'] for e in l] for l in levels],
                         [[42], ['child']])

    def test_a_parent_cycle_is_reported_rather_than_looped_over(self):
        entries = [{'key': 'a', 'parent': 'b'}, {'key': 'b', 'parent': 'a'}]
        levels, unplaceable = wf_core.spec_levels(entries)
        self.assertEqual(levels, [])
        self.assertEqual(len(unplaceable), 2)


class TestBatchEntries(unittest.TestCase):
    """The node cap is a named constant, and it actually splits."""

    def test_a_level_within_the_cap_is_one_request(self):
        items = list(range(wf_core.BATCH_MAX_NODES))
        self.assertEqual(len(wf_core.batch_entries(items)), 1)

    def test_one_over_the_cap_becomes_two_requests(self):
        items = list(range(wf_core.BATCH_MAX_NODES + 1))
        chunks = wf_core.batch_entries(items)
        self.assertEqual(len(chunks), 2)
        self.assertEqual(sum(len(c) for c in chunks), len(items))


# ── issue audit ──────────────────────────────────────────────────────────────

_AUDIT_FIELDS = {'Priority': {}, 'Effort': {}, 'Classification': {},
                 'Origin': {}, 'Ownership': {}}


def _node(**over):
    issue = {'number': 5, 'title': 'A story', 'body': '',
             'issueType': {'name': 'User Story'},
             'labels': {'nodes': []}, 'blockedBy': {'nodes': []},
             'issueFieldValues': {'nodes': []}}
    issue.update(over)
    return issue


def _field_value(name, value):
    if isinstance(value, list):
        return {'field': {'name': name}, 'options': [{'name': v} for v in value]}
    return {'field': {'name': name}, 'name': value}


def _kinds(result):
    return [g['kind'] for g in result['gaps']]


class TestDeclaredKind(unittest.TestCase):
    """What an issue says it is, as opposed to what GitHub has it typed as."""

    def test_a_type_label_wins_over_the_title(self):
        kind, source = wf_core.declared_kind('[STORY] a thing', ['type-bug'], {})
        self.assertEqual((kind, source), ('bug', 'label'))

    def test_a_title_prefix_is_read_when_there_is_no_label(self):
        self.assertEqual(wf_core.declared_kind('[DEBT] tidy up', [], {}),
                         ('tech debt', 'title'))

    def test_an_unknown_prefix_claims_nothing(self):
        self.assertEqual(wf_core.declared_kind('[WIP] a thing', [], {}),
                         (None, None))

    def test_a_renamed_label_still_resolves(self):
        kind, _ = wf_core.declared_kind('x', ['kind/bug'], {'type-bug': 'kind/bug'})
        self.assertEqual(kind, 'bug')


class TestAuditIssue(unittest.TestCase):
    """The audit reads and proposes. It must never decide to write."""

    def test_a_fully_classified_issue_has_no_gaps(self):
        issue = _node(issueFieldValues={'nodes': [
            _field_value('Priority', 'High'), _field_value('Effort', 'Medium'),
            _field_value('Classification', ['New Feature']),
            _field_value('Origin', 'Development'),
            _field_value('Ownership', 'Code agent')]})
        self.assertEqual(_kinds(wf_core.audit_issue(issue, _AUDIT_FIELDS)), [])

    def test_an_untyped_issue_is_a_gap(self):
        result = wf_core.audit_issue(_node(issueType=None), {})
        self.assertEqual(_kinds(result), ['missing-type'])

    def test_every_org_field_with_no_value_is_a_gap(self):
        """Five gaps, in two kinds: the three the picker reads are
        `missing-field`, and the two nothing selects on are
        `missing-optional-field` so a report can tell them apart."""
        result = wf_core.audit_issue(_node(), _AUDIT_FIELDS)
        self.assertEqual(_kinds(result),
                         ['missing-field'] * 3 + ['missing-optional-field'] * 2)

    def test_ownership_comes_from_the_prefix_and_nothing_else(self):
        """The prefix is written by this workflow and means one thing, so it
        is read back. Its absence means nothing: an unprefixed title used to be
        proposed as `Code agent`, which is wrong in the one direction that
        matters -- work that needs a person, handed to an agent that cannot
        finish it. A label never decides it either way."""
        unknown = wf_core.audit_issue(_node(), _AUDIT_FIELDS)
        self.assertEqual(unknown['proposed']['fields']['field-ownership'],
                         wf_core.SPEC_PLACEHOLDER)
        human = wf_core.audit_issue(_node(title='[Manual] rotate the key'),
                                    _AUDIT_FIELDS)
        self.assertEqual(human['proposed']['fields']['field-ownership'], 'Human')
        browser = wf_core.audit_issue(_node(title='[Browser] turn on the API'),
                                      _AUDIT_FIELDS)
        self.assertEqual(browser['proposed']['fields']['field-ownership'],
                         'Browser agent')
        labelled = wf_core.audit_issue(
            _node(labels={'nodes': [{'name': 'human-required'}]}), _AUDIT_FIELDS)
        self.assertEqual(labelled['proposed']['fields']['field-ownership'],
                         wf_core.SPEC_PLACEHOLDER)

    def test_an_unowned_issue_is_reported_once_not_twice(self):
        """`missing-field` already says Ownership is empty; `scope-unowned`
        saying it again made every unowned issue look like two problems."""
        result = wf_core.audit_issue(_node(), _AUDIT_FIELDS)
        self.assertNotIn('scope-unowned', _kinds(result))

    def test_a_field_the_org_does_not_define_is_not_a_gap(self):
        """The audit reports against the org's real shape, not a wish list."""
        result = wf_core.audit_issue(_node(), {'Priority': {}})
        self.assertEqual(_kinds(result), ['missing-field'])

    def test_a_native_type_contradicting_the_label_is_a_gap(self):
        issue = _node(labels={'nodes': [{'name': 'type-bug'}]})
        result = wf_core.audit_issue(issue, {})
        self.assertEqual(_kinds(result), ['type-contradiction'])
        self.assertIn('Bug', result['gaps'][0]['detail'])

    def test_a_debt_issue_typed_feature_is_caught_in_the_classification(self):
        """GitHub's five types cannot express tech debt; Classification can."""
        issue = _node(title='[DEBT] tidy up', issueType={'name': 'Feature'},
                       issueFieldValues={'nodes': [
                           _field_value('Classification', ['New Feature'])]})
        result = wf_core.audit_issue(issue, {'Classification': {}})
        self.assertEqual(_kinds(result), ['classification-contradiction'])
        self.assertIn('New Feature', result['gaps'][0]['detail'])
        self.assertIn('tech debt', result['gaps'][0]['detail'])

    def test_a_classification_that_is_merely_not_the_default_is_not_a_gap(self):
        """`New Feature` is a story's default, not the only thing it may be.

        Comparing against the default alone reported every deliberate choice as
        a contradiction — eleven findings on one real backlog, all eleven wrong.
        """
        for value in ('Enhancement', 'Documentation', 'Integration', 'Chore',
                      'Performance', 'Accessibility', 'Spike'):
            issue = _node(title='[STORY] do the thing',
                          issueType={'name': 'User Story'},
                          issueFieldValues={'nodes': [
                              _field_value('Classification', [value])]})
            result = wf_core.audit_issue(issue, {'Classification': {}})
            self.assertEqual(_kinds(result), [], '%s should be allowed on a story' % value)

    def test_debt_may_say_which_area_it_is_debt_in(self):
        """Accessibility debt, documentation debt and security debt are all real.

        Four such issues on one live backlog were reported as contradictions
        because the check compared against `Tech Debt` and nothing else.
        """
        for value in ('Accessibility', 'Documentation', 'Security', 'Performance'):
            issue = _node(title='[DEBT] tidy up', issueType={'name': 'Chore'},
                          issueFieldValues={'nodes': [
                              _field_value('Classification', [value])]})
            result = wf_core.audit_issue(issue, {'Classification': {}}, type_capable=True,
                                         type_map={'Chore': 'IT_chore'})
            self.assertEqual(_kinds(result), [], '%s should be allowed on debt' % value)

    def test_a_bug_classified_as_new_capability_is_a_gap(self):
        issue = _node(title='[BUG] it breaks', issueType={'name': 'Bug'},
                      issueFieldValues={'nodes': [
                          _field_value('Classification', ['New Feature'])]})
        result = wf_core.audit_issue(issue, {'Classification': {}})
        self.assertEqual(_kinds(result), ['classification-contradiction'])

    def test_a_story_classified_as_a_defect_is_still_a_gap(self):
        """Narrowing the check must not silence the pairing it exists for."""
        issue = _node(title='[STORY] do the thing', issueType={'name': 'User Story'},
                      issueFieldValues={'nodes': [
                          _field_value('Classification', ['Regression'])]})
        result = wf_core.audit_issue(issue, {'Classification': {}})
        self.assertEqual(_kinds(result), ['classification-contradiction'])

    def test_the_body_cannot_claim_a_dependency(self):
        """Prose is not a dependency. The audit used to read it and propose an
        edge from it, and on one real backlog it both missed a heading-style
        section and read "this **was** blocked by #980" as a live blocker. The
        edge is the only record now, so there is nothing here to disagree with
        it."""
        issue = _node(body='## Dependencies\n\nBlocked by #3\n')
        result = wf_core.audit_issue(issue, {}, open_numbers={3, 5})
        self.assertEqual(_kinds(result), [])
        self.assertNotIn('blocked_by', result['proposed'])

    def test_an_edge_that_already_exists_is_not_reported(self):
        issue = _node(body='Blocked by #3', blockedBy={'nodes': [{'number': 3}]})
        result = wf_core.audit_issue(issue, {}, open_numbers={3, 5})
        self.assertEqual(_kinds(result), [])

    def test_a_priority_label_does_not_propose_a_priority(self):
        """Labels decide nothing since 10.0.0. Reading one here would let a
        label somebody set months ago write the field the picker orders on."""
        issue = _node(labels={'nodes': [{'name': 'priority-high'}]})
        result = wf_core.audit_issue(issue, {'Priority': {}})
        self.assertEqual(result['proposed']['fields']['field-priority'],
                         wf_core.SPEC_PLACEHOLDER)

    def test_what_cannot_be_inferred_becomes_a_placeholder(self):
        """Silence must not pass: `issue-apply` refuses the spec until it is filled."""
        result = wf_core.audit_issue(_node(), _AUDIT_FIELDS)
        fields = result['proposed']['fields']
        self.assertEqual(fields['field-effort'], wf_core.SPEC_PLACEHOLDER)
        self.assertEqual(fields['field-origin'], wf_core.SPEC_PLACEHOLDER)

    def test_a_situational_field_is_not_a_gap(self):
        """A start date nobody set is not missing metadata.

        The backfill has never proposed a value for one, so reporting it only
        ensured a fully classified backlog could never come back clean — 275
        such findings across 69 issues on one real repo.
        """
        result = wf_core.audit_issue(_node(), {'Start date': {}, 'Target date': {}})
        self.assertEqual(_kinds(result), [])
        self.assertNotIn('fields', result['proposed'])

    def test_a_fully_classified_issue_reports_no_gaps(self):
        """The whole point of an audit is that it can come back clean."""
        issue = _node(title='[BUG] it breaks', issueType={'name': 'Bug'},
                      issueFieldValues={'nodes': [
                          _field_value('Priority', 'High'),
                          _field_value('Effort', 'Medium'),
                          _field_value('Classification', ['Bug Fix']),
                          _field_value('Origin', 'Development'),
                          _field_value('Ownership', 'Code agent')]})
        result = wf_core.audit_issue(issue, dict(_AUDIT_FIELDS, **{
            'Start date': {}, 'Target date': {}}))
        self.assertEqual(_kinds(result), [])

    def test_the_proposed_entry_is_a_valid_apply_spec_once_filled(self):
        result = wf_core.audit_issue(_node(title='[BUG] it breaks'), _AUDIT_FIELDS)
        entry = result['proposed']
        entry['fields'] = dict(entry['fields'], **{'field-priority': 'High',
                                                   'field-effort': 'Medium',
                                                   'field-origin': 'Development',
                                                   'field-ownership': 'Code agent'})
        field_map = {
            'Priority': {'id': 'p', 'data_type': 'single-select',
                         'options': {'High': 'o1'}},
            'Effort': {'id': 'e', 'data_type': 'single-select',
                       'options': {'Medium': 'o2'}},
            'Classification': {'id': 'c', 'data_type': 'multi-select',
                               'options': {'Bug Fix': 'o3'}},
            'Origin': {'id': 'o', 'data_type': 'single-select',
                       'options': {'Development': 'o4'}},
            'Ownership': {'id': 'w', 'data_type': 'single-select',
                          'options': {'Code agent': 'o5'}},
        }
        errors, _, _ = wf_core.validate_spec([entry], field_map, {'Bug': 'IT_bug'})
        self.assertEqual(errors, [])

    def test_the_spec_before_filling_is_refused(self):
        """The placeholder is the whole mechanism, so assert it actually refuses."""
        result = wf_core.audit_issue(_node(), _AUDIT_FIELDS)
        field_map = {'Effort': {'id': 'e', 'data_type': 'single-select',
                                'options': {'Medium': 'o2'}}}
        errors, _, _ = wf_core.validate_spec([result['proposed']], field_map, {})
        self.assertTrue(any('Effort' in e for e in errors), errors)


class TestAuditSummary(unittest.TestCase):

    def test_counts_by_kind_and_by_node(self):
        audited = [{'gaps': [{'kind': 'missing-type'}, {'kind': 'missing-field'}]},
                   {'gaps': [{'kind': 'missing-field'}]},
                   {'gaps': []}]
        self.assertEqual(wf_core.audit_summary(audited),
                         {'issues_scanned': 3, 'issues_with_gaps': 2,
                          'gaps': {'missing-type': 1, 'missing-field': 2}})


# ── preflight: configuration and label drift ─────────────────────────────────

_ALL_SECTIONS = list(wf_core.REQUIRED_CONFIG_SECTIONS)


def _levels(findings):
    return [f['level'] for f in findings]


def _checks(findings):
    return [f['check'] for f in findings]


class TestConfigSections(unittest.TestCase):

    def test_a_complete_config_has_no_findings(self):
        self.assertEqual(wf_core.config_section_findings(_ALL_SECTIONS), [])

    def test_a_missing_section_fails_and_names_itself(self):
        """The case that must be caught: the section the field tooling reads."""
        present = [h for h in _ALL_SECTIONS if h != 'Issue Types & Fields']
        findings = wf_core.config_section_findings(present)
        self.assertEqual(_levels(findings), [wf_core.CRITICAL])
        self.assertIn('Issue Types & Fields', findings[0]['detail'])
        self.assertIn('setup', findings[0]['fix'])
        self.assertEqual(findings[0]['where'], 'ClaudeProject.md')

    def test_an_authoring_qualifier_still_counts_as_present(self):
        """The template writes `## Project Board (optional)`; that is the section."""
        headings = ['%s (optional)' % h for h in _ALL_SECTIONS]
        self.assertEqual(wf_core.config_section_findings(headings), [])

    def test_every_missing_section_is_reported_separately(self):
        findings = wf_core.config_section_findings([])
        self.assertEqual(len(findings), len(_ALL_SECTIONS))


class TestScanLabelReferences(unittest.TestCase):
    """What an instruction file actually tells an agent to apply."""

    def test_a_literal_label_is_a_reference(self):
        found = wf_core.scan_label_references('gh issue edit 1 --add-label status-ready')
        self.assertEqual(found, [{'label': 'status-ready', 'line': 1}])

    def test_every_label_flag_shape_is_read(self):
        text = ('a --label alpha-one\n'
                'b --add-label "beta-two"\n'
                "c --remove-label 'gamma-three'\n"
                'd --add-label=delta-four\n')
        self.assertEqual([f['label'] for f in wf_core.scan_label_references(text)],
                         ['alpha-one', 'beta-two', 'gamma-three', 'delta-four'])

    def test_a_comma_separated_list_is_split(self):
        found = wf_core.scan_label_references('x --add-label "type-bug,priority-high"')
        self.assertEqual([f['label'] for f in found], ['type-bug', 'priority-high'])

    def test_trailing_prose_punctuation_is_not_part_of_the_name(self):
        found = wf_core.scan_label_references('apply `gh pr edit --add-label status-in-review`.')
        self.assertEqual([f['label'] for f in found], ['status-in-review'])

    def test_a_placeholder_is_not_a_claim_about_any_label(self):
        """These files say "the label you resolved" in three different ways."""
        text = ('a --add-label "{status_ready_label}"\n'
                'b --remove-label <verdict-label>\n'
                'c --add-label {review-state-label}\n'
                'd --add-label X\n')
        self.assertEqual(wf_core.scan_label_references(text), [])

    def test_the_line_is_reported_so_the_fix_is_one_click_away(self):
        found = wf_core.scan_label_references('\n\ngh issue edit --add-label type-bug')
        self.assertEqual(found[0]['line'], 3)


class TestLabelReferenceFindings(unittest.TestCase):

    def _ref(self, label, file='skills/bulk-execute/references/set-selection.md'):
        return {'file': file, 'label': label, 'line': 42}

    def test_a_retired_label_fails(self):
        """The named case: a call site still applying a label the repo dropped."""
        findings = wf_core.label_reference_findings(
            [self._ref('status-ready')], ['status-in-progress'])
        self.assertEqual(_levels(findings), [wf_core.CRITICAL])
        self.assertIn('set-selection.md', findings[0]['detail'])
        self.assertIn('status-ready', findings[0]['detail'])
        self.assertTrue(findings[0]['where'].endswith(':42'))

    def test_a_label_the_repo_has_is_not_reported(self):
        self.assertEqual(wf_core.label_reference_findings(
            [self._ref('status-ready')], ['status-ready']), [])

    def test_a_renamed_purpose_key_is_named_in_the_finding(self):
        """Hard-coding the default is wrong on a project that renamed it."""
        findings = wf_core.label_reference_findings(
            [self._ref('status-ready')], ['ready'], {'status-ready': 'ready'})
        self.assertIn('maps `status-ready` to `ready`', findings[0]['detail'])

    def test_one_finding_per_file_and_label(self):
        refs = [self._ref('status-ready'), self._ref('status-ready'),
                self._ref('status-ready', 'commands/other.md')]
        self.assertEqual(len(wf_core.label_reference_findings(refs, [])), 2)


class TestConfigLabelFindings(unittest.TestCase):

    def test_a_mapped_label_the_repo_lacks_fails(self):
        findings = wf_core.config_label_findings(
            {'claude-ready': 'claude-ready'}, {}, ['type-bug'])
        self.assertEqual(_levels(findings), [wf_core.CRITICAL])
        self.assertIn('claude-ready', findings[0]['detail'])

    def test_review_labels_are_checked_against_their_own_file(self):
        findings = wf_core.config_label_findings(
            {}, {'review-approved': 'approved'}, [])
        self.assertIn('review.config.md', findings[0]['detail'])

    def test_a_fully_present_map_is_clean(self):
        self.assertEqual(wf_core.config_label_findings(
            {'type-bug': 'type-bug'}, {'review-approved': 'review-approved'},
            ['type-bug', 'review-approved']), [])


class TestLabelDriftFindings(unittest.TestCase):

    def test_a_separator_that_drifted_is_a_warning(self):
        findings = wf_core.label_drift_findings(['type-bug', 'type:bug'])
        self.assertEqual(_levels(findings), [wf_core.WARNING])
        self.assertIn('type:bug', findings[0]['detail'])

    def test_a_pair_of_retired_labels_is_not_drift(self):
        """`label-retired` owns these, and its advice is the opposite: take
        them off. Drift's advice -- consolidate onto one of the pair -- would
        have a person tidying up two labels that should both go."""
        self.assertEqual(
            wf_core.label_drift_findings(['priority-medium', 'priority:medium']),
            [])

    def test_a_dropped_prefix_is_a_warning(self):
        findings = wf_core.label_drift_findings(['blocked', 'status-blocked'])
        self.assertEqual(_checks(findings), ['label-drift'])
        self.assertIn('status-blocked', findings[0]['fix'])

    def test_a_retired_label_still_drifts_while_it_is_on_real_issues(self):
        """`status-ready` left the map in 9.0.0 and every other status label
        followed in 10.0.0, but a project part-way through the migration still
        carries them. Nothing reads either name, so this decides nothing — it
        is a warning because a person filtering the issues list by hand sees
        one of the pair and thinks they are seeing all of it."""
        findings = wf_core.label_drift_findings(['ready', 'status-ready'])
        self.assertEqual(_checks(findings), ['label-drift'])

    def test_drift_never_fails_because_the_fix_deletes_data(self):
        findings = wf_core.label_drift_findings(
            ['blocked', 'status-blocked', 'priority:high', 'priority-high'])
        self.assertEqual(set(_levels(findings)), {wf_core.WARNING})

    def test_two_labels_that_only_look_alike_are_left_alone(self):
        self.assertEqual(wf_core.label_drift_findings(
            ['status-blocked', 'status-parked', 'documentation']), [])


class TestPinnedFieldFindings(unittest.TestCase):
    """A value written to an unpinned field is stored and then never shown."""

    _REQUIRED = ['Priority', 'Effort', 'Classification', 'Origin']

    def _type(self, name, pinned, enabled=True):
        return {'name': name, 'enabled': enabled, 'pinned': list(pinned)}

    def test_a_type_missing_a_field_the_tooling_writes_fails(self):
        findings = wf_core.pinned_field_findings(
            [self._type('Bug', ['Priority', 'Effort', 'Classification'])],
            self._REQUIRED)
        self.assertEqual(_levels(findings), [wf_core.CRITICAL])
        self.assertIn('Origin', findings[0]['detail'])

    def test_the_fix_names_the_type_and_where_to_pin_it(self):
        findings = wf_core.pinned_field_findings(
            [self._type('Bug', [])], self._REQUIRED)
        self.assertIn('`Bug`', findings[0]['fix'])
        self.assertIn('Pin to issues', findings[0]['fix'])
        self.assertIn('Planning', findings[0]['fix'])

    def test_a_disabled_type_is_not_checked(self):
        """A type nobody can pick cannot hold a wrong value."""
        self.assertEqual(wf_core.pinned_field_findings(
            [self._type('Task', [], enabled=False)], self._REQUIRED), [])

    def test_asymmetry_warns_and_does_not_fail(self):
        """A field one type carries and another does not is soft, not fatal."""
        findings = wf_core.pinned_field_findings(
            [self._type('User Story', self._REQUIRED + ['Team']),
             self._type('Epic', self._REQUIRED)], self._REQUIRED)
        self.assertEqual(_levels(findings), [wf_core.WARNING])
        self.assertEqual(findings[0]['check'], 'pin-asymmetry')
        self.assertIn('`Team`', findings[0]['detail'])
        self.assertIn('`Epic`', findings[0]['detail'])

    def test_a_correctly_pinned_org_is_clean(self):
        findings = wf_core.pinned_field_findings(
            [self._type('Bug', self._REQUIRED),
             self._type('Epic', self._REQUIRED)], self._REQUIRED)
        self.assertEqual(findings, [])


class TestTypedIssueWriteShape(unittest.TestCase):
    """What the native type makes redundant on the way in.

    A typed issue said it was a bug four times over -- the `[BUG]` prefix, the
    native type, the `bug` label and the `Classification` field. These take the
    duplicates back out at the one place that writes an issue.
    """

    def test_a_type_label_is_dropped_and_the_rest_kept_in_order(self):
        kept, dropped = wf_core.strip_type_labels(
            ['priority-high', 'type-bug', 'status-parked'])
        self.assertEqual(kept, ['priority-high', 'status-parked'])
        self.assertEqual(dropped, ['type-bug'])

    def test_a_renamed_type_label_is_dropped_too(self):
        kept, dropped = wf_core.strip_type_labels(
            ['kind/bug', 'P1'], {'type-bug': 'kind/bug'})
        self.assertEqual(kept, ['P1'])
        self.assertEqual(dropped, ['kind/bug'])

    def test_a_purpose_key_is_dropped_like_the_literal_name(self):
        """A spec may name either; both mean the same thing."""
        kept, _ = wf_core.strip_type_labels(['type-story', 'claude-authored'])
        self.assertEqual(kept, ['claude-authored'])

    def test_labels_with_no_type_among_them_are_untouched(self):
        labels = ['priority-low', 'status-parked']
        kept, dropped = wf_core.strip_type_labels(labels)
        self.assertEqual(kept, labels)
        self.assertEqual(dropped, [])

    def test_a_kind_prefix_is_stripped_from_the_title(self):
        self.assertEqual(wf_core.strip_title_prefix('[BUG] Crash on save'),
                         'Crash on save')
        self.assertEqual(wf_core.strip_title_prefix('[DEBT]   Stale docs'),
                         'Stale docs')

    def test_a_bracket_that_is_not_a_kind_is_left_alone(self):
        """Editing somebody's title on a guess is worse than a long title."""
        for title in ('[v2] Rewrite the parser', '[iOS] Keyboard overlaps',
                      'Plain title', ''):
            with self.subTest(title=title):
                self.assertEqual(wf_core.strip_title_prefix(title), title)

    def test_the_manual_prefix_survives(self):
        """`[Manual]` says a person has to finish it, which no field records.

        The title is the only place it can live, so stripping it would erase
        the one marker that keeps such an issue visible.
        """
        for title in ('[Manual] Grant the app access to the org',
                      '[manual] Rotate the signing key',
                      '[MANUAL] Approve the store submission'):
            with self.subTest(title=title):
                self.assertEqual(wf_core.strip_title_prefix(title), title)
        self.assertNotIn('MANUAL', wf_core.TITLE_PREFIX_KINDS)

    def test_the_manual_prefix_is_not_a_declared_kind(self):
        """It says who does the work, not what kind of work it is."""
        kind, source = wf_core.declared_kind('[Manual] Grant access', [])
        self.assertIsNone(kind)
        self.assertIsNone(source)


class TestDeprecatedLabelFindings(unittest.TestCase):
    """Label-map rows for labels that outlived whatever read them.

    `TestUnmappedLabelFindings` used to sit beside this one, checking that a
    project whose repo carried `status:parked` while its map had no
    `status-parked` row was reported -- because the picker would resolve the
    purpose key to a default that matched nothing and quietly keep a parked
    issue in the pool. No label resolves into a filter any more, so there is no
    silent failure left to catch and the check went with it.
    """

    def test_a_mapped_type_label_is_reported_once(self):
        findings = wf_core.deprecated_label_findings(
            {'type-bug': 'bug', 'type-story': 'story'}, ['bug', 'story'])
        self.assertEqual(_levels(findings), [wf_core.WARNING])
        self.assertEqual(findings[0]['check'], 'label-deprecated')
        self.assertIn('type-bug', findings[0]['detail'])
        self.assertIn('type-story', findings[0]['detail'])

    def test_a_mapped_status_label_is_reported_too(self):
        """The 10.0.0 addition: `status-*` joined `type-*` in being read by
        nothing, because the board column is the state."""
        findings = wf_core.deprecated_label_findings(
            {'status-blocked': 'blocked'}, ['blocked'])
        self.assertEqual(_levels(findings), [wf_core.WARNING])
        self.assertIn('status-blocked', findings[0]['detail'])

    def test_the_scope_and_priority_rows_are_reported(self):
        for purpose in ('scope-human', 'priority-high', 'needs-refinement',
                        'status-ready'):
            with self.subTest(purpose=purpose):
                findings = wf_core.deprecated_label_findings(
                    {purpose: 'whatever'}, ['whatever'])
                self.assertEqual(len(findings), 1)
                self.assertIn(purpose, findings[0]['detail'])

    def test_the_fix_does_not_ask_anyone_to_delete_a_live_label(self):
        """Deleting a label removes it from every issue carrying it, which is a
        data loss no config check should ask for."""
        findings = wf_core.deprecated_label_findings(
            {'status-blocked': 'blocked'}, ['blocked'])
        self.assertIn('label map', findings[0]['fix'])
        self.assertIn('every issue that carries it', findings[0]['fix'])

    def test_a_label_map_with_only_live_rows_is_clean(self):
        self.assertEqual(wf_core.deprecated_label_findings(
            {'claude-authored': 'by-claude'}, ['by-claude']), [])

    def test_a_stray_retired_label_nobody_maps_is_not_a_finding(self):
        """Nothing reads it, so it is clutter rather than a trap."""
        self.assertEqual(wf_core.deprecated_label_findings(
            {}, ['type-bug', 'status-blocked']), [])


class TestUnmappedFieldFindings(unittest.TestCase):

    def test_an_org_field_no_purpose_key_maps_warns(self):
        findings = wf_core.unmapped_field_findings(['Priority', 'Team'])
        self.assertEqual(_levels(findings), [wf_core.WARNING])
        self.assertIn('Team', findings[0]['detail'])

    def test_a_renamed_field_the_project_mapped_is_clean(self):
        self.assertEqual(wf_core.unmapped_field_findings(
            ['Urgency'], {'field-priority': 'Urgency'}), [])


class TestBoardColumnFindings(unittest.TestCase):

    def test_a_stale_option_id_warns(self):
        findings = wf_core.board_column_findings(
            {'col-in-progress': 'dead1234'}, {'47fc9ee4': 'In Progress'})
        self.assertEqual(_levels(findings), [wf_core.WARNING])
        self.assertIn('col-in-progress', findings[0]['detail'])

    def test_a_live_option_id_is_clean(self):
        self.assertEqual(wf_core.board_column_findings(
            {'col-in-progress': '47fc9ee4'}, {'47fc9ee4': 'In Progress'}), [])


class TestPreflightSummary(unittest.TestCase):

    def test_counts_by_level_and_by_check(self):
        findings = [wf_core.finding(wf_core.CRITICAL, 'config-section', 'd', 'f'),
                    wf_core.finding(wf_core.WARNING, 'label-drift', 'd', 'f'),
                    wf_core.finding(wf_core.WARNING, 'label-drift', 'd', 'f')]
        self.assertEqual(wf_core.preflight_summary(findings),
                         {'critical': 1, 'warning': 2,
                          'checks': {'config-section': 1, 'label-drift': 2}})



# -- duplicate detection ------------------------------------------------------

class TestSelectSiblingPrs(unittest.TestCase):
    """One definition of "duplicate" for every site that asks."""

    def _pr(self, number, closes, head='feat/x', **kw):
        node = {'number': number, 'title': 'pr %d' % number,
                'url': 'u%d' % number, 'headRefName': head, 'isDraft': False,
                'labels': {'nodes': [{'name': 'review-needs-review'}]},
                'closingIssuesReferences': {'nodes': [{'number': n} for n in closes]}}
        node.update(kw)
        return node

    def test_only_the_prs_that_close_the_issue_are_returned(self):
        nodes = [self._pr(1, [42]), self._pr(2, [7]), self._pr(3, [9, 42])]
        found = wf_core.select_sibling_prs(nodes, 42)
        self.assertEqual([p['number'] for p in found], [1, 3])

    def test_the_order_is_the_query_order_so_the_tie_break_is_deterministic(self):
        nodes = [self._pr(5, [42]), self._pr(2, [42])]
        self.assertEqual([p['number'] for p in wf_core.select_sibling_prs(nodes, 42)],
                         [5, 2])

    def test_your_own_pr_is_not_a_duplicate_of_itself(self):
        nodes = [self._pr(1, [42], head='feat/42-mine'),
                 self._pr(2, [42], head='feat/42-theirs')]
        found = wf_core.select_sibling_prs(nodes, 42, exclude_branch='feat/42-mine')
        self.assertEqual([p['number'] for p in found], [2])

    def test_each_result_carries_enough_to_compare_without_another_query(self):
        found = wf_core.select_sibling_prs([self._pr(1, [42], isDraft=True)], 42)
        self.assertEqual(found[0]['draft'], True)
        self.assertEqual(found[0]['labels'], ['review-needs-review'])
        self.assertEqual(found[0]['head_ref'], 'feat/x')

    def test_a_pr_with_no_recognised_closing_reference_is_not_a_duplicate(self):
        """A body that says "closes #42" but GitHub never linked is a bug in
        that PR's body, not a duplicate to reconcile."""
        self.assertEqual(wf_core.select_sibling_prs(
            [self._pr(1, [])], 42), [])
        self.assertEqual(wf_core.select_sibling_prs(None, 42), [])



# -- claim reaping ------------------------------------------------------------

class TestReapVerdict(unittest.TestCase):
    """Reaping frees a lock. Getting it wrong lets two agents build one story,
    so the asymmetry between `reap` and `suspect` is the whole point."""

    REVIEWING = ('review-reviewing', 'review-updating')

    def _issue(self, state='OPEN', labels=(), age=9, **kw):
        kw.setdefault('assigned', True)
        return wf_core.reap_verdict('issue', age, state, list(labels), **kw)

    def _pr(self, state='OPEN', labels=(), age=9, **kw):
        return wf_core.reap_verdict(
            'pr', age, state, list(labels), review_labels=self.REVIEWING, **kw)

    def test_a_recent_claim_is_never_touched(self):
        """A young ref is what a healthy running session looks like."""
        verdict, reason = self._issue(state='CLOSED', age=1)
        self.assertEqual(verdict, wf_core.SKIP)
        self.assertIn('threshold', reason)

    def test_the_threshold_is_configurable(self):
        self.assertEqual(self._issue(state='CLOSED', age=6, threshold=8)[0],
                         wf_core.SKIP)
        self.assertEqual(self._issue(state='CLOSED', age=6, threshold=4)[0],
                         wf_core.REAP)

    def test_a_closed_issue_frees_its_claim(self):
        self.assertEqual(self._issue(state='CLOSED')[0], wf_core.REAP)

    def test_an_unassigned_issue_frees_its_claim(self):
        """`pick` assigns `@me`, so an unassigned issue is one nobody holds.

        This read a `status-in-progress` label until 10.0.0. The label stopped
        being applied when the state moved to the board, which would have made
        every healthy in-flight claim look abandoned."""
        verdict, reason = self._issue(assigned=False)
        self.assertEqual(verdict, wf_core.REAP)
        self.assertIn('assigned', reason)

    def test_no_label_on_an_issue_changes_its_reap_verdict(self):
        """Whatever an issue still carries from the label workflow, the claim
        is decided by the state, the assignment and the PR."""
        for stale in ('status-parked', 'status-blocked', 'status-in-progress',
                      'needs-refinement', 'claude-ready'):
            self.assertEqual(self._issue(labels=[stale])[0], wf_core.SUSPECT)
            self.assertEqual(self._issue(labels=[stale], assigned=False)[0],
                             wf_core.REAP)

    def test_an_issue_with_a_pr_already_open_frees_its_claim(self):
        """The PR is the ownership marker; the post-create release just
        did not run."""
        self.assertEqual(self._issue(has_open_pr=True)[0], wf_core.REAP)

    def test_an_assigned_issue_with_no_pr_is_suspect_not_reaped(self):
        """Indistinguishable from a slow but healthy session."""
        verdict, reason = self._issue()
        self.assertEqual(verdict, wf_core.SUSPECT)
        self.assertIn('no PR', reason)

    def test_a_merged_or_closed_pr_frees_its_claim(self):
        self.assertEqual(self._pr(state='MERGED')[0], wf_core.REAP)
        self.assertEqual(self._pr(state='CLOSED')[0], wf_core.REAP)

    def test_an_open_pr_with_no_review_under_way_frees_its_claim(self):
        self.assertEqual(self._pr(labels=['review-approved'])[0], wf_core.REAP)

    def test_an_open_pr_under_review_is_suspect(self):
        self.assertEqual(self._pr(labels=['review-reviewing'])[0], wf_core.SUSPECT)
        self.assertEqual(self._pr(labels=['review-updating'])[0], wf_core.SUSPECT)

    def test_an_unreadable_target_is_suspect_rather_than_reaped(self):
        """Not knowing is not evidence the work has moved on."""
        self.assertEqual(self._issue(state=None)[0], wf_core.SUSPECT)
        self.assertEqual(self._issue(age=None)[0], wf_core.SUSPECT)


class TestReapSummary(unittest.TestCase):

    def test_counts_every_verdict_including_the_absent_ones(self):
        results = [('issue-1', wf_core.REAP, ''), ('pr-2', wf_core.REAP, ''),
                   ('issue-3', wf_core.SUSPECT, '')]
        self.assertEqual(wf_core.reap_summary(results),
                         {'reaped': 2, 'suspect': 1, 'skipped': 0})


class TestBoardColumnNames(unittest.TestCase):

    def test_every_lifecycle_state_has_a_column(self):
        for key in ('col-backlog', 'col-in-progress', 'col-in-review',
                    'col-blocked', 'col-non-code', 'col-refinement',
                    'col-parked', 'col-attention', 'col-done'):
            self.assertIn(key, wf_core.BOARD_COLUMN_NAMES)

    def test_every_lane_but_done_is_one_setup_creates(self):
        """The board is the whole record of state, so a state with no lane is a
        state an issue cannot be put into. `Done` is excluded because a new
        board already has it."""
        self.assertEqual(sorted(wf_core.LANE_COLUMNS),
                         sorted(k for k in wf_core.BOARD_COLUMN_NAMES
                                if k != 'col-done'))
        self.assertNotIn('col-done', wf_core.LANE_COLUMNS)

    def test_the_pool_column_is_backlog(self):
        self.assertEqual(wf_core.POOL_COLUMN, 'col-backlog')
        self.assertNotIn('col-ready', wf_core.BOARD_COLUMN_NAMES)

    def test_each_key_resolves_to_the_name_the_rest_of_the_plugin_uses(self):
        """The values are the contract, not just the keys.

        `board_move` looks the column up on the live board by this name, so a
        value no board uses fails every move to that column, and fails
        quietly: a board mirrors the labels, so a failed move is never fatal.
        `col-backlog` read `Todo` for a long time, which is what GitHub calls
        the column on a new Projects v2 board rather than what
        `templates/default-labels.md`, the `ClaudeProject.md` template,
        `commands/report-issue.md` and the purpose key itself all call it.
        """
        self.assertEqual(wf_core.BOARD_COLUMN_NAMES, {
            'col-backlog':     'Backlog',
            'col-in-progress': 'In Progress',
            'col-in-review':   'In Review',
            'col-blocked':     'Blocked',
            'col-non-code':    'Non-code',
            'col-refinement':  'Needs refinement',
            'col-parked':      'Parked',
            'col-attention':   'Needs attention',
            'col-done':        'Done',
        })


class TestChoreIsMaintenance(unittest.TestCase):
    """A `Chore`-typed issue has to reach `execute mode=maintenance`.

    Typing tech debt as `Chore` on an org that has the type is the right
    answer and, on its own, silently emptied the maintenance pool: the
    filter only kept `Bug`.
    """

    TYPE_MAP = {1: 'Chore', 2: 'Bug', 3: 'User Story'}

    def test_chore_is_kept_in_maintenance_mode(self):
        candidates = [_issue(1, []), _issue(2, []), _issue(3, [])]
        result = filter_by_native_type(candidates, 'maintenance', self.TYPE_MAP)
        self.assertEqual([c['number'] for c in result], [1, 2])

    def test_chore_is_not_a_feature_candidate(self):
        result = filter_by_native_type([_issue(1, [])], 'feature', self.TYPE_MAP)
        self.assertEqual(result, [])

    def test_chore_needs_no_classification_to_qualify(self):
        """Unlike `Feature`, whose Classification decides."""
        result = filter_by_native_type([_issue(1, [])], 'maintenance',
                                       self.TYPE_MAP, {1: 'New Feature'})
        self.assertEqual([c['number'] for c in result], [1])


class TestNativeDependencyEdges(unittest.TestCase):
    """The `blockedBy` edges, which now decide whether an issue is blocked."""

    def test_edges_split_into_open_and_closed_keeping_order(self):
        edges = [{'number': 979, 'state': 'OPEN'},
                 {'number': 1311, 'state': 'CLOSED'},
                 {'number': 980, 'state': 'OPEN'}]
        self.assertEqual(wf_core.edge_states(edges), ([979, 980], [1311]))

    def test_a_repeated_edge_is_counted_once(self):
        edges = [{'number': 979, 'state': 'OPEN'}, {'number': 979, 'state': 'OPEN'}]
        self.assertEqual(wf_core.edge_states(edges), ([979], []))

    def test_an_edge_with_no_usable_number_is_dropped(self):
        edges = [{'number': None, 'state': 'OPEN'}, {'number': 7, 'state': 'CLOSED'}]
        self.assertEqual(wf_core.edge_states(edges), ([], [7]))

    def test_every_blocker_closed_releases_the_issue(self):
        verdict, open_numbers, closed = wf_core.unblock_verdict(
            [{'number': 1311, 'state': 'CLOSED'}])
        self.assertEqual(verdict, wf_core.UNBLOCK_RELEASE)
        self.assertEqual((open_numbers, closed), ([], [1311]))

    def test_one_open_blocker_holds_the_issue(self):
        verdict, open_numbers, closed = wf_core.unblock_verdict(
            [{'number': 979, 'state': 'OPEN'}, {'number': 1311, 'state': 'CLOSED'}])
        self.assertEqual(verdict, wf_core.UNBLOCK_HOLD)
        self.assertEqual((open_numbers, closed), ([979], [1311]))

    def test_no_edges_is_its_own_verdict_and_never_a_release(self):
        """The safety rule. Most issues labelled blocked with no edge are
        waiting on the world, not on an issue, and releasing them would put
        work no agent can do into the pool."""
        self.assertEqual(wf_core.unblock_verdict([])[0], wf_core.UNBLOCK_NO_EDGES)
        self.assertEqual(wf_core.unblock_verdict(None)[0], wf_core.UNBLOCK_NO_EDGES)

class TestPartialDelivery(unittest.TestCase):
    """The case no edge can describe: a blocker that shipped and stayed open."""

    NOW = datetime.datetime(2026, 9, 9, 12, 0, 0)

    def _pr(self, number, title, merged_at, state='MERGED'):
        return {'number': number, 'title': title, 'state': state,
                'mergedAt': merged_at}

    def test_a_title_reference_counts_as_delivery(self):
        prs = [self._pr(1372, 'Verify sign-in on the backend (#979, #980)',
                        '2026-09-09T09:31:43Z')]
        found = wf_core.recent_delivery(prs, 979, self.NOW)
        self.assertEqual(found, {'number': 1372,
                                 'merged_at': '2026-09-09T09:31:43Z'})

    def test_a_body_only_mention_does_not_count(self):
        """Tried against a real backlog this flagged ten of eleven held issues.
        Only the title is somebody saying the PR is about that issue."""
        prs = [self._pr(1375, 'Scope every issue to one party',
                        '2026-09-09T09:00:00Z')]
        self.assertIsNone(wf_core.recent_delivery(prs, 1176, self.NOW))

    def test_a_shorter_number_does_not_answer_for_a_longer_one(self):
        prs = [self._pr(1, 'Something (#97)', '2026-09-09T09:00:00Z')]
        self.assertIsNone(wf_core.recent_delivery(prs, 979, self.NOW))

    def test_a_longer_number_does_not_answer_for_a_shorter_one(self):
        prs = [self._pr(1, 'Something (#1979)', '2026-09-09T09:00:00Z')]
        self.assertIsNone(wf_core.recent_delivery(prs, 979, self.NOW))

    def test_an_old_merge_falls_outside_the_window(self):
        prs = [self._pr(900, 'Older work (#979)', '2026-07-01T09:00:00Z')]
        self.assertIsNone(wf_core.recent_delivery(prs, 979, self.NOW))

    def test_an_unmerged_pull_request_is_not_a_delivery(self):
        prs = [self._pr(1400, 'In flight (#979)', None, state='OPEN')]
        self.assertIsNone(wf_core.recent_delivery(prs, 979, self.NOW))

    def test_the_newest_qualifying_merge_wins(self):
        prs = [self._pr(1300, 'First half (#979)', '2026-09-02T09:00:00Z'),
               self._pr(1372, 'Second half (#979)', '2026-09-09T09:00:00Z')]
        self.assertEqual(wf_core.recent_delivery(prs, 979, self.NOW)['number'], 1372)


class TestWorkScope(unittest.TestCase):
    """Which of the three parties owns an issue, and what that costs it."""

    def test_the_ownership_field_names_the_owner(self):
        self.assertEqual(wf_core.issue_scope('Turn on the API', 'Browser agent'),
                         wf_core.SCOPE_BROWSER)
        self.assertEqual(wf_core.issue_scope('Device pass', 'Human'),
                         wf_core.SCOPE_HUMAN)
        self.assertEqual(wf_core.issue_scope('Add a setting', 'Code agent'),
                         wf_core.SCOPE_CODE)

    def test_the_title_prefix_answers_when_the_field_has_no_value(self):
        """Only then. It is the human-readable echo of the field, and reading
        it here is what lets `issue-audit` backfill a backlog written before
        the field existed."""
        self.assertEqual(wf_core.issue_scope('[Browser] Turn on the API'),
                         wf_core.SCOPE_BROWSER)
        self.assertEqual(wf_core.issue_scope('[Manual] Device pass'),
                         wf_core.SCOPE_HUMAN)

    def test_the_field_wins_over_the_prefix(self):
        self.assertEqual(
            wf_core.issue_scope('[Manual] Device pass', 'Code agent'),
            wf_core.SCOPE_CODE)

    def test_an_issue_with_neither_is_code_work(self):
        self.assertEqual(wf_core.issue_scope('Add a setting'),
                         wf_core.SCOPE_CODE)

    def test_a_scope_label_names_nothing_any_more(self):
        """`browser-agent` was the fallback until 10.0.0. It is inert."""
        self.assertEqual(wf_core.issue_scope('Turn on the API'),
                         wf_core.SCOPE_CODE)

    def test_non_code_wins_over_blocked(self):
        """A blocker closing never makes browser work pickable, so the lane it
        ends up in must be the one no sweep releases."""
        self.assertEqual(wf_core.board_column_for(wf_core.SCOPE_BROWSER, [979]),
                         'col-non-code')

    def test_code_work_with_an_open_edge_is_blocked(self):
        self.assertEqual(wf_core.board_column_for(wf_core.SCOPE_CODE, [979]),
                         'col-blocked')

    def test_code_work_with_nothing_open_goes_to_backlog(self):
        """Which is exactly what pickable means: the pool is that column."""
        self.assertEqual(wf_core.board_column_for(wf_core.SCOPE_CODE, []),
                         'col-backlog')

    def test_an_issue_nobody_owns_needs_refinement(self):
        """Not Backlog: the picker refuses an unowned issue, so a Backlog card
        with no owner is a card nothing will ever take."""
        self.assertEqual(wf_core.board_column_for(None, []), 'col-refinement')

    def test_an_explicit_state_wins_for_code_work(self):
        self.assertEqual(
            wf_core.board_column_for(wf_core.SCOPE_CODE, [979], 'col-parked'),
            'col-parked')

    def test_non_code_work_wins_even_over_an_explicit_state(self):
        """Non-code is what keeps it out of every agent's pool for good."""
        self.assertEqual(
            wf_core.board_column_for(wf_core.SCOPE_HUMAN, [], 'col-backlog'),
            'col-non-code')

    def test_a_spec_state_names_one_of_three_lanes(self):
        self.assertEqual(wf_core.spec_state_column('parked'),
                         ('col-parked', None))
        self.assertEqual(wf_core.spec_state_column(None), (None, None))
        key, err = wf_core.spec_state_column('ready')
        self.assertIsNone(key)
        self.assertIn('ready', err)


class TestMayPlaceCard(unittest.TestCase):
    """Which lanes `issue-apply` may move a card out of."""

    def test_no_card_or_no_lane_may_be_placed(self):
        self.assertEqual(wf_core.may_place_card(None), (True, None))
        self.assertEqual(wf_core.may_place_card(''), (True, None))

    def test_the_lanes_it_owns_may_be_rewritten(self):
        for lane in ('Backlog', 'Blocked', 'Non-code'):
            self.assertEqual(wf_core.may_place_card(lane), (True, None), lane)

    def test_a_lane_a_person_or_a_run_chose_is_kept(self):
        for lane in ('In Progress', 'In Review', 'Parked', 'Needs refinement',
                     'Needs attention', 'Done'):
            self.assertEqual(wf_core.may_place_card(lane), (False, lane), lane)

    def test_an_explicit_request_overrides_that(self):
        self.assertEqual(wf_core.may_place_card('In Progress', 'col-parked'),
                         (True, None))


class TestEdgeDiff(unittest.TestCase):

    def test_what_to_add_and_what_to_remove(self):
        self.assertEqual(wf_core.edge_diff([5, 6], [5, 7]), ([7], [6]))

    def test_an_empty_list_removes_everything(self):
        self.assertEqual(wf_core.edge_diff([5, 6], []), ([], [5, 6]))

    def test_an_unchanged_set_is_a_no_op(self):
        self.assertEqual(wf_core.edge_diff([6, 5], [5, 6]), ([], []))


class TestOwnershipConflict(unittest.TestCase):
    """One issue, one party: the field and the title prefix must agree."""

    def test_an_unprefixed_title_is_code_work(self):
        self.assertIsNone(wf_core.ownership_conflict('Add a setting', 'Code agent'))

    def test_matching_prefixes_are_clean(self):
        self.assertIsNone(wf_core.ownership_conflict('[Manual] Pass', 'Human'))
        self.assertIsNone(wf_core.ownership_conflict('[browser] Turn it on',
                                                     'Browser agent'))

    def test_a_person_owned_issue_needs_the_prefix(self):
        self.assertIn('[Manual]', wf_core.ownership_conflict('Pass', 'Human'))

    def test_a_prefix_on_code_work_is_a_conflict(self):
        self.assertIn('one issue, one party',
                      wf_core.ownership_conflict('[Manual] Pass', 'Code agent'))

    def test_no_value_is_not_a_conflict(self):
        """Missing is `validate_spec`'s mandatory-field error, not this one."""
        self.assertIsNone(wf_core.ownership_conflict('[Manual] Pass', None))


def _hplan(type_name, **entry):
    return {'entry': entry, 'type': type_name}


class TestSpecHierarchy(unittest.TestCase):
    """Epic → Feature → User Story, checked across a whole spec."""

    TYPES = {'Epic': 'e', 'Feature': 'f', 'User Story': 's', 'Bug': 'b'}

    def _errors(self, plans, types=None, parents=None, type_map=TYPES):
        return wf_core.spec_hierarchy_errors(plans, types or {}, parents or {},
                                             type_map)

    def test_a_tree_in_one_spec_is_clean(self):
        plans = [_hplan('Epic', key='e', title='E'),
                 _hplan('Feature', key='f', title='F', parent='e'),
                 _hplan('User Story', key='s', title='S', parent='f')]
        self.assertEqual(self._errors(plans), [])

    def test_a_story_under_an_existing_feature_is_clean(self):
        plans = [_hplan('User Story', key='s', title='S', parent=50)]
        self.assertEqual(self._errors(plans, types={50: 'Feature'}), [])

    def test_a_story_straight_under_an_epic_is_refused(self):
        plans = [_hplan('User Story', key='s', title='S', parent=50)]
        errors = self._errors(plans, types={50: 'Epic'})
        self.assertEqual(len(errors), 1)
        self.assertIn("belongs under a 'Feature'", errors[0])

    def test_a_feature_may_stand_without_an_epic(self):
        """An epic invented to hold one feature would only restate it."""
        self.assertEqual(self._errors([_hplan('Feature', key='f', title='F')]), [])

    def test_a_feature_with_a_parent_needs_an_epic_one(self):
        plans = [_hplan('Feature', key='f', title='F', parent=50)]
        errors = self._errors(plans, types={50: 'User Story'})
        self.assertEqual(len(errors), 1)
        self.assertIn("belongs under a 'Epic'", errors[0])

    def test_bugs_chores_and_epics_need_no_parent(self):
        plans = [_hplan('Bug', key='b', title='B'),
                 _hplan('Epic', key='e', title='E')]
        self.assertEqual(self._errors(plans), [])

    def test_an_update_is_judged_against_the_parent_it_already_has(self):
        plans = [_hplan('User Story', number=7)]
        self.assertEqual(self._errors(plans, parents={7: (50, 'Feature')}), [])
        self.assertEqual(len(self._errors(plans, parents={7: (None, None)})), 1)

    def test_an_update_that_settles_no_type_is_not_checked(self):
        """Setting a field on an issue must not refuse over structure."""
        self.assertEqual(self._errors([_hplan(None, number=7)]), [])

    def test_a_parent_updated_in_the_same_spec_keeps_its_live_type(self):
        """The parent entry names no type, so its live one answers."""
        plans = [_hplan(None, number=50),
                 _hplan('User Story', key='s', title='S', parent=50)]
        self.assertEqual(self._errors(plans, types={50: 'Feature'}), [])

    def test_an_org_without_the_parent_type_is_not_held_to_it(self):
        plans = [_hplan('User Story', key='s', title='S')]
        self.assertEqual(self._errors(plans, type_map={'User Story': 's'}), [])

    def test_an_update_that_moves_its_parent_is_judged_by_its_live_type(self):
        """Found live: a story re-parented onto an epic by an entry that named
        no `kind` went straight through."""
        plans = [_hplan(None, number=7, parent=40)]
        errors = self._errors(plans, types={7: 'User Story', 40: 'Epic'})
        self.assertEqual(len(errors), 1)
        self.assertIn("belongs under a 'Feature'", errors[0])
        self.assertEqual(
            self._errors(plans, types={7: 'User Story', 40: 'Feature'}), [])


class TestSpecLiveErrors(unittest.TestCase):
    """What an update breaks once the issue it updates is read."""

    FIELDS = {
        'Priority': {'id': 'p', 'data_type': 'single-select',
                     'options': {'High': 'o1', 'Low': 'o2'}},
        'Effort': {'id': 'e', 'data_type': 'single-select',
                   'options': {'Medium': 'o3'}},
        'Ownership': {'id': 'w', 'data_type': 'single-select',
                      'options': {'Code agent': 'o4', 'Human': 'o5'}},
    }
    CARRIES = {'Priority': 'High', 'Effort': 'Medium', 'Ownership': 'Code agent'}

    def _check(self, entry, live_fields=None, title='Fix the thing'):
        errors, _, plans = wf_core.validate_spec([entry], self.FIELDS, {})
        self.assertEqual(errors, [])
        live = {7: {'title': title,
                    'fields': self.CARRIES if live_fields is None else live_fields}}
        return wf_core.spec_live_errors(plans, live)

    def test_an_update_need_not_restate_what_the_issue_carries(self):
        self.assertEqual(
            self._check({'number': 7, 'fields': {'field-priority': 'Low'}}), [])

    def test_a_value_neither_the_entry_nor_the_issue_has_is_refused(self):
        errors = self._check({'number': 7, 'fields': {'field-priority': 'Low'}},
                             live_fields={'Priority': 'High'})
        self.assertEqual(len(errors), 2)
        self.assertIn('Effort', errors[0])

    def test_a_placeholder_on_an_update_is_still_refused_before_any_read(self):
        """`TODO` is what an audit writes: somebody saying the value is unknown."""
        entry = {'number': 7, 'fields': {'field-priority': wf_core.SPEC_PLACEHOLDER}}
        errors, _, _ = wf_core.validate_spec([entry], self.FIELDS, {})
        self.assertEqual(len(errors), 1)
        self.assertIn('Priority', errors[0])

    def test_a_create_still_needs_every_value_in_the_spec(self):
        errors, _, _ = wf_core.validate_spec(
            [{'title': 'New', 'fields': {'field-priority': 'Low'}}],
            self.FIELDS, {})
        self.assertEqual(len(errors), 2)

    def test_setting_a_person_on_an_unprefixed_issue_is_refused(self):
        errors = self._check({'number': 7, 'fields': {'field-ownership': 'Human'}})
        self.assertEqual(len(errors), 1)
        self.assertIn('[Manual]', errors[0])

    def test_a_manual_retitle_of_a_code_agent_issue_is_refused(self):
        errors = self._check({'number': 7, 'title': '[Manual] Device pass'})
        self.assertEqual(len(errors), 1)

    def test_an_update_touching_neither_title_nor_owner_is_not_judged(self):
        """Refusing a priority change over a conflict it did not make blocks the fix."""
        self.assertEqual(
            self._check({'number': 7, 'fields': {'field-priority': 'Low'}},
                        live_fields=dict(self.CARRIES, Ownership='Human')), [])


class TestValidateSpecStructure(unittest.TestCase):
    """The two structural refusals `validate_spec` makes before any write."""

    FIELDS = {
        'Priority': {'id': 'p', 'data_type': 'single-select',
                     'options': {'High': 'o1'}},
        'Effort': {'id': 'e', 'data_type': 'single-select',
                   'options': {'Medium': 'o2'}},
        'Ownership': {'id': 'w', 'data_type': 'single-select',
                      'options': {'Code agent': 'o5', 'Human': 'o6'}},
    }

    def _entry(self, **over):
        entry = {'title': 'A thing', 'kind': 'story',
                 'fields': {'field-priority': 'High', 'field-effort': 'Medium',
                            'field-ownership': 'Code agent'}}
        entry.update(over)
        return entry

    def test_the_state_lands_on_the_plan(self):
        errors, _, plans = wf_core.validate_spec(
            [self._entry(state='refinement')], self.FIELDS,
            {'User Story': 's'})
        self.assertEqual(errors, [])
        self.assertEqual(plans[0]['state'], 'col-refinement')

    def test_an_unknown_state_is_an_error(self):
        errors, _, _ = wf_core.validate_spec(
            [self._entry(state='Ready')], self.FIELDS, {'User Story': 's'})
        self.assertEqual(len(errors), 1)

    def test_a_title_and_owner_that_disagree_are_refused(self):
        errors, _, _ = wf_core.validate_spec(
            [self._entry(title='[Manual] Device pass')], self.FIELDS,
            {'User Story': 's'})
        self.assertEqual(len(errors), 1)
        self.assertIn('one issue, one party', errors[0])

    def test_ownership_takes_an_issue_out_of_the_pool(self):
        """The teeth. Everything else here is bookkeeping if this does not hold."""
        pool = select_pool([{'number': 1, 'title': 'a', 'labels': []},
                            {'number': 2, 'title': 'b', 'labels': []},
                            {'number': 3, 'title': 'c', 'labels': []}],
                           ownership_map={1: 'Human', 2: 'Browser agent',
                                          3: 'Code agent'})
        self.assertEqual([c['number'] for c in pool], [3])

    def test_a_stale_scope_label_does_not_override_the_field(self):
        """An issue still carrying `human-required` but owned by the code agent
        is pickable: the field is the answer and the label reads nothing."""
        pool = select_pool([{'number': 1, 'title': 'a', 'labels': ['human-required']},
                            {'number': 2, 'title': 'b', 'labels': []}],
                           ownership_map={1: 'Code agent', 2: 'Human'})
        self.assertEqual([c['number'] for c in pool], [1])

    def test_a_status_label_alone_no_longer_excludes(self):
        """`status-non-code` used to be what kept a code agent off an issue.
        The owner is."""
        pool = select_pool([{'number': 1, 'title': 'a', 'labels': ['status-non-code']},
                            {'number': 2, 'title': 'b', 'labels': []}],
                           ownership_map={1: 'Code agent', 2: 'Code agent'})
        self.assertEqual([c['number'] for c in pool], [1, 2])

    def test_the_board_has_a_column_for_it(self):
        self.assertEqual(wf_core.BOARD_COLUMN_NAMES['col-non-code'], 'Non-code')


class TestScopeFindings(unittest.TestCase):
    """The check that stops the ownership field and the title prefix drifting.

    It used to police four signals against each other -- the field, the prefix,
    a scope label and a `status-non-code` lifecycle label. Two of those are
    gone, and most of this check went with them: what is left is whether the
    structured answer exists, whether it names a party, and whether the title a
    person reads agrees with it.
    """

    @staticmethod
    def _kinds(issues, ownership=None):
        return [f['kind'] for f in wf_core.scope_findings(issues, ownership)]

    def _issue(self, title):
        return {'number': 1, 'title': title}

    def test_a_clean_scoped_issue_reports_nothing(self):
        self.assertEqual(self._kinds([self._issue('[Manual] Open the account')],
                                     {1: 'Human'}), [])

    def test_a_clean_code_issue_reports_nothing(self):
        self.assertEqual(self._kinds([self._issue('Add a setting')],
                                     {1: 'Code agent'}), [])

    def test_a_shouted_prefix_is_not_a_scope_error(self):
        """Real backlogs carry `[MANUAL]` as often as `[Manual]`."""
        self.assertEqual(self._kinds([self._issue('[MANUAL] Open the account')],
                                     {1: 'Human'}), [])

    def test_no_ownership_value_is_the_dangerous_one(self):
        """This is the state that puts a device pass in front of a code agent —
        or, since the picker refuses to guess, keeps it out of every pool with
        nothing saying why."""
        findings = wf_core.scope_findings(
            [self._issue('[Manual] Device pass')], {})
        self.assertEqual([f['kind'] for f in findings], ['scope-unowned'])
        self.assertIn('Code agent', findings[0]['detail'])

    def test_an_option_naming_no_party_is_reported(self):
        findings = wf_core.scope_findings(
            [self._issue('Add a setting')], {1: 'Platform team'})
        self.assertEqual([f['kind'] for f in findings], ['scope-option'])
        self.assertIn('Platform team', findings[0]['detail'])

    def test_non_code_work_with_no_prefix_is_reported(self):
        findings = wf_core.scope_findings(
            [self._issue('Open the bank account')], {1: 'Human'})
        self.assertEqual([f['kind'] for f in findings], ['scope-prefix'])
        self.assertIn('[Manual]', findings[0]['detail'])

    def test_a_prefix_on_code_work_is_reported(self):
        findings = wf_core.scope_findings(
            [self._issue('[Browser] Add a setting')], {1: 'Code agent'})
        self.assertEqual([f['kind'] for f in findings], ['scope-prefix'])

    def test_a_prefix_that_names_the_other_party_is_reported(self):
        findings = wf_core.scope_findings(
            [self._issue('[Browser] Device pass')], {1: 'Human'})
        self.assertEqual([f['kind'] for f in findings], ['scope-prefix'])
        self.assertIn('[Manual]', findings[0]['detail'])


class TestScopeIsAudited(unittest.TestCase):
    """`wf issue-audit` reports scope drift where it used to report prose edges."""

    def test_a_backfilled_owner_is_not_also_reported_as_unowned(self):
        """The audit proposes `Human` from the title prefix in the same pass,
        so an issue it is about to own must not come back as ownerless."""
        node = _audit_node(1313, title='[Manual] Device pass')
        entry = wf_core.audit_issue(node, _AUDIT_FIELDS, open_numbers={1313})
        self.assertNotIn('scope-unowned', _gap_kinds(entry))
        self.assertEqual(entry['proposed']['fields']['field-ownership'], 'Human')

    def test_an_issue_whose_title_disagrees_with_its_owner_is_a_gap(self):
        node = _audit_node(1313, title='Device pass',
                           field_values=[{'field': {'name': 'Ownership'},
                                          'name': 'Human'}])
        entry = wf_core.audit_issue(node, _AUDIT_FIELDS, open_numbers={1313})
        self.assertIn('scope-prefix', _gap_kinds(entry))

    def test_an_org_with_no_ownership_field_is_not_reported_per_issue(self):
        """The field is missing, not the value. `config-audit` says that once
        for the org; saying it on every issue buries what it means."""
        node = _audit_node(1313, title='[Manual] Device pass')
        entry = wf_core.audit_issue(node, {'Priority': {}}, open_numbers={1313})
        self.assertNotIn('scope-unowned', _gap_kinds(entry))

    def test_nothing_proposes_a_dependency_edge_any_more(self):
        """The body cannot claim a dependency: only an edge records one."""
        node = _audit_node(1131, body='Blocked by #1124.')
        entry = wf_core.audit_issue(node, _AUDIT_FIELDS,
                                    open_numbers={1131, 1124})
        self.assertNotIn('blocked_by', entry['proposed'])
        self.assertNotIn('missing-edge', _gap_kinds(entry))


# -- preflight: the file-level checks -----------------------------------------

class TestPlaceholderFindings(unittest.TestCase):
    """A file copied from the template and not filled in."""

    def test_a_filled_in_file_is_clean(self):
        self.assertEqual(
            wf_core.placeholder_findings('| org | Subverting-complexity |'), [])

    def test_every_offending_line_is_named(self):
        text = '| org | {org} |\n| repo | ok |\n| repo | {repo} |'
        found = wf_core.placeholder_findings(text)
        self.assertEqual(found[0]['level'], wf_core.WARNING)
        self.assertIn('1, 3', found[0]['detail'])

    def test_a_long_run_is_summarised_rather_than_listed(self):
        text = '\n'.join(['{org}'] * 9)
        detail = wf_core.placeholder_findings(text)[0]['detail']
        self.assertIn('and 4 more', detail)


class TestRetiredSectionFindings(unittest.TestCase):
    """Sections this version reads and ignores. Left in place they mislead."""

    def test_a_surviving_ready_gate_is_reported(self):
        found = wf_core.retired_section_findings(['Identity', 'Ready Gate'])
        self.assertEqual([f['check'] for f in found], ['config-retired'])
        self.assertIn('Ready Gate', found[0]['detail'])

    def test_a_surviving_agent_gating_section_is_reported(self):
        found = wf_core.retired_section_findings(['Agent Gating'])
        self.assertIn('Backlog', found[0]['detail'])

    def test_it_warns_rather_than_failing(self):
        """Nothing reads the section, so nothing behaves wrongly because of it."""
        found = wf_core.retired_section_findings(['Ready Gate', 'Agent Gating'])
        self.assertEqual({f['level'] for f in found}, {wf_core.WARNING})

    def test_a_qualified_heading_is_still_matched(self):
        self.assertTrue(wf_core.retired_section_findings(['Ready Gate (optional)']))

    def test_a_file_without_either_is_clean(self):
        self.assertEqual(wf_core.retired_section_findings(['Identity']), [])


class TestQualityGateFindings(unittest.TestCase):

    def test_a_real_command_passes(self):
        self.assertEqual(wf_core.quality_gate_findings('pnpm test'), [])

    def test_an_empty_gate_warns(self):
        self.assertEqual(wf_core.quality_gate_findings('')[0]['check'],
                         'quality-gate')

    def test_the_template_placeholder_is_named_as_such(self):
        detail = wf_core.quality_gate_findings(
            '{quality_gate_command}')[0]['detail']
        self.assertIn('placeholder', detail)


class TestClaudeMdFindings(unittest.TestCase):

    def test_a_file_that_points_at_the_config_is_clean(self):
        self.assertEqual(wf_core.claude_md_findings(True, True), [])

    def test_a_missing_file_is_reported_separately_from_a_silent_one(self):
        self.assertEqual(wf_core.claude_md_findings(False, False)[0]['check'],
                         'file-claude-md')
        self.assertEqual(wf_core.claude_md_findings(True, False)[0]['check'],
                         'claude-md-ref')

    def test_only_the_pointer_is_repaired_automatically(self):
        """Writing a project's CLAUDE.md from nothing is the project's call."""
        self.assertIn('claude-md-ref', wf_core.FIXABLE_CHECKS)
        self.assertNotIn('file-claude-md', wf_core.FIXABLE_CHECKS)


class TestReviewConfigFindings(unittest.TestCase):

    def test_a_config_that_names_no_review_file_is_clean(self):
        self.assertEqual(wf_core.review_config_findings(None, False), [])

    def test_a_named_file_that_exists_is_clean(self):
        self.assertEqual(
            wf_core.review_config_findings('docs/review.config.md', True), [])

    def test_a_named_file_that_is_missing_warns(self):
        found = wf_core.review_config_findings('docs/review.config.md', False)
        self.assertIn('default name', found[0]['detail'])


class TestFixPlan(unittest.TestCase):
    """What `--fix` may touch, decided offline so it is the same every run."""

    def test_a_repairable_finding_is_separated_from_one_that_is_not(self):
        fixable, blocked = wf_core.fix_plan(
            [{'check': 'board-lane'}, {'check': 'gh-auth'}])
        self.assertEqual(fixable, [{'check': 'board-lane'}])
        self.assertEqual(blocked, [{'check': 'gh-auth'}])

    def test_nothing_that_needs_a_judgement_call_is_repairable(self):
        """Each of these has two defensible answers, so a run must not pick."""
        for check in ('board-title', 'label-drift', 'config-section',
                      'field-absent', 'quality-gate', 'placeholders'):
            self.assertNotIn(check, wf_core.FIXABLE_CHECKS, check)

    def test_every_unrepairable_check_says_why(self):
        for check in wf_core.UNFIXABLE_REASONS:
            self.assertNotIn(check, wf_core.FIXABLE_CHECKS, check)
            self.assertTrue(wf_core.unfixable_reason(check))

    def test_an_unknown_check_still_gets_a_truthful_answer(self):
        self.assertIn('no automatic repair',
                      wf_core.unfixable_reason('something-new'))


class TestStripSections(unittest.TestCase):

    TEXT = ('# Project\n\n## Identity\n\nrows\n\n## Ready Gate\n\nprose\n'
            'more prose\n\n## Label Map\n\nrows\n')

    def test_the_named_section_and_nothing_else_goes(self):
        out, removed = wf_core.strip_sections(self.TEXT, ['Ready Gate'])
        self.assertEqual(removed, ['Ready Gate'])
        self.assertNotIn('Ready Gate', out)
        self.assertIn('## Identity', out)
        self.assertIn('## Label Map', out)

    def test_a_deeper_heading_inside_the_section_goes_with_it(self):
        text = '## Ready Gate\n\n### Detail\n\nx\n\n## Keep\n\ny\n'
        out, _ = wf_core.strip_sections(text, ['Ready Gate'])
        self.assertNotIn('### Detail', out)
        self.assertIn('## Keep', out)

    def test_removing_a_section_twice_changes_nothing_the_second_time(self):
        once, _ = wf_core.strip_sections(self.TEXT, ['Ready Gate'])
        twice, removed = wf_core.strip_sections(once, ['Ready Gate'])
        self.assertEqual(removed, [])
        self.assertEqual(once, twice)

    def test_a_section_that_is_not_there_is_not_an_error(self):
        out, removed = wf_core.strip_sections(self.TEXT, ['Agent Gating'])
        self.assertEqual((out, removed), (self.TEXT, []))

    def test_a_trailing_section_runs_to_the_end_of_the_file(self):
        out, _ = wf_core.strip_sections('## Keep\n\nx\n\n## Ready Gate\n\ny\n',
                                        ['Ready Gate'])
        self.assertNotIn('Ready Gate', out)
        self.assertIn('## Keep', out)


class TestStripLabelMapRows(unittest.TestCase):

    TEXT = ('## Label Map\n\n| Purpose | Label |\n| --- | --- |\n'
            '| status-blocked | `blocked` |\n| claude-authored | `authored` |\n'
            '\n## Project Board\n\n| status-blocked | not a label map row |\n')

    def test_only_rows_inside_the_label_map_are_touched(self):
        out, removed = wf_core.strip_label_map_rows(self.TEXT, ['status-blocked'])
        self.assertEqual(removed, ['status-blocked'])
        self.assertNotIn('| status-blocked | `blocked` |', out)
        self.assertIn('not a label map row', out)

    def test_the_surviving_label_is_left_alone(self):
        out, _ = wf_core.strip_label_map_rows(self.TEXT, ['status-blocked'])
        self.assertIn('claude-authored', out)

    def test_prose_naming_a_retired_label_is_not_a_row(self):
        text = '## Label Map\n\nWe used to apply status-blocked here.\n'
        self.assertEqual(wf_core.strip_label_map_rows(text, ['status-blocked']),
                         (text, []))

    def test_running_it_twice_changes_nothing_the_second_time(self):
        once, _ = wf_core.strip_label_map_rows(self.TEXT, ['status-blocked'])
        twice, removed = wf_core.strip_label_map_rows(once, ['status-blocked'])
        self.assertEqual((twice, removed), (once, []))

    def test_a_file_with_no_label_map_is_left_alone(self):
        self.assertEqual(wf_core.strip_label_map_rows('# x\n', ['status-blocked']),
                         ('# x\n', []))


class TestBoardColumnFindings(unittest.TestCase):
    """The snapshot and the board can disagree in either direction."""

    LIVE = {'o1': 'Backlog', 'o2': 'In Progress'}

    def _checks(self, columns):
        return [f['detail'] for f in
                wf_core.board_column_findings(columns, self.LIVE)]

    def test_an_agreeing_snapshot_is_clean(self):
        columns = {'col-backlog': 'o1', 'col-in-progress': 'o2'}
        self.assertEqual(wf_core.board_column_findings(columns, self.LIVE), [])

    def test_a_recorded_id_the_board_no_longer_has_is_reported(self):
        details = self._checks({'col-backlog': 'gone'})
        self.assertTrue(any('no longer has' in d for d in details))

    def test_a_live_column_the_file_does_not_record_is_reported(self):
        """The direction a repair creates: adding a lane leaves the file
        recording it as `n/a`, and nothing said so until this checked."""
        details = self._checks({'col-backlog': 'o1'})
        self.assertTrue(any('In Progress' in d and 'no option id' in d
                            for d in details))

    def test_a_lane_the_board_does_not_have_is_not_reported_here(self):
        """That is `board_lane_findings`, and for `Backlog` it is critical."""
        details = self._checks({'col-backlog': 'o1', 'col-in-progress': 'o2'})
        self.assertFalse(any('Blocked' in d for d in details))

    def test_both_directions_warn_rather_than_failing(self):
        found = wf_core.board_column_findings({'col-backlog': 'gone'}, self.LIVE)
        self.assertEqual({f['level'] for f in found}, {wf_core.WARNING})


class TestStatusOptionsTable(unittest.TestCase):

    def test_every_canonical_column_gets_a_row_in_canonical_order(self):
        rendered = wf_core.render_status_options({'col-backlog': 'abc123'})
        rows = [l for l in rendered.splitlines() if l.startswith('| ')][2:]
        self.assertEqual(len(rows), len(wf_core.BOARD_COLUMN_NAMES))
        self.assertIn('| Backlog | `col-backlog` | `abc123` |', rows[0])

    def test_a_column_the_board_does_not_have_is_recorded_as_absent(self):
        self.assertIn('| `col-done` | n/a |', wf_core.render_status_options({}))

    def test_the_same_board_always_produces_the_same_table(self):
        columns = {'col-done': 'z', 'col-backlog': 'a'}
        self.assertEqual(wf_core.render_status_options(columns),
                         wf_core.render_status_options(dict(reversed(
                             list(columns.items())))))

    def test_replacing_the_table_leaves_the_rest_of_the_section_alone(self):
        text = ('## Project Board\n\n| project-node-id | PVT_1 |\n\n'
                '### Status Options\n\n| Column | Purpose Key | Option ID |\n'
                '| --- | --- | --- |\n| Backlog | `col-backlog` | `old` |\n\n'
                '## Reference Docs\n\nx\n')
        out, changed = wf_core.replace_status_options(text,
                                                      {'col-backlog': 'new'})
        self.assertTrue(changed)
        self.assertIn('| project-node-id | PVT_1 |', out)
        self.assertIn('## Reference Docs', out)
        self.assertIn('`new`', out)
        self.assertNotIn('`old`', out)

    def test_writing_the_same_table_twice_reports_no_change(self):
        text = ('### Status Options\n\n'
                + wf_core.render_status_options({'col-backlog': 'a'}) + '\n')
        self.assertEqual(wf_core.replace_status_options(text,
                                                        {'col-backlog': 'a'}),
                         (text, False))

    def test_the_prose_around_the_table_survives_the_rewrite(self):
        """The first version replaced the whole section and ate four paragraphs
        of this repository's own writing. Only the table's lines may move."""
        text = ('### Status Options\n\nWhy this board is shaped this way.\n\n'
                '| Column | Purpose Key | Option ID |\n| --- | --- | --- |\n'
                '| Backlog | `col-backlog` | `old` |\n\n'
                '**Backlog is the pool.** Nothing else is read.\n')
        out, changed = wf_core.replace_status_options(text,
                                                      {'col-backlog': 'new'})
        self.assertTrue(changed)
        self.assertIn('Why this board is shaped this way.', out)
        self.assertIn('**Backlog is the pool.**', out)
        self.assertIn('`new`', out)
        self.assertNotIn('`old`', out)

    def test_a_section_with_prose_but_no_table_is_left_alone(self):
        text = '### Status Options\n\nNot configured yet.\n'
        self.assertEqual(wf_core.replace_status_options(text, {'a': 'b'}),
                         (text, False))

    def test_a_file_with_no_table_is_left_alone_rather_than_given_one(self):
        self.assertEqual(wf_core.replace_status_options('# x\n', {'a': 'b'}),
                         ('# x\n', False))


class TestRetiredWorkflowFindings(unittest.TestCase):
    """What preflight reports about the workflow this one replaced."""

    def test_a_ready_column_on_the_board_warns(self):
        findings = wf_core.board_retired_findings(['Backlog', 'Ready', 'Done'])
        self.assertEqual(_checks(findings), ['board-retired'])
        self.assertIn('Backlog', findings[0]['detail'])

    def test_a_board_without_one_is_clean(self):
        self.assertEqual(wf_core.board_retired_findings(['Backlog', 'Done']), [])

    def test_open_issues_carrying_retired_labels_are_named(self):
        findings = wf_core.retired_label_findings([
            {'number': 3, 'labels': ['status-ready', 'type-bug']},
            {'number': 4, 'labels': ['type-bug']}])
        self.assertEqual(_checks(findings), ['label-retired'])
        self.assertIn('#3', findings[0]['detail'])
        self.assertNotIn('#4', findings[0]['detail'])

    def test_both_retired_repairs_are_fixable_and_the_rest_are_not(self):
        for check in ('label-retired', 'board-retired'):
            self.assertIn(check, wf_core.FIXABLE_CHECKS)
        for check in ('field-options', 'instructions-retired'):
            self.assertIn(check, wf_core.UNFIXABLE_REASONS)

    def test_a_priority_option_the_picker_cannot_rank_warns(self):
        findings = wf_core.field_option_findings(
            {'Priority': {'options': {'P0': 'x', 'High': 'y'}}})
        self.assertEqual(_checks(findings), ['field-options'])
        self.assertEqual(_levels(findings), [wf_core.WARNING])
        self.assertIn('P0', findings[0]['detail'])

    def test_an_ownership_nothing_can_route_is_critical(self):
        findings = wf_core.field_option_findings(
            {'Ownership': {'options': {'Platform team': 'x'}}})
        self.assertEqual(_levels(findings), [wf_core.CRITICAL])

    def test_the_options_the_workflow_reads_are_clean(self):
        self.assertEqual(wf_core.field_option_findings({
            'Priority': {'options': {'Urgent': 'a', 'High': 'b', 'Medium': 'c',
                                     'Low': 'd'}},
            'Ownership': {'options': {'Code agent': 'a', 'Browser agent': 'b',
                                      'Human': 'c'}}}), [])

    def test_retired_vocabulary_in_an_instruction_file_is_reported(self):
        findings = wf_core.instruction_findings({
            'CLAUDE.md': 'Intro.\nMove it to the Ready column.\nBlocked by #12\n'})
        self.assertEqual(sorted(_checks(findings)),
                         ['instructions-retired', 'instructions-retired'])
        joined = ' '.join(f['detail'] for f in findings)
        self.assertIn('line 2', joined)
        self.assertIn('line 3', joined)

    def test_a_current_instruction_file_is_clean(self):
        self.assertEqual(wf_core.instruction_findings({
            'CLAUDE.md': 'The board column is the state. Backlog is the pool.\n'}),
            [])


class TestBoardColumnCreationValues(unittest.TestCase):
    """A created column needs a colour and a description, and GitHub requires
    both. They live beside the names so every creator writes the same board."""

    def test_every_column_has_a_colour_and_a_description(self):
        for name in wf_core.BOARD_COLUMN_NAMES.values():
            self.assertIn(name, wf_core.BOARD_COLUMN_COLOURS)
            self.assertTrue(wf_core.BOARD_COLUMN_DESCRIPTIONS.get(name))

    def test_no_lane_an_issue_passes_through_shares_a_colour(self):
        """The enum has eight colours to nine lanes, so `Parked` and `Done`
        share the spare one and nothing on the way to done looks alike."""
        working = [n for n in wf_core.BOARD_COLUMN_NAMES.values()
                   if n not in ('Parked', 'Done')]
        colours = [wf_core.BOARD_COLUMN_COLOURS[n] for n in working]
        self.assertEqual(len(colours), len(set(colours)))


class TestAddConfigPointer(unittest.TestCase):

    def test_a_file_that_already_points_at_the_config_is_untouched(self):
        text = '# Repo\n\nSee ClaudeProject.md.\n'
        self.assertEqual(wf_core.add_config_pointer(text), (text, False))

    def test_the_pointer_is_appended_to_a_file_that_lacks_one(self):
        out, changed = wf_core.add_config_pointer('# Repo\n')
        self.assertTrue(changed)
        self.assertIn('ClaudeProject.md', out)
        self.assertTrue(out.startswith('# Repo\n'))

    def test_a_project_that_worded_its_own_pointer_keeps_it(self):
        text = '# Repo\n\nConfig: [here](ClaudeProject.md)\n'
        self.assertEqual(wf_core.add_config_pointer(text), (text, False))

    def test_running_it_twice_appends_once(self):
        once, _ = wf_core.add_config_pointer('# Repo\n')
        self.assertEqual(wf_core.add_config_pointer(once), (once, False))


# ── a bulk set chosen from a container (#239) ────────────────────────────────

def _tree(number, kind, *children, state='OPEN', repo=None):
    return {'number': number, 'type': kind, 'state': state, 'repo': repo,
            'children': list(children)}


class TestChooseParentSet(unittest.TestCase):
    """`choose_parent_set` — the one bulk set a container's tree offers."""

    @staticmethod
    def _numbers(choice):
        return [s['number'] for s in choice['selected']]

    @staticmethod
    def _reason(choice, number):
        return next(e['reason'] for e in choice['excluded'] if e['number'] == number)

    def test_a_feature_offers_its_pool_leaves_in_priority_order(self):
        root = _tree(10, 'Feature', _tree(11, 'User Story'), _tree(12, 'Bug'))
        choice = wf_core.choose_parent_set(root, [12, 11], {11: [], 12: []})
        self.assertEqual(choice['group'], 10)
        self.assertEqual(self._numbers(choice), [12, 11])
        self.assertEqual(choice['excluded'], [])

    def test_under_an_epic_one_feature_is_taken(self):
        """The Feature holding the highest-priority leaf, and only that one:
        leaves from two Features are two deliverables in one pull request."""
        root = _tree(1, 'Epic',
                     _tree(2, 'Feature', _tree(21, 'User Story')),
                     _tree(3, 'Feature', _tree(31, 'User Story'),
                           _tree(32, 'User Story')))
        choice = wf_core.choose_parent_set(root, [31, 21, 32],
                                           {21: [], 31: [], 32: []})
        self.assertEqual(choice['group'], 3)
        self.assertEqual(self._numbers(choice), [31, 32])
        self.assertIn('#2', self._reason(choice, 21))

    def test_a_leaf_blocked_by_a_sibling_is_taken_after_it(self):
        root = _tree(10, 'Feature', _tree(11, 'User Story'), _tree(12, 'User Story'))
        choice = wf_core.choose_parent_set(root, [11], {11: [], 12: [11]})
        self.assertEqual(self._numbers(choice), [11, 12])

    def test_a_leaf_blocked_by_anything_else_is_left_out(self):
        root = _tree(10, 'Feature', _tree(11, 'User Story'), _tree(12, 'User Story'))
        choice = wf_core.choose_parent_set(root, [11], {11: [], 12: [99]})
        self.assertEqual(self._numbers(choice), [11])
        self.assertIn('#99', self._reason(choice, 12))

    def test_work_outside_the_pool_is_never_taken_and_says_why(self):
        root = _tree(10, 'Feature', _tree(11, 'User Story'), _tree(12, 'User Story'))
        choice = wf_core.choose_parent_set(
            root, [11], {11: []},
            {12: 'in the `Non-code` column, owned by Human, not the code agent'})
        self.assertEqual(self._numbers(choice), [11])
        self.assertIn('Non-code', self._reason(choice, 12))

    def test_a_feature_with_no_stories_is_reported_not_built(self):
        root = _tree(1, 'Epic', _tree(2, 'Feature'),
                     _tree(3, 'Feature', _tree(31, 'User Story')))
        choice = wf_core.choose_parent_set(root, [31], {31: []})
        self.assertEqual(self._numbers(choice), [31])
        self.assertIn('no open stories', self._reason(choice, 2))

    def test_the_size_cut_takes_a_dependent_with_its_blocker(self):
        """13 waits on 12, which waits on 11. A size of two keeps 11 and 13 by
        preference order, and 13 then waits on something nobody is building."""
        root = _tree(10, 'Feature', _tree(11, 'User Story'),
                     _tree(12, 'User Story'), _tree(13, 'User Story'))
        choice = wf_core.choose_parent_set(root, [11], {11: [], 13: [12], 12: [11]},
                                           max_size=2)
        self.assertEqual(self._numbers(choice), [11])
        self.assertIn('--size', self._reason(choice, 12))
        self.assertIn('#12', self._reason(choice, 13))

    def test_nothing_ready_means_nothing_is_taken(self):
        root = _tree(10, 'Feature', _tree(11, 'User Story'))
        choice = wf_core.choose_parent_set(root, [], {}, {11: 'in the `Parked` column'})
        self.assertIsNone(choice['group'])
        self.assertEqual(choice['selected'], [])
        self.assertIn('Parked', self._reason(choice, 11))

    def test_closed_leaves_are_ignored_and_foreign_ones_reported(self):
        root = _tree(10, 'Feature', _tree(11, 'User Story', state='CLOSED'),
                     _tree(12, 'User Story', repo='o/other'),
                     _tree(13, 'User Story', repo='o/r'))
        choice = wf_core.choose_parent_set(root, [13], {13: []}, repo='o/r')
        self.assertEqual(self._numbers(choice), [13])
        self.assertEqual(self._reason(choice, 12), 'in another repository')
        self.assertNotIn(11, [e['number'] for e in choice['excluded']])


# ── closing a finished container (#240) ──────────────────────────────────────

def _container(number, kind, *children, state='OPEN', repo=None):
    return {'number': number, 'type': kind, 'state': state, 'repo': repo,
            'children': [{'number': n, 'state': s} for n, s in children]}


class TestFinishedContainers(unittest.TestCase):
    """Which Epic or Feature a closed issue finishes, and how far up."""

    def test_every_child_closed_finishes_it_whatever_the_reason(self):
        """The read carries state only, so a child closed as not planned is
        closed like any other: that was the decision on #240."""
        self.assertTrue(wf_core.container_finished(
            _container(1, 'Feature', (2, 'CLOSED'), (3, 'CLOSED'))))

    def test_one_open_child_keeps_it_open(self):
        self.assertFalse(wf_core.container_finished(
            _container(1, 'Epic', (2, 'CLOSED'), (3, 'OPEN'))))

    def test_a_child_this_run_closed_counts_before_the_read_catches_up(self):
        self.assertTrue(wf_core.container_finished(
            _container(1, 'Feature', (2, 'OPEN')), closed={2}))

    def test_an_empty_container_is_never_finished(self):
        self.assertFalse(wf_core.container_finished(_container(1, 'Epic')))

    def test_only_an_open_container_can_be_finished(self):
        self.assertFalse(wf_core.container_finished(
            _container(1, 'User Story', (2, 'CLOSED'))))
        self.assertFalse(wf_core.container_finished(
            _container(1, 'Feature', (2, 'CLOSED'), state='CLOSED')))

    def test_closing_a_story_can_finish_its_feature_and_then_its_epic(self):
        chain = [_container(10, 'Feature', (11, 'OPEN')),
                 _container(1, 'Epic', (10, 'OPEN'), (20, 'CLOSED'))]
        self.assertEqual(wf_core.ancestors_to_close(11, chain),
                         [{'number': 10, 'finished_by': 11},
                          {'number': 1, 'finished_by': 10}])

    def test_the_walk_stops_at_the_first_unfinished_ancestor(self):
        chain = [_container(10, 'Feature', (11, 'OPEN'), (12, 'OPEN')),
                 _container(1, 'Epic', (10, 'OPEN'))]
        self.assertEqual(wf_core.ancestors_to_close(11, chain), [])

    def test_a_parent_in_another_repository_is_left_alone(self):
        chain = [_container(10, 'Feature', (11, 'OPEN'), repo='o/other')]
        self.assertEqual(wf_core.ancestors_to_close(11, chain, repo='o/r'), [])

    def test_one_finding_names_every_finished_container(self):
        found = wf_core.finished_container_findings(
            [{'number': 5, 'title': 'a'}, {'number': 6, 'title': 'b'}])
        self.assertEqual(len(found), 1)
        self.assertEqual(found[0]['check'], 'container-finished')
        self.assertEqual(found[0]['level'], wf_core.WARNING)
        self.assertIn('#5', found[0]['detail'])
        self.assertIn('#6', found[0]['detail'])
        self.assertIn('container-finished', wf_core.FIXABLE_CHECKS)
        self.assertEqual(wf_core.finished_container_findings([]), [])


if __name__ == '__main__':
    unittest.main(verbosity=2)
