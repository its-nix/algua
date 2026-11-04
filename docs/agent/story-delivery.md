# Delivery workflow

Owner direction, 2026-11-04: prioritize working software and short iterations.

- Start with the requested behavior and existing code. Implement a small runnable slice.
- Use focused regression or smoke checks appropriate to the change. Do not run the full suite
  or wait for CI on every small change; use broad validation for broad integration work or on request.
- Do not require a separate specification PR, readiness report, Todoist mirror, mutation campaign,
  multi-agent review or evidence framework for routine implementation. BMAD planning is optional
  unless the owner specifically requests it for the task.
- Review concrete correctness, data-loss and authorization risks. Gather findings in one bounded
  pass and verify fixes directly. Do not restart a general audit for optional improvements.
- Reuse existing commands and infrastructure. Keep notes proportional; finish the working flow
  before adding polish, abstractions or speculative edge cases.
- Preserve user work, use scoped commits and branches, and report actual checks and omissions.
  A canceled or skipped check is never a pass.

Product controls remain in force: human-only live activation, capital limits, next-bar execution,
point-in-time disclosures and reproducible identities. This delivery policy changes development
ceremony, not permission to trade or bypass signed authorization.

Automatic repository CI/CD is disabled. `.github/workflows/ci.yml` retains its full checks behind
`workflow_dispatch` for later use. When desired, re-enable the workflow and dispatch it explicitly;
there is no requirement to do so before each small commit.
