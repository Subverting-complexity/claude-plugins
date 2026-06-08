# Graph Report - .  (2026-06-07)

## Corpus Check
- 118 files · ~139,932 words
- Verdict: corpus is large enough that graph structure adds value.

## Summary
- 265 nodes · 384 edges · 24 communities (15 shown, 9 thin omitted)
- Extraction: 92% EXTRACTED · 8% INFERRED · 0% AMBIGUOUS · INFERRED: 30 edges (avg confidence: 0.82)
- Token cost: 27,000 input · 6,600 output

## Community Hubs (Navigation)
- [[_COMMUNITY_Code Review & Quality Standards|Code Review & Quality Standards]]
- [[_COMMUNITY_GitHub Workflow Plugin Schema|GitHub Workflow Plugin Schema]]
- [[_COMMUNITY_GitHub Workflow Commands & Agents|GitHub Workflow Commands & Agents]]
- [[_COMMUNITY_Monorepo Rules & Project Config|Monorepo Rules & Project Config]]
- [[_COMMUNITY_Shared Skills & Design References|Shared Skills & Design References]]
- [[_COMMUNITY_Issue & Board Lifecycle|Issue & Board Lifecycle]]
- [[_COMMUNITY_Software Architecture Principles|Software Architecture Principles]]
- [[_COMMUNITY_Architecture & Acceptance Skills|Architecture & Acceptance Skills]]
- [[_COMMUNITY_Local Workflow Plugin Manifest|Local Workflow Plugin Manifest]]
- [[_COMMUNITY_Marketplace Plugin Config|Marketplace Plugin Config]]
- [[_COMMUNITY_Auto-Merge & CI Gates|Auto-Merge & CI Gates]]
- [[_COMMUNITY_Skill Sync (Bash)|Skill Sync (Bash)]]
- [[_COMMUNITY_Skill Sync (PowerShell)|Skill Sync (PowerShell)]]
- [[_COMMUNITY_Webhook Hook Config|Webhook Hook Config]]
- [[_COMMUNITY_Bootstrap Script (Bash)|Bootstrap Script (Bash)]]
- [[_COMMUNITY_Skill Linter|Skill Linter]]
- [[_COMMUNITY_Body File Safety|Body File Safety]]
- [[_COMMUNITY_Worktree Hygiene|Worktree Hygiene]]
- [[_COMMUNITY_GitHub Workflow Settings|GitHub Workflow Settings]]
- [[_COMMUNITY_Local Workflow Hooks|Local Workflow Hooks]]
- [[_COMMUNITY_Guide Command|Guide Command]]
- [[_COMMUNITY_Grill-Me Dependency|Grill-Me Dependency]]

## God Nodes (most connected - your core abstractions)
1. `Execute Skill (End-to-End Story Execution)` - 16 edges
2. `Shared Skills Manifest` - 15 edges
3. `Code Review Skill` - 14 edges
4. `Plain-English Wording Standard` - 13 edges
5. `Feature Discovery Skill` - 13 edges
6. `Wording Standard (Plain-English Output)` - 13 edges
7. `Plain-English Wording Standard` - 12 edges
8. `Banned Output Patterns` - 10 edges
9. `Banned Patterns (Output Anti-Patterns)` - 10 edges
10. `Synced Skill (Shared Skill Copy)` - 10 edges

## Surprising Connections (you probably didn't know these)
- `Fitness Functions for Architecture Compliance` --semantically_similar_to--> `CI GitHub Workflow`  [INFERRED] [semantically similar]
  _shared-skills/code-architect/references/fundamentals-of-software-architecture.md → .github/workflows/ci.yml
- `GoF Design Patterns (Creational, Structural, Behavioral)` --semantically_similar_to--> `SOLID Principles`  [INFERRED] [semantically similar]
  local-workflow/skills/code-architect/references/design-patterns.md → _shared-skills/code-architect/references/clean-architecture.md
- `Story Template (12-section Issue Format)` --semantically_similar_to--> `Project Configuration Template (ClaudeProject.md)`  [INFERRED] [semantically similar]
  local-workflow/references/story-template.md → github-workflow/templates/ClaudeProject.md
- `Story Template Reference` --semantically_similar_to--> `User Story Skill`  [INFERRED] [semantically similar]
  github-workflow/references/story-template.md → _shared-skills/user-story/SKILL.md
- `User Story Skill` --semantically_similar_to--> `Acceptance Criteria Skill`  [INFERRED] [semantically similar]
  _shared-skills/user-story/SKILL.md → github-workflow/skills/acceptance-criteria/SKILL.md

## Import Cycles
- None detected.

