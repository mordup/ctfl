---
name: confidence-assessment
description: "Confidence scoring framework for agent findings. Provides a 5-tier scale with context-adapted anchors for auditing, QA, and architecture."
user-invocable: false
---

# Confidence Assessment Framework

Every substantive finding or recommendation MUST include a confidence tier. This prevents speculation from being treated as fact and helps prioritize action.

## Tiers

| Tier | Label | Meaning |
|------|-------|---------|
| 5 | **CONFIRMED** | Verified by tracing the complete code path, or reproduced |
| 4 | **HIGH** | Strong evidence from code reading; minor ambiguity remains (e.g. depends on runtime state) |
| 3 | **PROBABLE** | Reasonable inference from code structure, but path not fully traced |
| 2 | **POSSIBLE** | Plausible scenario, but significant assumptions involved |
| 1 | **SPECULATIVE** | Theoretically possible; needs investigation before acting on |

## Context-Adapted Anchors

### Code Auditing (code-auditor)
- **CONFIRMED**: Read the full data flow from input to output, bug is certain
- **HIGH**: Read the relevant functions, issue is clear but depends on caller behavior
- **PROBABLE**: Pattern matches a known bug class, but didn't trace all callers
- **POSSIBLE**: Code looks fragile but couldn't construct a triggering scenario
- **SPECULATIVE**: Theoretical concern based on general security principles

### Quality Analysis (quality-analyst)
- **CONFIRMED**: Tested the interaction by reading all config toggle paths end-to-end
- **HIGH**: Read the UI code path, inconsistency is visible in the code
- **PROBABLE**: Formatting looks wrong based on similar patterns elsewhere
- **POSSIBLE**: Edge case that depends on specific API response shape
- **SPECULATIVE**: UX concern based on general principles, not code evidence

### Architecture (python-architect)
- **CONFIRMED**: Mapped the full dependency graph, recommendation is grounded
- **HIGH**: Read the key modules, coupling/cohesion assessment is solid
- **PROBABLE**: Architectural judgment based on module structure, didn't trace all edges
- **POSSIBLE**: Design concern based on growth trajectory, not current pain
- **SPECULATIVE**: Pattern from other projects that may or may not apply here

## Usage

Always append confidence to findings:

```
## [SEVERITY] Title — Confidence: TIER

...
```

When confidence is POSSIBLE or SPECULATIVE, explicitly state what investigation would raise it. Don't present low-confidence findings as actionable without flagging them.
