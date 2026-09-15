#!/usr/bin/env python3
"""
Pure decision logic for the `wf` workflow CLI.

This module is the **canonical, executable** encoding of the selection rules
that the workflow templates describe in prose — story selection, label
resolution, backlog-mode detection, dependency parsing, and branch naming.

It is deliberately **pure**: no GitHub API calls, no `git`, no file or network
I/O. Feed plain dicts/strings in, get decisions out. The I/O shell that talks
to `gh`/`git` lives in `wf.py`; the offline test suite
(`tests/test_decision_logic.py`) imports *this* module directly so the rules
stay verifiable without a network.

The rules themselves live in the `wf_core_*` modules, one concern each (see
`scripts/README.md` for the map). This module imports them all and re-exports
every name they define, so `wf_core.X` and `from wf_core import X` keep
working for the shell and the tests alike. A new rule goes in the module whose
concern it belongs to, never here.

Reference templates (the prose these functions encode):
  - synergy/skills/pr-review/references/review-workflow.md  (review labels)
  - synergy/skills/execute/SKILL.md  (branch convention)
"""

import wf_core_findings
import wf_core_fields
import wf_core_refs
import wf_core_stage
import wf_core_spec
import wf_core_audit
import wf_core_select
import wf_core_bulk
import wf_core_claims
import wf_core_drift
import wf_core_pool
import wf_core_review
import wf_core_preflight
import wf_core_repair
import wf_core_scratch
import wf_core_schedule

_MODULES = (
    wf_core_findings, wf_core_fields, wf_core_refs, wf_core_stage, wf_core_spec,
    wf_core_audit, wf_core_select, wf_core_bulk, wf_core_claims, wf_core_drift,
    wf_core_pool, wf_core_review, wf_core_preflight, wf_core_repair,
    wf_core_scratch, wf_core_schedule,
)

for _module in _MODULES:
    globals().update((name, value) for name, value in vars(_module).items()
                     if not name.startswith('__'))
del _module
