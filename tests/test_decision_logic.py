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
    current_lifecycle_label,
    detect_backlog_mode,
    filter_by_native_type,
    get_sprint_candidates,
    is_maintenance_classification,
    parse_dependencies,
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

def _issue(number, labels, body='', milestone=None):
    return {'number': number, 'labels': labels, 'body': body, 'milestone': milestone}


class TestStorySelection(unittest.TestCase):
    """Priority sort, mode filter, refinement filter, and agent-gating."""

    # Priority sort

    def test_higher_priority_beats_lower_issue_number(self):
        """A high-priority issue is selected over a medium-priority issue with a smaller number."""
        candidates = [
            _issue(1, ['priority-medium', 'status-ready']),
            _issue(10, ['priority-high', 'status-ready']),
        ]
        self.assertEqual(select_story(candidates)['number'], 10)

    def test_same_priority_lower_number_wins(self):
        candidates = [
            _issue(20, ['priority-medium', 'status-ready']),
            _issue(5, ['priority-medium', 'status-ready']),
        ]
        self.assertEqual(select_story(candidates)['number'], 5)

    def test_full_priority_order_critical_high_medium_low(self):
        candidates = [
            _issue(4, ['priority-low', 'status-ready']),
            _issue(3, ['priority-medium', 'status-ready']),
            _issue(2, ['priority-high', 'status-ready']),
            _issue(1, ['priority-critical', 'status-ready']),
        ]
        self.assertEqual(select_story(candidates)['number'], 1)

    def test_unlabelled_priority_sorts_after_explicit_low(self):
        candidates = [
            _issue(1, ['status-ready']),            # no priority label
            _issue(2, ['priority-low', 'status-ready']),
        ]
        self.assertEqual(select_story(candidates)['number'], 2)

    # Refinement filter

    def test_needs_refinement_excluded_even_at_high_priority(self):
        candidates = [
            _issue(1, ['priority-high', 'needs-refinement', 'status-ready']),
            _issue(2, ['priority-medium', 'status-ready']),
        ]
        self.assertEqual(select_story(candidates)['number'], 2)

    def test_all_need_refinement_returns_none(self):
        candidates = [_issue(1, ['priority-high', 'needs-refinement'])]
        self.assertIsNone(select_story(candidates))

    def test_empty_pool_returns_none(self):
        self.assertIsNone(select_story([]))

    # Lifecycle filter -- every state but status-ready is out of the pool

    def test_parked_is_out_of_the_pool(self):
        """A human set it aside; the picker does not take it back."""
        candidates = [
            _issue(1, ['priority-critical', 'status-parked']),
            _issue(2, ['priority-low', 'status-ready']),
        ]
        self.assertEqual(select_story(candidates)['number'], 2)

    def test_every_unavailable_lifecycle_state_is_out_of_the_pool(self):
        for state in ('status-parked', 'status-blocked', 'status-in-progress',
                      'status-in-review', 'status-needs-attention',
                      'needs-refinement'):
            with self.subTest(state=state):
                self.assertIsNone(
                    select_story([_issue(1, ['priority-critical', state])]))

    def test_no_lifecycle_label_at_all_stays_eligible(self):
        """`ready-gate: none` depends on this: unlabelled is not unavailable."""
        self.assertEqual(select_story([_issue(7, ['priority-low'])])['number'], 7)

    # Mode filter

    def test_story_mode_accepts_any_type(self):
        """In story mode there is no type filter — all issue kinds are eligible."""
        candidates = [
            _issue(1, ['priority-medium', 'type-bug', 'status-ready']),
            _issue(2, ['priority-medium', 'type-story', 'status-ready']),
        ]
        # Both eligible; lowest number wins
        self.assertEqual(select_story(candidates, mode='story')['number'], 1)

    # A `type-*` label classifies nothing any more, on any org. An org that
    # has not enabled native issue types cannot answer a feature/maintenance
    # question at all, and saying so is the point -- guessing from labels is
    # what put a `[CHORE]` in the feature pool.

    def test_feature_mode_without_native_types_selects_nothing(self):
        candidates = [
            _issue(1, ['priority-high', 'type-bug', 'status-ready']),
            _issue(2, ['priority-medium', 'type-story', 'status-ready']),
        ]
        self.assertIsNone(select_story(candidates, mode='feature'))

    def test_maintenance_mode_without_native_types_selects_nothing(self):
        candidates = [_issue(1, ['priority-medium', 'type-bug', 'status-ready'])]
        self.assertIsNone(select_story(candidates, mode='maintenance'))

    def test_the_unanswerable_candidates_are_named_not_dropped(self):
        unclassified = []
        candidates = [_issue(1, ['type-bug']), _issue(2, ['type-story'])]
        pool = select_pool(candidates, mode='maintenance',
                           unclassified=unclassified)
        self.assertEqual(pool, [])
        self.assertEqual(unclassified, [1, 2])

    def test_story_mode_still_needs_no_types_at_all(self):
        """Story mode asks no type question, so it is unaffected."""
        candidates = [_issue(1, ['priority-high', 'status-ready'])]
        self.assertEqual(select_story(candidates)['number'], 1)

    # Agent gating

    def test_gating_disabled_does_not_filter_on_claude_ready(self):
        candidates = [
            _issue(1, ['priority-medium', 'status-ready']),           # no claude-ready
            _issue(2, ['priority-medium', 'status-ready', 'claude-ready']),
        ]
        # Gating off: pick #1 (lower number, same priority)
        self.assertEqual(select_story(candidates, agent_gating='disabled')['number'], 1)

    def test_gating_enabled_requires_claude_ready(self):
        candidates = [
            _issue(1, ['priority-high', 'status-ready']),             # not approved
            _issue(2, ['priority-medium', 'status-ready', 'claude-ready']),
        ]
        # Gating on: #1 filtered out even though higher priority
        self.assertEqual(select_story(candidates, agent_gating='enabled')['number'], 2)

    def test_gating_enabled_nothing_approved_returns_none(self):
        candidates = [_issue(1, ['priority-high', 'status-ready'])]
        self.assertIsNone(select_story(candidates, agent_gating='enabled'))