## Hyperedges (group relationships)
- **Skill Output Quality System (wording standard + banned patterns applied by all skills)** — shared_wording_standard, shared_banned_patterns, skill_acceptance_criteria, skill_code_architect, skill_debugging, skill_doc_writer, skill_feature_discovery, skill_grill_me, skill_pr_description, skill_repo_scaffolding, skill_security_audit, skill_structured_coding [EXTRACTED 1.00]
- **Shared Skill Sync Integrity Enforcement (pre-commit hook + CI + editorial rules)** — hooks_precommit, workflows_ci_synccheck, claude_synced_skill_rule, claude_sync_after_edit_rule, concept_sync_marker [EXTRACTED 1.00]
- **Plugin Release Governance (version bumping + CI validation + semver rules)** — claude_version_bump_rule, concept_plugin_version_semver, workflows_ci_versionbumpcheck, workflows_ci_validatepluginsjson [EXTRACTED 1.00]
- **Worktree Clean State Enforcement (All Exit Commands)** — commands_block_story, commands_finish_story, commands_update_pr [EXTRACTED 1.00]
- **Shared Plain-English Output Standard (Skills + Commands)** — skills_shared_wording_standard, skills_shared_banned_patterns, concept_plain_english_output [EXTRACTED 1.00]
- **End-to-End Story Lifecycle (Pick → Start → Finish)** — commands_pick_story, commands_start_story, commands_finish_story [EXTRACTED 1.00]
- **PR Lifecycle Automation (Execute → Code Review → Auto-Merge)** — execute_finish_self_review, code_review_skill, code_review_auto_merge [EXTRACTED 0.95]
- **Claim-Based Concurrency Safety Pattern** — code_review_claim_procedure, code_review_concurrency_rules, execute_exit_cleanup [EXTRACTED 0.95]
- **Shared Wording Standard Across All Skills** — wording_standard, code_review_skill, debugging_skill, execute_skill, feature_discovery_skill, structured_coding_skill, security_audit_skill, verify_feature_skill, repo_scaffolding_skill, doc_writer_skill, grill_me_skill, pr_description_skill, user_story_skill [EXTRACTED 1.00]
- **Atomic Claim, Story Selection, and Board Update Workflow** — templates_claim_procedure_atomic_claim, templates_story_selection_procedure, templates_board_resolution_procedure [EXTRACTED 1.00]
- **Label Resolution Invariant: Purpose Keys, Lifecycle Labels, and Board Columns** — concept_purpose_key_resolution, concept_issue_lifecycle_labels, concept_board_column_mirror [EXTRACTED 1.00]
- **Code Architect Reference Triad: Clean Architecture, Design Patterns, Architecture Fundamentals** — code_architect_clean_architecture_ref, code_architect_design_patterns_ref, code_architect_fundamentals_ref [EXTRACTED 1.00]
- **Plain-English Output Convention (wording-standard + banned-patterns)** — wording_standard_concept, banned_patterns_concept, debugging_skill, structured_coding_skill, security_audit_skill, verify_feature_skill, mobile_audit_skill, feature_discovery_skill, repo_scaffolding_skill, execute_skill, grill_me_skill [EXTRACTED 1.00]
- **Execute Orchestration Pipeline (code-architect + structured-coding + grill-me)** — execute_skill, code_architect_skill_ref, structured_coding_skill, grill_me_skill [EXTRACTED 1.00]
- **Story Planning Skills Cluster (feature-discovery + repo-scaffolding + user-story)** — feature_discovery_skill, repo_scaffolding_skill, user_story_skill, story_template_ref, dag_dependency_concept [INFERRED 0.95]

## Communities (24 total, 9 thin omitted)

### Community 0 - "Code Review & Quality Standards"
Cohesion: 0.07
Nodes (53): Banned Patterns (Output Anti-Patterns), code-architect Skill (dependency reference), Atomic Claim Procedure (refs/claims/pr-N), PR Claim Concurrency Rules (Atomic Ref Lock), Duplicate PR Reconciliation Reference (Step 2b), PR Review State Labels, Re-Review Significance Assessment Reference (Step 4b), Code Review Read-Only Mode (+45 more)

### Community 1 - "GitHub Workflow Plugin Schema"
Cohesion: 0.07
Nodes (29): default, description, title, type, default, description, title, type (+21 more)

### Community 2 - "GitHub Workflow Commands & Agents"
Cohesion: 0.19
Nodes (26): Builder Agent, DocWriter Agent, Reviewer Agent, Block Story Command, Finish Story Command, Pick Story Command, Report Issue Command, Setup Command (+18 more)

### Community 3 - "Monorepo Rules & Project Config"
Cohesion: 0.12
Nodes (22): Always Commit and Open PR When Work Complete, Claude Plugins Monorepo, Always Run sync-skills After Editing, Never Edit Synced Skill Copy Rule, Bump Plugin Version Before Merging Rule, claude-plugins GitHub Project Board, ClaudeProject Configuration, Label Map for Workflow Automation (+14 more)

