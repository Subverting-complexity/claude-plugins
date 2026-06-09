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
import unittest

# ── Reference implementation ─────────────────────────────────────────────────
# These functions encode the decision rules from the workflow templates.
# They are the test subject, not production code — but they serve as a
# canonical, executable description of the same logic Claude applies at
# runtime.

_PRIORITY_ORDER = ['priority-critical', 'priority-high', 'priority-medium', 'priority-low']


def _priority_rank(labels):
    """Returns sort key: 0=critical … 3=low, 4=no priority label."""
    for i, p in enumerate(_PRIORITY_ORDER):
        if p in labels:
            return i
    return len(_PRIORITY_ORDER)


def _filter_by_mode(candidates, mode):
    """Apply mode filter.

    story       — no type filter; all issues are eligible.
    feature     — keep type-story issues only.
    maintenance — keep bug / security / debt / architecture issues only.
    """
    if mode == 'story':
        return list(candidates)
    feature_labels = {'type-story'}
    maintenance_labels = {'type-bug', 'type-security', 'type-debt', 'type-arch'}
    keep = feature_labels if mode == 'feature' else maintenance_labels
    return [c for c in candidates if any(lbl in keep for lbl in c.get('labels', []))]


def _filter_refinement(candidates):
    """Exclude issues that carry needs-refinement — not yet ready for pickup."""
    return [c for c in candidates if 'needs-refinement' not in c.get('labels', [])]


def _filter_agent_gating(candidates, agent_gating):
    """If gating is enabled, keep only human-approved (claude-ready) issues."""
    if agent_gating != 'enabled':
        return list(candidates)
    return [c for c in candidates if 'claude-ready' in c.get('labels', [])]


def _sort_candidates(candidates):
    """Sort by priority descending (critical first), then ascending issue number."""
    return sorted(candidates, key=lambda c: (_priority_rank(c.get('labels', [])), c['number']))


def select_story(candidates, mode='story', agent_gating='disabled'):
    """Full selection pipeline: filter → sort → top candidate (or None)."""
    pool = _filter_by_mode(candidates, mode)
    pool = _filter_refinement(pool)
    pool = _filter_agent_gating(pool, agent_gating)
    pool = _sort_candidates(pool)
    return pool[0] if pool else None


# Default label names from github-workflow/templates/default-labels.md.
# Each entry maps a purpose key to the concrete label name used when a
# project has not defined a custom mapping.
_DEFAULT_LABELS = {
    'type-story': 'type-story',
    'type-bug': 'type-bug',
    'type-security': 'type-security',
    'type-debt': 'type-debt',
    'type-arch': 'type-arch',
    'priority-critical': 'priority-critical',
    'priority-high': 'priority-high',
    'priority-medium': 'priority-medium',
    'priority-low': 'priority-low',
    'claude-ready': 'claude-ready',
    'claude-authored': 'claude-authored',
    'status-ready': 'status-ready',
    'needs-refinement': 'needs-refinement',
    'status-in-progress': 'status-in-progress',
    'status-parked': 'status-parked',
    'status-blocked': 'status-blocked',
    'status-in-review': 'status-in-review',
    'status-needs-attention': 'status-needs-attention',
}


def resolve_label(purpose_key, project_map, defaults=None):
    """Resolve a purpose key to a concrete label name.

    Resolution order (from default-labels.md — "The single resolution path"):
    1. Project map (ClaudeProject.md label map, already in context at runtime).
    2. Default inventory (the table in default-labels.md).
    3. The key itself as a last resort so callers never get an empty string.
    """
    if defaults is None:
        defaults = _DEFAULT_LABELS
    return project_map.get(purpose_key) or defaults.get(purpose_key) or purpose_key


def detect_backlog_mode(candidates):
    """Return 'sprint' if any candidate has a milestone, otherwise 'flat'.

    From story-selection.md Step 2: presence of any milestone field triggers
    sprint mode; the active sprint is then resolved via a separate API call.
    An empty pool has no milestones and therefore defaults to flat.
    """
    return 'sprint' if any(c.get('milestone') for c in candidates) else 'flat'


def get_sprint_candidates(candidates, sprint_title):
    """Narrow candidates to those belonging to the active sprint."""
    return [c for c in candidates if c.get('milestone') == sprint_title]


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


if __name__ == '__main__':
    unittest.main(verbosity=2)