class TestSelectionHonoursProjectLabelMap(unittest.TestCase):
    """The fast path must resolve every label it filters/sorts on through the
    project map — otherwise a project that renames labels comes
    up spuriously empty (the `no-candidates` / ready-gate-mismatch symptom)."""

    # A project that renames the defaults.
    PROJECT_MAP = {
        'priority-high': 'P1',
        'priority-medium': 'P2',
        'needs-refinement': 'triage',
        'claude-ready': 'bot-ok',
        'type-story': 'kind-story',
        'type-bug': 'kind-bug',
    }

    def test_priority_sort_uses_remapped_labels(self):
        """A renamed priority label still outranks a lower-priority issue with a
        smaller number — without the map it would sort as 'no priority'."""
        candidates = [
            _issue(1, ['P2']),
            _issue(10, ['P1']),
        ]
        self.assertEqual(
            select_story(candidates, project_map=self.PROJECT_MAP)['number'], 10)

    def test_parked_filter_uses_remapped_label(self):
        candidates = [
            _issue(1, ['P1', 'on-hold']),  # renamed status-parked -> excluded
            _issue(2, ['P2', 'status-ready']),
        ]
        project_map = dict(self.PROJECT_MAP, **{'status-parked': 'on-hold'})
        self.assertEqual(
            select_story(candidates, project_map=project_map)['number'], 2)

    def test_refinement_filter_uses_remapped_label(self):
        candidates = [
            _issue(1, ['P1', 'triage']),   # renamed needs-refinement → excluded
            _issue(2, ['P2']),
        ]
        self.assertEqual(
            select_story(candidates, project_map=self.PROJECT_MAP)['number'], 2)

    def test_agent_gating_uses_remapped_label(self):
        candidates = [
            _issue(1, ['P1']),             # not approved
            _issue(2, ['P2', 'bot-ok']),   # renamed claude-ready
        ]
        self.assertEqual(
            select_story(candidates, agent_gating='enabled',
                         project_map=self.PROJECT_MAP)['number'], 2)

    def test_remapped_project_does_not_come_up_empty(self):
        """Regression: without map-aware filters this pool emptied to no-candidates."""
        candidates = [
            _issue(5, ['P1']),
            _issue(6, ['P2', 'triage']),   # excluded by refinement
        ]
        pool = select_pool(candidates, project_map=self.PROJECT_MAP)
        self.assertEqual([c['number'] for c in pool], [5])

    def test_omitting_map_falls_back_to_default_names(self):
        """No project map → default literals still work (backwards compatible)."""
        candidates = [
            _issue(1, ['priority-medium', 'status-ready']),
            _issue(10, ['priority-high', 'status-ready']),
        ]
        self.assertEqual(select_story(candidates)['number'], 10)


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
            _issue(1, ['status-ready'], milestone=None),
            _issue(2, ['status-ready'], milestone=None),
        ]
        self.assertEqual(detect_backlog_mode(candidates), 'flat')

    def test_any_milestone_triggers_sprint_mode(self):
        candidates = [
            _issue(1, ['status-ready'], milestone='Sprint 3'),
            _issue(2, ['status-ready'], milestone=None),
        ]
        self.assertEqual(detect_backlog_mode(candidates), 'sprint')

    def test_all_milestones_is_sprint_mode(self):
        candidates = [
            _issue(1, ['status-ready'], milestone='Sprint 3'),
            _issue(2, ['status-ready'], milestone='Sprint 3'),
        ]
        self.assertEqual(detect_backlog_mode(candidates), 'sprint')

    def test_empty_candidate_list_is_flat(self):
        self.assertEqual(detect_backlog_mode([]), 'flat')

    def test_sprint_filter_keeps_only_matching_milestone(self):
        candidates = [
            _issue(1, ['status-ready'], milestone='Sprint 3'),
            _issue(2, ['status-ready'], milestone='Sprint 4'),   # different sprint
            _issue(3, ['status-ready'], milestone=None),
        ]
        result = get_sprint_candidates(candidates, 'Sprint 3')
        self.assertEqual([c['number'] for c in result], [1])

    def test_sprint_selection_respects_priority_within_sprint(self):
        """After narrowing to a sprint, the priority sort still picks the best issue."""
        candidates = [
            _issue(1, ['priority-low', 'status-ready'], milestone='Sprint 5'),
            _issue(2, ['priority-high', 'status-ready'], milestone='Sprint 5'),
            _issue(3, ['priority-critical', 'status-ready'], milestone='Sprint 6'),  # wrong sprint
        ]
        sprint_pool = get_sprint_candidates(candidates, 'Sprint 5')
        result = select_story(sprint_pool)
        self.assertEqual(result['number'], 2)