### Community 4 - "Shared Skills & Design References"
Cohesion: 0.19
Nodes (22): Acyclic Story Dependency Chain (DAG Validation), Deferred Speccing for Large Features, Plain-English Reader-First Output Principle, Template Variable Substitution (PLUGIN_NAME, PLUGIN_VERSION), Shared Skills Manifest, Design Patterns Reference (Gang of Four), Behavioral Patterns (Chain of Responsibility, Command, Iterator, Mediator, Memento, Observer, State, Strategy, Template Method, Visitor), Creational Patterns (Abstract Factory, Builder, Factory Method, Prototype, Singleton) (+14 more)

### Community 5 - "Issue & Board Lifecycle"
Cohesion: 0.15
Nodes (19): Atomic Claim Lock via Git Refs, Board Column as Mirror of Issue Lifecycle Labels, Claim-first, Validate-lazily Selection Strategy, closingIssuesReferences GraphQL Field for PR Deduplication, Dual-tracked Priority (label + field), Issue Lifecycle State Labels (mutually exclusive), Native GitHub Issue Types (capability-gated), Purpose Key Label Resolution (apply == filter invariant) (+11 more)

### Community 6 - "Software Architecture Principles"
Cohesion: 0.12
Nodes (18): Clean Architecture Reference (Robert C. Martin), Clean Architecture Concentric Layers (Entities, Use Cases, Adapters, Frameworks), Dependency Rule (source code dependencies point inward), Fitness Functions for Architecture Compliance, Humble Object Pattern (testability at boundaries), Screaming Architecture (domain-visible top-level structure), Component Principles (REP, CCP, CRP, ADP, SDP, SAP), Dependency Rule (source dependencies point inward) (+10 more)

### Community 7 - "Architecture & Acceptance Skills"
Cohesion: 0.15
Nodes (17): Acceptance Criteria Skill, Design Patterns Reference (Gang of Four), Fundamentals of Software Architecture Reference (Richards & Ford), Code Architect Skill, Architecture Styles (Layered, Microkernel, Service-Based, Event-Driven, Microservices), GoF Design Patterns (Creational, Structural, Behavioral), Banned Output Patterns, local-workflow Plugin README (+9 more)

### Community 8 - "Local Workflow Plugin Manifest"
Cohesion: 0.20
Nodes (9): author, name, description, displayName, keywords, license, name, repository (+1 more)

### Community 9 - "Marketplace Plugin Config"
Cohesion: 0.22
Nodes (8): description, keywords, license, name, owner, name, plugins, repository

### Community 10 - "Auto-Merge & CI Gates"
Cohesion: 0.28
Nodes (9): Auto-Merge on Approval Reference, CI Gate Enforcement (GitHub vs Plugin-side), require-ci-before-merge Setting, Review Config Generation Guide, review.config.md Template, review.config.md (PR Review Configuration), Preflight Auto-Merge Safety Checks Reference, Preflight Critical vs Warning Classification (+1 more)

### Community 11 - "Skill Sync (Bash)"
Cohesion: 0.47
Nodes (3): sync-skills.sh script, remove_orphaned_files(), sync_directory()

### Community 12 - "Skill Sync (PowerShell)"
Cohesion: 0.60
Nodes (3): Get-PluginVersion(), Process-MdContent(), Sync-Directory()

## Knowledge Gaps
- **86 isolated node(s):** `name`, `name`, `description`, `repository`, `license` (+81 more)
  These have ≤1 connection - possible missing edges or undocumented components.
- **9 thin communities (<3 nodes) omitted from report** — run `graphify query` to explore isolated nodes.

## Suggested Questions
_Questions this graph is uniquely positioned to answer:_

- **Why does `SOLID Principles` connect `Software Architecture Principles` to `Architecture & Acceptance Skills`?**
  _High betweenness centrality (0.140) - this node is a cross-community bridge._
- **Why does `Clean Architecture Reference (Robert C. Martin)` connect `Software Architecture Principles` to `Shared Skills & Design References`?**
  _High betweenness centrality (0.114) - this node is a cross-community bridge._
- **Why does `Code Architect Skill` connect `Shared Skills & Design References` to `Software Architecture Principles`?**
  _High betweenness centrality (0.107) - this node is a cross-community bridge._
- **What connects `name`, `name`, `description` to the rest of the system?**
  _100 weakly-connected nodes found - possible documentation gaps or missing edges._
- **Should `Code Review & Quality Standards` be split into smaller, more focused modules?**
  _Cohesion score 0.06966618287373004 - nodes in this community are weakly interconnected._
- **Should `GitHub Workflow Plugin Schema` be split into smaller, more focused modules?**
  _Cohesion score 0.06666666666666667 - nodes in this community are weakly interconnected._
- **Should `Monorepo Rules & Project Config` be split into smaller, more focused modules?**
  _Cohesion score 0.11688311688311688 - nodes in this community are weakly interconnected._