#!/usr/bin/env python3
"""
Fast, offline tests for workflow decision logic.

Covers the three pure-logic areas described in the workflow templates:
  - Story selection (priority sort, mode/refinement/gating filters)
  - Label resolution (project map lookup with default fallback)
  - Backlog-mode detection (sprint vs flat from milestone presence)

No GitHub API calls, no file I/O.  Feed fixture data in, assert outputs.
Reference: github-workflow/templates/story-selection.md,
           github-workflow/templates/default-labels.md
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
    _filter_by_mode,
    actionable_update_label,
    branch_name,
    branch_slug,
    closing_issue_numbers,
    current_lifecycle_label,
    detect_backlog_mode,
    filter_by_native_type,
    get_sprint_candidates,
    parse_dependencies,
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

    # Mode filter

    def test_story_mode_accepts_any_type(self):
        """In story mode there is no type filter — all issue kinds are eligible."""
        candidates = [
            _issue(1, ['priority-medium', 'type-bug', 'status-ready']),
            _issue(2, ['priority-medium', 'type-story', 'status-ready']),
        ]
        # Both eligible; lowest number wins
        self.assertEqual(select_story(candidates, mode='story')['number'], 1)

    def test_feature_mode_keeps_only_type_story(self):
        candidates = [
            _issue(1, ['priority-high', 'type-bug', 'status-ready']),
            _issue(2, ['priority-medium', 'type-story', 'status-ready']),
        ]
        self.assertEqual(select_story(candidates, mode='feature')['number'], 2)

    def test_feature_mode_no_eligible_returns_none(self):
        candidates = [_issue(1, ['priority-high', 'type-bug', 'status-ready'])]
        self.assertIsNone(select_story(candidates, mode='feature'))

    def test_maintenance_mode_accepts_all_non_story_types(self):
        candidates = [
            _issue(1, ['priority-medium', 'type-story', 'status-ready']),   # excluded
            _issue(2, ['priority-medium', 'type-bug', 'status-ready']),
            _issue(3, ['priority-medium', 'type-security', 'status-ready']),
            _issue(4, ['priority-medium', 'type-debt', 'status-ready']),
            _issue(5, ['priority-medium', 'type-arch', 'status-ready']),
        ]
        pool = _filter_by_mode(candidates, mode='maintenance')
        numbers = {c['number'] for c in pool}
        self.assertNotIn(1, numbers)
        self.assertIn(2, numbers)
        self.assertIn(3, numbers)
        self.assertIn(4, numbers)
        self.assertIn(5, numbers)

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
    project map, exactly like the inline `story-selection.md` path — otherwise a
    project that renames labels diverges from the inline path and the pool comes
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

    def test_feature_mode_uses_remapped_type_label(self):
        candidates = [
            _issue(1, ['P1', 'kind-bug']),     # renamed type-bug → excluded
            _issue(2, ['P2', 'kind-story']),   # renamed type-story → kept
        ]
        self.assertEqual(
            select_story(candidates, mode='feature',
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
    """Fixed dependency markers from story-selection.md Step 3."""

    def test_extracts_each_marker_form(self):
        body = "Depends on #1. Blocked by #2. After #3. Requires #4."
        deps, overflow = parse_dependencies(body)
        self.assertEqual(deps, [1, 2, 3, 4])
        self.assertFalse(overflow)

    def test_is_case_insensitive(self):
        deps, _ = parse_dependencies("DEPENDS ON #7 and Requires #8")
        self.assertEqual(deps, [7, 8])

    def test_dependencies_section_hash_refs(self):
        body = "## Context\nbuild it\n## Dependencies\n- #11\n- #12\n## Notes\nsee #99"
        deps, _ = parse_dependencies(body)
        # #99 is in Notes, not Dependencies, and matches no marker → excluded
        self.assertEqual(deps, [11, 12])

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


class TestBranchNaming(unittest.TestCase):
    """Deterministic slug + convention rendering from start-story.md Step 6."""

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
    """update-pr pool: my PRs with actionable feedback, prioritised."""

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

    def test_candidate_without_type_info_excluded(self):
        candidates = [_issue(99, [])]
        result = filter_by_native_type(candidates, 'feature', self.TYPE_MAP)
        self.assertEqual(result, [])

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

    def test_select_pool_falls_back_to_labels_without_type_map(self):
        """Without type_map, select_pool uses label-based filtering as before."""
        candidates = [
            _issue(1, ['priority-high', 'type-story']),
            _issue(2, ['priority-medium', 'type-bug']),
        ]
        pool = select_pool(candidates, mode='feature')
        self.assertEqual([c['number'] for c in pool], [1])


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


if __name__ == '__main__':
    unittest.main(verbosity=2)