class TestSelectPool(unittest.TestCase):
    """select_pool returns the full ordered list; select_story is its head."""

    def test_pool_is_sorted_best_first(self):
        candidates = [
            _issue(5, ['priority-low', 'status-ready']),
            _issue(3, ['priority-critical', 'status-ready']),
            _issue(4, ['priority-medium', 'status-ready']),
        ]
        pool = select_pool(candidates)
        self.assertEqual([c['number'] for c in pool], [3, 4, 5])

    def test_pool_head_matches_select_story(self):
        candidates = [
            _issue(2, ['priority-high', 'status-ready']),
            _issue(1, ['priority-low', 'status-ready']),
        ]
        self.assertEqual(select_pool(candidates)[0]['number'], select_story(candidates)['number'])

    def test_empty_pool_is_empty_list(self):
        self.assertEqual(select_pool([]), [])


class TestDependencyParsing(unittest.TestCase):
    """Fixed dependency markers.

    Every "prose is not a dependency" case below is a real body from a
    70-issue backlog that the previous bare-`#N` sweep read as an edge.
    """

    def test_extracts_each_marker_form(self):
        body = ("Depends on #1. Blocked by #2. Blocked on #3. Requires #4. "
                "Depends upon #5.")
        deps, overflow = parse_dependencies(body)
        self.assertEqual(deps, [1, 2, 3, 4, 5])
        self.assertFalse(overflow)

    def test_is_case_insensitive(self):
        deps, _ = parse_dependencies("DEPENDS ON #7 and Requires #8")
        self.assertEqual(deps, [7, 8])

    def test_a_marker_takes_the_whole_reference_run(self):
        """`and #N` used to be dropped silently, halving real edges."""
        deps, _ = parse_dependencies("Depends on #977 and #1032.")
        self.assertEqual(deps, [977, 1032])
        deps, _ = parse_dependencies("Blocked by #981, #991, #979 and #980.")
        self.assertEqual(deps, [979, 980, 981, 991])
        deps, _ = parse_dependencies("Blocked by **#1003** and **#1004**.")
        self.assertEqual(deps, [1003, 1004])

    def test_after_counts_only_as_a_list_item_under_dependencies(self):
        body = "## Dependencies\n\n- After #1126\n"
        self.assertEqual(parse_dependencies(body)[0], [1126])

    def test_after_in_narrative_is_not_a_dependency(self):
        """An `after` in a sentence is a note that they already landed."""
        body = "## Dependencies\n\nThe scope narrowed after #431 and #682 merged.\n"
        self.assertEqual(parse_dependencies(body)[0], [])
        self.assertEqual(parse_dependencies("Easier after #1204.")[0], [])

    def test_bare_refs_under_dependencies_are_not_dependencies(self):
        """The heading is not a marker. Bodies put all of this under it."""
        for line in (
            "Changes the scope of #982, #1000, #1030 and #1097.",
            "None of the epic's manual tasks - #1002, #1003 or #1004 - block it.",
            "Supersedes #981.",
            "Splits #1032.",
        ):
            body = "## Dependencies\n\n%s\n" % line
            self.assertEqual(parse_dependencies(body)[0], [], line)

    def test_a_reference_before_the_marker_owns_the_clause(self):
        """An epic's status list describes its children, not itself."""
        body = "- Sign in with Apple, verified on the backend (#979) - *blocked on #1032*"
        self.assertEqual(parse_dependencies(body)[0], [])

    def test_a_negated_marker_is_not_a_dependency(self):
        self.assertEqual(parse_dependencies("No longer blocked on #1004.")[0], [])
        self.assertEqual(parse_dependencies("This is not blocked by #863.")[0], [])

    def test_a_denial_next_to_a_bare_reference(self):
        body = "Depends on nothing. #863 does not have to land first."
        self.assertEqual(parse_dependencies(body)[0], [])

    def test_bare_hash_outside_section_is_ignored(self):
        deps, _ = parse_dependencies("Fixes the thing in #50 area generally")
        self.assertEqual(deps, [])

    def test_dedupes_and_sorts(self):
        deps, _ = parse_dependencies("Depends on #5. Blocked by #5. Requires #2.")
        self.assertEqual(deps, [2, 5])

    def test_overflow_flag_set_above_limit(self):
        body = " ".join("Depends on #%d." % n for n in range(1, 8))
        deps, overflow = parse_dependencies(body)
        self.assertTrue(overflow)
        self.assertGreater(len(deps), 5)

    def test_empty_or_none_body(self):
        self.assertEqual(parse_dependencies('')[0], [])
        self.assertEqual(parse_dependencies(None)[0], [])


