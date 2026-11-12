# Capability-aware source selection

Approved in chat: rank material by actual pilot feasibility, explore a bounded shortlist, track
blockers per source, and validate declared recipe/control history before authoring. Work in4cdb,
use focused checks and bounded review, merge/deploy under existing authorization. No new services,
DB schema, qualification/live gate edits, source relabeling or data purchase.

- Add pure recipe assessment using the observed profile and existing window_capacity. All control
  requirements count. A feasible declaration is advisory; authored CONFIG still gets its own check.
- Build a deterministic three-source plan from bounded notes plus source hashes, capability/profile
  identity and per-source operational progress. Feasible first, unknown next, blocked backlog.
  New notes do not reset other notes' retry state; source/profile/code changes may reopen them.
- Add CLI plan/review adapters. Require structured source reviews, validate actual new scratch
  ideas against offered feasible source recipes, retain incomplete coverage honestly, and record
  per-source progress only for clean worker/import finalization. Keep refuted/dedup walls intact.
- Integrate the configured leap driver; retire the global empty-pass freeze for this path. Supply
  forage with the recipe schema and require leap to traverse the offered shortlist. Preserve legacy
  unconfigured behavior and all resource caps.
- Test ranking/controls/history, per-source reset/failure paths, source-to-idea/import/queue handoff,
  and a real bounded production pass. A genuine negative result is valid; admission is not profit.