class TestBlocksParsing(unittest.TestCase):
    """`Blocks #N` - the marker that names an edge on the *other* issue."""

    def test_reads_both_markers_and_the_whole_run(self):
        self.assertEqual(wf_core.parse_blocks("Blocks #979 and #980."),
                         [979, 980])
        self.assertEqual(wf_core.parse_blocks("Blocking #1123."), [1123])

    def test_forward_and_reverse_markers_do_not_cross(self):
        body = "Blocked by #980. Blocks #1123."
        self.assertEqual(parse_dependencies(body)[0], [980])
        self.assertEqual(wf_core.parse_blocks(body), [1123])

    def test_empty_body(self):
        self.assertEqual(wf_core.parse_blocks(''), [])
        self.assertEqual(wf_core.parse_blocks(None), [])


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


_AUDIT_FIELDS = {'Priority': {}, 'Effort': {}, 'Classification': {}, 'Origin': {}}


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

    def test_the_dependency_half_is_not_gated(self):
        """`parse_dependencies` is picker logic, not backfill: always on."""
        node = _audit_node(1131, body="Blocked by #1124.")
        entry = wf_core.audit_issue(node, _AUDIT_FIELDS,
                                    open_numbers={1131, 1124})
        self.assertIn('missing-edge', _gap_kinds(entry))
        self.assertEqual(entry['proposed']['blocked_by'], [1124])


class TestReverseEdgeFolding(unittest.TestCase):
    """`Blocks #N` placed on the issue it actually belongs to."""

    def _run(self, nodes, open_numbers=None):
        audited = [wf_core.audit_issue(n, _AUDIT_FIELDS,
                                       open_numbers=open_numbers)
                   for n in nodes]
        return {a['number']: a
                for a in wf_core.fold_reverse_edges(audited, nodes, open_numbers)}

    def test_the_edge_lands_on_the_blocked_issue(self):
        nodes = [_audit_node(1032, body="Blocks #979 and #980."),
                 _audit_node(979), _audit_node(980)]
        by = self._run(nodes, {1032, 979, 980})
        self.assertEqual(by[979]['proposed']['blocked_by'], [1032])
        self.assertEqual(by[980]['proposed']['blocked_by'], [1032])
        self.assertNotIn('blocked_by', by[1032]['proposed'])
        self.assertIn('missing-edge', _gap_kinds(by[979]))

    def test_an_edge_the_graph_already_has_is_not_proposed(self):
        nodes = [_audit_node(1032, body="Blocks #979."),
                 _audit_node(979, blocked_by=[1032])]
        by = self._run(nodes, {1032, 979})
        self.assertNotIn('blocked_by', by[979]['proposed'])

    def test_a_blocked_issue_outside_the_scan_is_skipped(self):
        nodes = [_audit_node(1032, body="Blocks #979.")]
        by = self._run(nodes, {1032})
        self.assertNotIn('blocked_by', by[1032]['proposed'])

    def test_the_reverse_edge_merges_with_a_forward_one(self):
        nodes = [_audit_node(1032, body="Blocks #979."),
                 _audit_node(979, body="Blocked by #977.")]
        by = self._run(nodes, {1032, 979, 977})
        self.assertEqual(by[979]['proposed']['blocked_by'], [977, 1032])


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


class TestCurrentLifecycleLabel(unittest.TestCase):
    """Find the concrete lifecycle label to remove when claiming."""

    def test_finds_default_named_lifecycle_label(self):
        labels = ['priority-high', 'status-ready', 'type-story']
        self.assertEqual(current_lifecycle_label(labels, {}), 'status-ready')

    def test_respects_project_custom_name(self):
        labels = ['custom-ready', 'priority-low']
        project_map = {'status-ready': 'custom-ready'}
        self.assertEqual(current_lifecycle_label(labels, project_map), 'custom-ready')

    def test_returns_none_when_no_lifecycle_label_present(self):
        self.assertIsNone(current_lifecycle_label(['priority-high'], {}))


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


class TestReadyGateParsing(unittest.TestCase):
    """parse_claude_project must read `ready-gate` so the fast path queries the
    right pool. A missed parse silently defaults to `label`, which on a `none`
    or board gate fetches the wrong pool and reports a spurious no-candidates."""

    def _gate(self, value):
        text = ("## Ready Gate\n\n"
                "| Setting    | Value      |\n"
                "| ---------- | ---------- |\n"
                "| ready-gate | %s |\n" % value)
        return parse_claude_project(text)['ready_gate']

    def test_label_gate_parsed(self):
        self.assertEqual(self._gate('`label`'), 'label')

    def test_none_gate_parsed(self):
        self.assertEqual(self._gate('`none`'), 'none')

    def test_board_column_gate_parsed(self):
        self.assertEqual(self._gate('`board-column`'), 'board-column')

    def test_value_without_backticks_parsed(self):
        self.assertEqual(self._gate('none'), 'none')

    def test_off_and_disabled_normalise_to_none(self):
        """`off` / `disabled` are synonyms for "no gate"; they must normalise
        to `none` so `wf pick` handles them on the fast path instead of
        bouncing an unrecognised token to inline selection."""
        self.assertEqual(self._gate('`off`'), 'none')
        self.assertEqual(self._gate('off'), 'none')
        self.assertEqual(self._gate('`disabled`'), 'none')
        self.assertEqual(self._gate('disabled'), 'none')

    def test_missing_section_defaults_to_label(self):
        """No Ready Gate section → default `label`, never empty/None."""
        self.assertEqual(parse_claude_project('## Identity\n')['ready_gate'], 'label')

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
    """The org's `Priority` field orders the pool; the label is the fallback.

    Priority used to be dual-tracked -- the label decided pick order, the field
    decided what the portal showed -- so setting Priority in the portal, which
    is where a person actually sets it, changed the views and left the picker
    reading a label nobody had touched. The field is the source of truth now.
    """

    def _pool(self, candidates, priority_map):
        return [c['number'] for c in
                select_pool(candidates, priority_map=priority_map)]

    def test_the_field_outranks_the_label(self):
        """#1 says low on its label and Urgent on its field: it goes first."""
        candidates = [_issue(1, ['priority-low', 'status-ready']),
                      _issue(2, ['priority-critical', 'status-ready'])]
        self.assertEqual(self._pool(candidates, {1: 'Urgent'}), [1, 2])

    def test_the_full_field_order_is_urgent_high_medium_low(self):
        candidates = [_issue(n, ['status-ready']) for n in (1, 2, 3, 4)]
        order = {1: 'Low', 2: 'Medium', 3: 'High', 4: 'Urgent'}
        self.assertEqual(self._pool(candidates, order), [4, 3, 2, 1])

    def test_an_issue_with_no_field_value_falls_back_to_its_label(self):
        """Mixed backlogs are the normal case mid-migration, not an error."""
        candidates = [_issue(1, ['status-ready']),                     # Urgent, field
                      _issue(2, ['priority-critical', 'status-ready']),  # label only
                      _issue(3, ['priority-low', 'status-ready'])]
        self.assertEqual(self._pool(candidates, {1: 'Medium'}), [2, 1, 3])

    def test_the_option_name_is_matched_case_insensitively(self):
        candidates = [_issue(1, ['status-ready']), _issue(2, ['status-ready'])]
        self.assertEqual(self._pool(candidates, {2: 'urgent'}), [2, 1])

    def test_an_unrecognised_option_falls_back_to_the_label(self):
        """An org that renamed its options is not silently unprioritised."""
        candidates = [_issue(1, ['priority-low', 'status-ready']),
                      _issue(2, ['priority-critical', 'status-ready'])]
        self.assertEqual(self._pool(candidates, {1: 'P0'}), [2, 1])

    def test_no_map_at_all_leaves_label_ordering_untouched(self):
        candidates = [_issue(1, ['priority-low', 'status-ready']),
                      _issue(2, ['priority-critical', 'status-ready'])]
        self.assertEqual(self._pool(candidates, None), [2, 1])

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
        pool = select_pool(candidates, mode='maintenance', type_map=self.TYPE_MAP,
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
        pool = select_pool(candidates, mode='feature', type_map=self.TYPE_MAP)
        numbers = [c['number'] for c in pool]
        self.assertEqual(numbers, [1])

    def test_select_pool_ignores_type_map_for_story_mode(self):
        """story mode never filters by type, even when type_map is provided."""
        candidates = [_issue(1, []), _issue(2, []), _issue(3, [])]
        pool = select_pool(candidates, mode='story', type_map=self.TYPE_MAP)
        self.assertEqual(len(pool), 3)

    def test_select_pool_without_a_type_map_classifies_nothing(self):
        """No native types, no answer -- and every candidate is named."""
        candidates = [
            _issue(1, ['priority-high', 'type-story']),
            _issue(2, ['priority-medium', 'type-bug']),
        ]
        unclassified = []
        pool = select_pool(candidates, mode='feature', unclassified=unclassified)
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
    def _story(number, body=''):
        return {'number': number, 'body': body}

    def _numbers(self, ordered):
        return [s['number'] for s in ordered]

    def test_independent_set_keeps_input_order(self):
        stories = [self._story(1), self._story(2), self._story(3)]
        ordered, notes = plan_bulk_order(stories)
        self.assertEqual(self._numbers(ordered), [1, 2, 3])
        self.assertEqual(notes, [])

    def test_dependency_inside_the_set_is_built_first(self):
        stories = [self._story(1), self._story(2, 'Blocked by #3'), self._story(3)]
        ordered, _ = plan_bulk_order(stories)
        self.assertEqual(self._numbers(ordered), [1, 3, 2])

    def test_chain_is_ordered_end_to_end(self):
        stories = [self._story(1, 'Depends on #2'),
                   self._story(2, 'Depends on #3'),
                   self._story(3)]
        self.assertEqual(self._numbers(plan_bulk_order(stories)[0]), [3, 2, 1])

    def test_dependency_outside_the_set_does_not_reorder(self):
        """A dep on an issue not in the set is the claim step's problem, not ours."""
        stories = [self._story(1, 'Depends on #99'), self._story(2)]
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
        stories = [self._story(1, 'Depends on #4'), self._story(2), self._story(3),
                   self._story(4)]
        ordered, notes = plan_bulk_order(stories, max_size=3)
        self.assertEqual(self._numbers(ordered), [1, 2, 3])
        self.assertEqual([n['number'] for n in notes], [4])

    def test_cycle_is_reported_and_still_returns_every_story(self):
        stories = [self._story(1, 'Depends on #2'), self._story(2, 'Depends on #1')]
        ordered, notes = plan_bulk_order(stories)
        self.assertEqual(sorted(self._numbers(ordered)), [1, 2])
        self.assertEqual({n['reason'] for n in notes}, {'dependency-cycle'})

    def test_self_reference_is_not_a_cycle(self):
        stories = [self._story(1, 'Depends on #1'), self._story(2)]
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

_FIELD_MAP = {
    'Priority': {'id': 'F_pri', 'data_type': 'single-select',
                 'options': {'High': 'o_hi', 'Medium': 'o_med'}},
    'Effort': {'id': 'F_eff', 'data_type': 'single-select',
               'options': {'Medium': 'o_effmed'}},
    'Classification': {'id': 'F_cls', 'data_type': 'multi-select',
                       'options': {'New Feature': 'o_nf', 'Bug Fix': 'o_bf'}},
}
_TYPE_MAP = {'User Story': 'IT_story', 'Epic': 'IT_epic', 'Bug': 'IT_bug'}


def _entry(**over):
    entry = {'key': 'a', 'title': 'A story', 'kind': 'story',
             'fields': {'field-priority': 'High', 'field-effort': 'Medium'}}
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
        entry = _entry(fields={'field-effort': 'Medium'})
        errors, _, _ = wf_core.validate_spec([entry], _FIELD_MAP, _TYPE_MAP)
        self.assertEqual(len(errors), 1)
        self.assertIn('a', errors[0])
        self.assertIn('Priority', errors[0])

    def test_a_placeholder_counts_as_missing(self):
        """`TODO` is what an audit writes; it must not be able to pass as a value."""
        entry = _entry(fields={'field-priority': wf_core.SPEC_PLACEHOLDER,
                               'field-effort': 'Medium'})
        errors, _, _ = wf_core.validate_spec([entry], _FIELD_MAP, _TYPE_MAP)
        self.assertEqual(len(errors), 1)
        self.assertIn('Priority', errors[0])

    def test_a_field_this_org_does_not_define_is_skipped_not_an_error(self):
        """An org is allowed fewer fields than the default inventory."""
        entry = _entry(fields=dict(_entry()['fields'], **{'field-origin': 'Development'}))
        errors, skipped, plans = wf_core.validate_spec([entry], _FIELD_MAP, _TYPE_MAP)
        self.assertEqual(errors, [])
        self.assertEqual(skipped, {'Origin'})
        self.assertNotIn('Origin', plans[0]['fields'])

    def test_an_option_the_field_does_not_offer_is_an_error(self):
        entry = _entry(fields={'field-priority': 'Blocker', 'field-effort': 'Medium'})
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

_AUDIT_FIELDS = {'Priority': {}, 'Effort': {}, 'Classification': {}, 'Origin': {}}


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
            _field_value('Origin', 'Development')]})
        self.assertEqual(_kinds(wf_core.audit_issue(issue, _AUDIT_FIELDS)), [])

    def test_an_untyped_issue_is_a_gap(self):
        result = wf_core.audit_issue(_node(issueType=None), {})
        self.assertEqual(_kinds(result), ['missing-type'])

    def test_every_org_field_with_no_value_is_a_gap(self):
        result = wf_core.audit_issue(_node(), _AUDIT_FIELDS)
        self.assertEqual(_kinds(result), ['missing-field'] * 4)

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

    def test_a_body_dependency_with_no_edge_is_proposed(self):
        issue = _node(body='## Dependencies\n\nBlocked by #3\n')
        result = wf_core.audit_issue(issue, {}, open_numbers={3, 5})
        self.assertEqual(_kinds(result), ['missing-edge'])
        self.assertEqual(result['proposed']['blocked_by'], [3])

    def test_an_edge_that_already_exists_is_not_reported(self):
        issue = _node(body='Blocked by #3', blockedBy={'nodes': [{'number': 3}]})
        result = wf_core.audit_issue(issue, {}, open_numbers={3, 5})
        self.assertEqual(_kinds(result), [])

    def test_a_dependency_on_a_closed_issue_is_reported_not_proposed(self):
        """An edge to a closed issue would be applied and then sit there inert."""
        issue = _node(body='Blocked by #3')
        result = wf_core.audit_issue(issue, {}, open_numbers={5})
        self.assertEqual(_kinds(result), ['dependency-closed'])
        self.assertNotIn('blocked_by', result['proposed'])

    def test_priority_is_inferred_from_the_issue_own_label(self):
        issue = _node(labels={'nodes': [{'name': 'priority-high'}]})
        result = wf_core.audit_issue(issue, {'Priority': {}})
        self.assertEqual(result['proposed']['fields']['field-priority'], 'High')

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
        result = wf_core.audit_issue(_node(), {'Start date': {}, 'Target date': {},
                                               'Parent': {}, 'Status reason': {}})
        self.assertEqual(_kinds(result), [])
        self.assertNotIn('fields', result['proposed'])

    def test_a_fully_classified_issue_reports_no_gaps(self):
        """The whole point of an audit is that it can come back clean."""
        issue = _node(title='[BUG] it breaks', issueType={'name': 'Bug'},
                      issueFieldValues={'nodes': [
                          _field_value('Priority', 'High'),
                          _field_value('Effort', 'Medium'),
                          _field_value('Classification', ['Bug Fix']),
                          _field_value('Origin', 'Development')]})
        result = wf_core.audit_issue(issue, dict(_AUDIT_FIELDS, **{
            'Start date': {}, 'Target date': {}}))
        self.assertEqual(_kinds(result), [])

    def test_the_proposed_entry_is_a_valid_apply_spec_once_filled(self):
        result = wf_core.audit_issue(_node(title='[BUG] it breaks'), _AUDIT_FIELDS)
        entry = result['proposed']
        entry['fields'] = dict(entry['fields'], **{'field-priority': 'High',
                                                   'field-effort': 'Medium',
                                                   'field-origin': 'Development'})
        field_map = {
            'Priority': {'id': 'p', 'data_type': 'single-select',
                         'options': {'High': 'o1'}},
            'Effort': {'id': 'e', 'data_type': 'single-select',
                       'options': {'Medium': 'o2'}},
            'Classification': {'id': 'c', 'data_type': 'multi-select',
                               'options': {'Bug Fix': 'o3'}},
            'Origin': {'id': 'o', 'data_type': 'single-select',
                       'options': {'Development': 'o4'}},
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
        findings = wf_core.label_drift_findings(['priority-medium', 'priority:medium'])
        self.assertEqual(_levels(findings), [wf_core.WARNING])
        self.assertIn('priority:medium', findings[0]['detail'])

    def test_a_dropped_prefix_is_a_warning(self):
        findings = wf_core.label_drift_findings(['ready', 'status-ready'])
        self.assertEqual(_checks(findings), ['label-drift'])
        self.assertIn('status-ready', findings[0]['fix'])

    def test_drift_never_fails_because_the_fix_deletes_data(self):
        findings = wf_core.label_drift_findings(
            ['ready', 'status-ready', 'priority:high', 'priority-high'])
        self.assertEqual(set(_levels(findings)), {wf_core.WARNING})

    def test_two_labels_that_only_look_alike_are_left_alone(self):
        self.assertEqual(wf_core.label_drift_findings(
            ['status-ready', 'status-parked', 'documentation']), [])


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

    def test_parent_unpinned_on_epic_is_not_reported_at_all(self):
        """An epic is the parent, so it has no parent to record.

        The audit used to warn about this and then say in its own fix text
        that it was correct, which is how a clean run stops meaning anything.
        """
        self.assertEqual(wf_core.pinned_field_findings(
            [self._type('User Story', self._REQUIRED + ['Parent']),
             self._type('Epic', self._REQUIRED)], self._REQUIRED), [])

    def test_the_parent_exemption_ignores_case(self):
        """The names are org-configured, so the pair is matched case-blind."""
        self.assertEqual(wf_core.pinned_field_findings(
            [self._type('Story', self._REQUIRED + ['parent']),
             self._type('epic', self._REQUIRED)], self._REQUIRED), [])

    def test_parent_missing_from_a_type_that_is_not_epic_still_warns(self):
        """Only `Epic` is exempt — a story with no `Parent` is a real gap."""
        findings = wf_core.pinned_field_findings(
            [self._type('User Story', self._REQUIRED + ['Parent']),
             self._type('Bug', self._REQUIRED),
             self._type('Epic', self._REQUIRED)], self._REQUIRED)
        self.assertEqual(_levels(findings), [wf_core.WARNING])
        self.assertIn('`Bug`', findings[0]['detail'])
        self.assertNotIn('`Epic`', findings[0]['detail'])

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
            ['priority-high', 'type-bug', 'status-ready'])
        self.assertEqual(kept, ['priority-high', 'status-ready'])
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
        labels = ['priority-low', 'status-ready']
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


class TestDeprecatedLabelFindings(unittest.TestCase):
    """The `type-*` rows that outlived what read them."""

    def test_a_mapped_type_label_is_reported_once(self):
        findings = wf_core.deprecated_label_findings(
            {'type-bug': 'bug', 'type-story': 'story', 'status-ready': 'ready'},
            ['bug', 'story', 'ready'])
        self.assertEqual(_levels(findings), [wf_core.WARNING])
        self.assertEqual(findings[0]['check'], 'type-label-deprecated')
        self.assertIn('type-bug', findings[0]['detail'])
        self.assertIn('type-story', findings[0]['detail'])

    def test_a_label_map_without_type_rows_is_clean(self):
        self.assertEqual(wf_core.deprecated_label_findings(
            {'status-ready': 'status:ready'}, ['status:ready']), [])

    def test_a_stray_type_label_nobody_maps_is_not_a_finding(self):
        """Nothing reads it, so it is clutter rather than a trap."""
        self.assertEqual(wf_core.deprecated_label_findings(
            {}, ['type-bug', 'type-story']), [])


class TestUnmappedLabelFindings(unittest.TestCase):
    """A purpose key the repo carries under a name nothing maps it to.

    This is the silent one: the label exists, the config validates, and the
    picker resolves the purpose key to a default that matches no issue -- so a
    parked issue stays in the pool and nothing anywhere says why.
    """

    LIVE = ['status:ready', 'status:parked', 'needs-refinement', 'bug']

    def test_a_near_miss_with_no_map_row_fails(self):
        findings = wf_core.unmapped_label_findings(
            {'status-ready': 'status:ready'}, self.LIVE)
        self.assertEqual(_levels(findings), [wf_core.CRITICAL])
        self.assertEqual(findings[0]['check'], 'label-unmapped')
        self.assertIn('status:parked', findings[0]['detail'])
        self.assertIn('status-parked', findings[0]['fix'])

    def test_a_mapped_key_is_not_reported(self):
        self.assertEqual(wf_core.unmapped_label_findings(
            {'status-ready': 'status:ready',
             'status-parked': 'status:parked'}, self.LIVE), [])

    def test_a_key_the_repo_carries_under_its_default_name_is_fine(self):
        """No row needed when the default is what the repo actually uses."""
        self.assertEqual(wf_core.unmapped_label_findings(
            {}, ['status-ready', 'status-parked', 'needs-refinement']), [])

    def test_a_key_the_project_simply_does_not_use_is_not_reported(self):
        """Absence is not drift. Only a near miss means the filter will fail."""
        self.assertEqual(wf_core.unmapped_label_findings({}, ['bug', 'chore']), [])

    def test_underscores_and_slashes_count_as_the_same_near_miss(self):
        findings = wf_core.unmapped_label_findings({}, ['status_blocked'])
        self.assertEqual(len(findings), 1)
        self.assertIn('status_blocked', findings[0]['detail'])


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

    IN_PROGRESS = 'status-in-progress'
    REVIEWING = ('review-reviewing', 'review-updating')

    def _issue(self, state='OPEN', labels=(IN_PROGRESS,), age=9, **kw):
        return wf_core.reap_verdict(
            'issue', age, state, list(labels),
            in_progress_label=self.IN_PROGRESS, **kw)

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

    def test_an_issue_whose_lifecycle_label_moved_on_frees_its_claim(self):
        verdict, reason = self._issue(labels=['status-ready'])
        self.assertEqual(verdict, wf_core.REAP)
        self.assertIn('in progress', reason)

    def test_an_issue_with_a_pr_already_open_frees_its_claim(self):
        """The PR is the ownership marker; the post-create release just
        did not run."""
        self.assertEqual(self._issue(has_open_pr=True)[0], wf_core.REAP)

    def test_an_in_progress_issue_with_no_pr_is_suspect_not_reaped(self):
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
        for key in ('col-backlog', 'col-ready', 'col-in-progress',
                    'col-in-review', 'col-blocked', 'col-done'):
            self.assertIn(key, wf_core.BOARD_COLUMN_NAMES)


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


if __name__ == '__main__':
    unittest.main(verbosity=2)
