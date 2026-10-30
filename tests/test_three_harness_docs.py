"""Doc-contract guard for the three-harness reconciliation (plan Task 0).

Guards are pure text checks under a caller-supplied root, so they can be mutation-checked on
`tmp_path` copies without touching a real safety file. Matching runs on normalized blocks
(paragraph, list item, table row, heading) and pins coupled claims, not bare words. Passing proves
what the docs say; it grants no authority and proves nothing about runtime enforcement.
"""

from __future__ import annotations

import re
import shutil
from collections.abc import Callable
from pathlib import Path
from typing import NamedTuple

import pytest

REPO = Path(__file__).resolve().parent.parent
PRD = "docs/PRD.md"
DELIVERY = "docs/agent/story-delivery.md"
OPERATING = "docs/agent/operating.md"
RECONCILIATION = "docs/vision-reconciliation.md"
DECISIONS = "docs/.decision-log.md"
DEV_README = "docs/development/README.md"
BOARD_SPEC = "docs/development/stories/spec-strategy-board.md"
BOARD_CONTRACT = "docs/development/specs/spec-strategy-board/strategy-board-contract.md"
UNRELAXED = "docs/development/specs/spec-story-2-1-unrelaxed-live-qualification/SPEC.md"
DESIGN = "docs/superpowers/specs/2026-10-30-algua-three-harness-design.md"
PLAN = "docs/superpowers/plans/2026-10-30-algua-three-harness-implementation.md"
READINESS = "docs/development/implementation-readiness-report-2026-10-30-three-harness.md"
OBSERVED = "docs/development/observed-target-report-2026-10-30-three-harness.md"
GUIDES = ("AGENTS.md", "CLAUDE.md", PRD, "docs/architecture.md", RECONCILIATION, OPERATING,
          DELIVERY, DEV_README)
GUARDED = (*GUIDES, DECISIONS, BOARD_SPEC, BOARD_CONTRACT, UNRELAXED, DESIGN, PLAN, READINESS,
           OBSERVED)

TARGET_BLOCKED = r"\btarget[- ]blocked\b"
OWNER_APPROVAL = (r"(?:lior|owner)(?:['’]s)?\s+(?:\w+\s+){0,2}?approv\w+"
                  r"|(?:lior|owner)\s+(?:must\s+)?approves?")
TEN_CYCLES = r"\b(?:10|ten)\s+(?:completed\s+)?unattended(?:\s+[\w-]+){0,3}\s+cycles\b"
HUNDRED_ATTEMPTS = r"(?:>=|≥|at least)\s*100\b"

# Section -> (title, phrases that must survive, approved concepts that amendment must add).
PRD_SECTIONS: dict[int, tuple[str, tuple[str, ...], tuple[str, ...]]] = {
    1: ("North Star", ("the ultimate product is net trading profit",),
        ("personally funded", "multimodal research factory")),
    2: ("Priority order", ("1. net profitability",), ()),
    3: ("Economic thesis", ("volatility is not mispricing",), ()),
    4: ("AI and LLM thesis", ("an ai component receives no statistical shortcut",),
        (r"\bopencode\b", r"(?:no|never)\b[^.]*\bagent\b[^.]*\borders\b")),
    5: ("One Algua, not prod Algua versus dev Algua",
        ("there is one product, one repository and one architecture",), ()),
    6: ("Architecture", ("modular monolith + isolated live runtime + background workers",),
        (r"hermes[^.]*engineering", r"\bopencode\b", "strategy leaderboard")),
    7: ("Strategy contract", ("do not create separate strategy implementations",),
        ("per-symbol score",)),
    8: ("Research philosophy", ("negative results are valuable outputs",),
        (r"\bvariants?\b", r"\bbreadth\b")),
    9: ("Experiment memory is a moat", ("agents must search prior experiments",),
        ("failed runs", "second research database")),
    10: ("Reproducibility and research integrity", ("it cannot justify promotion",),
         (r"replay[^.]*(?:cannot|never)[^.]*forward",)),
    11: ("Data", ("canonical local, versioned historical dataset",),
         ("pilot_real_proxy", "yfinance", r"not\b[^.]*point-in-time")),
    12: ("Markets and timeframes", ("high-frequency/tick-level trading is outside",),
         (r"\$0\.5–10b", r"price >= \$5", r"dollar volume >= \$5m", "90-session", "end-of-day",
          r"next-eligible-session", r"no sl/tp is obligatory")),
    13: ("Portfolio", ("no aggressive kelly sizing",), ("across-strategy", "not sl/tp")),
    14: ("Strategy deterioration", ("replacing it requires the replacement to pass",), ()),
    15: ("Live operation philosophy", ("stopping trading requires less authority",), ()),
    16: ("Shadow and paper operation", ("paper and shadow execution remain permanent",), ()),
    17: ("Autonomous engineering", ("runtime evidence is evidence—not authority",),
         (r"\bhermes\b", TARGET_BLOCKED)),
    18: ("Engineering autonomy boundaries", ("agents must never modify their own authority",),
         (TARGET_BLOCKED, OWNER_APPROVAL)),
    19: ("Human authority", ("first activation of a strategy into real-money live trading",
                             "agents may never independently raise the maximum capital"),
         (r"\bcredentials\b", OWNER_APPROVAL)),
    20: ("Operational autonomy", ("72 hours unattended",), (r"\bsystemd\b", r"hermes[^.]*monitor")),
    21: ("Capital", ("₪10,000", "₪6,000", "10% drawdown of the live experimental account",
                     "no automatic increase in approved capital"),
         ("no leverage", "authenticated owner authorization")),
    22: ("External and funded capital", ("headline \"account size\"",), ()),
    23: ("Initial success criteria", ("positive net live p&l",),
         ("machine acceptance", "investment acceptance")),
    24: ("90-day objective", ("one real strategy end to end",),
         (TEN_CYCLES, HUNDRED_ATTEMPTS, r"\bunknown\b")),
    25: ("Development sequence", ("phase 8 — market breadth",),
         ("2026-10-30-algua-three-harness-implementation",)),
    26: ("Code philosophy", ("new abstractions require demonstrated repeated need",),
         (r"\bno second\b",)),
    27: ("Explicit non-goals", ("an hft/tick-level trading system",), ()),
    28: ("Roadmap admission test", ("how can this improve",), ()),
    29: ("When to stop", ("the correct response to failure is learning",), ()),
    30: ("The standard", ("make money. preserve knowledge. control risk.",), ()),
}
BINDING = {
    "AGENTS.md": ("actor == actor.human", "a matching unrevoked row in approvals",
                  "frozen data contract for dataprovider.get_bars"),
    "CLAUDE.md": ("you may never put a strategy live", "a bare --actor human unlocks nothing",
                  "requires a verified human approval and a fresh forward-test certificate"),
    "docs/architecture.md": ("needs a verified human signature plus a fresh forward certificate",),
    RECONCILIATION: ("real-money activation still requires the signed human ceremony",),
    OPERATING: ("two-step signed ceremony", "ssh-keygen -y sign -n algua-go-live",
                "the forward certificate is not waivable in-band"),
    DELIVERY: ("does not merge, deploy, activate trading, allocate capital or expand an authority "
               "boundary", "no worker writes to the main checkout"),
    DEV_README: ("a code merge is not authorization to deploy, trade or allocate capital",),
    UNRELAXED: ("nobody, human included, can waive that",),
    BOARD_SPEC: ("keep lifecycle order as the default", "any use of board order in research "
                 "promotion", "compute a composite score, recommend a winner"),
    BOARD_CONTRACT: ("may never replace latest_gate or feed a promotion path",),
}
AUTHORITY_STATEMENTS = (
    ("routing", (r"hermes kanban[^.;]*engineering", r"github[^.;]*evidence",
                 r"todoist[^.;]*\b(?:human|lior)\b")),
    ("approval", (r"\bmerges?\b", r"\bdeployments?\b", r"\bcredentials?\b", r"\bdestructive\b",
                  r"\bexternal\b", r"\bprotected\b", OWNER_APPROVAL)),
    ("automation", (r"auto[- ]?merg", r"paper ci/cd", TARGET_BLOCKED)),
)
TODOIST_QUEUE = (r"shared (?:algua )?todoist|todoist is the shared|mirror\w*\b.{0,80}\btodoist\b"
                 r"|\btodoist\b.{0,80}\b(?:mirror\w*|execution queue|claimable)\b")
MERGE_STEP = (r"\bgh pr merge\b|\bgit merge\b|\bgit push\b[^.]*\bmain\b|\bmerge through\b"
              r"|\bdeploy by\b|\bfast-forward\w*\b[^.]*\b(?:main|checkout)\b")
AUTOMATION = (r"\bauto[- ]?merg\w*|\bautonomous merges?\b(?!-)|\bautomatic merges?\b"
              r"|\bauto[- ]?deploy\w*|\bautomatic paper\b|\bpaper ci/cd\b")
UNGATED_GRANT = r"\b(?:merg|deploy)\w*[^.;]*\bwithout\s+(?:\w+\s+){0,2}?(?:lior|owner)\b"
NEGATED = r"\b(?:never|not|cannot|no)\b"
LIVE_GRANT = r"\bagents?\s+(?:may|can)\s+[^.]*\b(?:go|put|promot\w*|activat\w*)\b[^.]*\blive\b"
LANDMARKS = {
    DESIGN: ("02_architecture_design.md", *(f"## {n}. " for n in range(1, 13)),
             "critical strategy sandbox gate"),
    PLAN: ("03_implementation_plan.md", *(f"### task {n} —" for n in range(11)), "- [ ] step 5:",
           "## global constraints", "## cutover and rollback rules", "## plan review / execution"),
}
PROVENANCE = (r"origin\w*\s+source[^.]*\bproposed\b", r"owner direction[^.]*\bapproved\b",
              r"new controls?[^.]*\bnot\b[^.]*\bimplemented\b", TARGET_BLOCKED, OWNER_APPROVAL)
CLAIMED_CONTROLS = r"new controls?\s+(?:are|is)\s+(?:now\s+)?(?:implemented|enabled|active)\b"
OBSERVED_FACTS = (
    "db6860000f87a6cc98469e0e4901fa9c10c0d277", "583f065c04baadce81f30a925fd4b8feb34c4e67",
    "a3c71fa6302eb7491510c0c14beee998156a5e1a", "1569fb96e023ac8dbc4100d3c461c705d9374af8",
    "8818d32e28515d0e279d4ab3af26dbac8217656c", "7f4baa53826697542afddcb49620a1922798cae2",
    "0c3b34a710b0a4e0074d048fd2642fc834e88c27", "40855794f479bd67b45f7daa9707657c77423590",
    "174a385464701da5e6bf93d1631bd1a02a8ddcde2c369b88ab4e05c1ec155f78",
    "981919f5f753db298c256217f87cfba3f5e91e19ada070cc2ac01d2882ed7ed9",
    "fa179ebcdcf124ff4fd805cca68b15491ddbc179c69bc20421ddcf83c005c182",
    "66f2c2f2076086146a8cbd9053bbd662a1881485da4f9dfc514aab6403d2df52",
    "d6da43dbf313e130dde3f4df08ceef5795128efd341823a9ba07221af602748b",
    "algua-research", "algua-leap", "algua-forage", "algua-paper", "algua-mergeback-drain",
)
OBSERVED_CLAIMS = (
    *(rf"\b{field}\W+{value}\b" for field, value in (
        ("required_status_checks", "null"), ("require_code_owner_reviews", "true"),
        ("required_approving_review_count", "0"), ("enforce_admins", "false"),
        ("dismiss_stale_reviews", "false"), ("require_last_push_approval", "false"))),
    r"inactiv\w*[^.]*\bnot\b[^.]*health acceptance",
    r"separate[^.]*its-nix/os|its-nix/os[^.]*separate", TARGET_BLOCKED,
)
READINESS_CLAIMS = (r"\btask 4\b", r"\btask 7\b", TARGET_BLOCKED, OWNER_APPROVAL,
                    r"independent[^.]*review[^.]*(?:downstream|qa)", "strategy-board/v1",
                    "entry-point inventory", Path(DESIGN).name, Path(PLAN).name,
                    Path(OBSERVED).name)
SUPERSESSION = ("supersed", r"\bleaderboard\b", r"lifecycle[- ]order", "spec-strategy-board",
                r"\bexploratory\b", r"\b(?:no|not|never|without)\b[^.]*\bpromotion\b")


def normalize(text: str) -> str:
    return re.sub(r"\s+", " ", re.sub(r"[*`]", "", text)).strip().lower()


def blocks(text: str) -> list[str]:
    """Normalized paragraphs, list items, table rows and headings; wrapped lines rejoin."""
    found: list[list[str]] = [[]]
    for line in text.splitlines():
        if not line.strip() or re.match(r"^\s*(?:#{1,6}\s|[-*]\s|\d+\.\s|\|)", line):
            found.append([])
        if line.strip():
            found[-1].append(line)
    return [normalize(" ".join(lines)) for lines in found if lines]


def prd_sections(text: str) -> dict[int, tuple[str, str]]:
    """`# N. Title` sections, ignoring look-alike lines inside fenced code."""
    sections: dict[int, tuple[str, list[str]]] = {}
    body: list[str] = []
    fenced = False
    for line in text.splitlines():
        fenced ^= line.startswith("```")
        heading = None if fenced else re.match(r"^# (\d+)\. (.+)$", line)
        if heading:
            body = []
            sections[int(heading[1])] = (heading[2].strip(), body)
        else:
            body.append(line)
    return {number: (title, "\n".join(lines)) for number, (title, lines) in sections.items()}


def read(root: Path, relative: str) -> str:
    path = root / relative
    return path.read_text(encoding="utf-8") if path.is_file() else ""


def lacking(text: str, terms: tuple[str, ...]) -> list[str]:
    return [term for term in terms if not re.search(term, text)]


def block_with_all(text: str, terms: tuple[str, ...]) -> bool:
    return any(not lacking(block, terms) for block in blocks(text))


def merge_violations(block: str) -> list[str]:
    found = []
    if re.search(MERGE_STEP, block) and not re.search(OWNER_APPROVAL, block):
        found.append(f"ungated merge/deploy step: {block}")
    if re.search(AUTOMATION, block) and not re.search(TARGET_BLOCKED, block):
        found.append(f"automation not TARGET BLOCKED: {block}")
    if re.search(r"standing approval[^.]*\b(?:merg|deploy)", block):
        found.append(f"standing approval stretched: {block}")
    for sentence in re.split(r"(?<=[.;])\s", block):
        grant = re.search(UNGATED_GRANT, sentence)
        if grant and not re.search(NEGATED, sentence[: grant.start()]):
            found.append(f"grant without owner: {sentence}")
    return found


def unknown_violations(text: str) -> list[str]:
    found = []
    for target in (TEN_CYCLES, HUNDRED_ATTEMPTS):
        matching = [block for block in blocks(text) if re.search(target, block)]
        found += [] if matching else [f"not reported: {target}"]
        found += [
            f"must read UNKNOWN: {block}" for block in matching
            if "unknown" not in block or re.search(r"(?<!not )\b(?:achieved|passed)\b", block)
        ]
    return found


def check_prd(root: Path) -> list[str]:
    sections = prd_sections(read(root, PRD))
    found = [f"unexpected section {n}" for n in sections.keys() - PRD_SECTIONS.keys()]
    for number, (title, retained, concepts) in PRD_SECTIONS.items():
        heading, raw = sections.get(number, ("", ""))
        body = normalize(raw)
        found += [] if heading == title else [f"section {number} missing or renamed"]
        found += [f"§{number} lost: {term}" for term in retained if term not in body]
        found += [f"§{number} lacks: {term}" for term in lacking(body, concepts)]
        if not concepts and re.search(r"\b(?:hermes|opencode|kanban|leaderboard)\b", body):
            found.append(f"§{number} is outside the requested amendment set")
    return found


def check_guides(root: Path) -> list[str]:
    found = []
    for guide in GUIDES:
        text = read(root, guide)
        found += [f"{guide}: no {name} statement" for name, terms in AUTHORITY_STATEMENTS
                  if not block_with_all(text, terms)]
        for block in blocks(text):
            found += [f"{guide}: {violation}" for violation in merge_violations(block)]
            if "todoist" in block and (re.search(TODOIST_QUEUE, block)
                                       or not re.search(r"\b(?:human|lior|owner)\b", block)):
                found.append(f"{guide}: Todoist not human-only: {block}")
            found += [f"{guide} loosens live: {block}" for grant in re.finditer(LIVE_GRANT, block)
                      if not re.search(NEGATED, grant[0])]
    return found


def check_binding(root: Path) -> list[str]:
    return [f"{relative} lost: {phrase}" for relative, phrases in BINDING.items()
            for phrase in phrases if phrase not in normalize(read(root, relative))]


def check_published(root: Path) -> list[str]:
    found = []
    for relative, marks in LANDMARKS.items():
        text = read(root, relative)
        whole = normalize(text)
        head = normalize("\n".join(text.splitlines()[:40]))
        found += [f"{relative} incomplete: {mark}" for mark in marks if mark not in whole]
        found += [f"{relative} provenance lacks: {term}" for term in lacking(head, PROVENANCE)]
        found += [f"{relative} claims controls"] if re.search(CLAIMED_CONTROLS, whole) else []
    return found


def check_reports(root: Path) -> list[str]:
    observed, readiness = read(root, OBSERVED), read(root, READINESS)
    observed_text, readiness_text = normalize(observed), normalize(readiness)
    return [*(f"observed lacks: {fact}" for fact in OBSERVED_FACTS if fact not in observed_text),
            *(f"observed lacks: {term}" for term in lacking(observed_text, OBSERVED_CLAIMS)),
            *(f"readiness lacks: {term}" for term in lacking(readiness_text, READINESS_CLAIMS)),
            *unknown_violations(observed), *unknown_violations(readiness)]


def check_supersession(root: Path) -> list[str]:
    return [f"{relative}: no supersession record" for relative in (RECONCILIATION, DECISIONS)
            if not block_with_all(read(root, relative), SUPERSESSION)]


GUARDS: dict[str, Callable[[Path], list[str]]] = {
    "prd": check_prd, "guides": check_guides, "binding": check_binding,
    "published": check_published, "reports": check_reports, "supersession": check_supersession,
}


class Mutation(NamedTuple):
    name: str
    guard: str
    relative: str
    pattern: str
    replacement: str


MUTATIONS = (
    Mutation("section_renumbered", "prd", PRD, r"(?m)^# 27\. ", "## 27. "),
    Mutation("drawdown_doubled", "prd", PRD,
             "10% drawdown of the live", "20% drawdown of the live"),
    Mutation("universe_lost", "prd", PRD, r"\$0\.5–10B", "$1–2B"),
    Mutation("outside_scope", "prd", PRD, r"(?m)^# 16\. .*$",
             "# 16. Shadow and paper operation\n\nHermes."),
    Mutation("todoist_queue", "guides", DELIVERY, r"\Z",
             "\n\nTodoist is the shared queue for Lior.\n"),
    Mutation("routing_lost", "guides", "CLAUDE.md", "(?i)hermes kanban", "the backlog"),
    Mutation("merge_step", "guides", DELIVERY, r"\Z", "\n\nFinish with `gh pr merge 1`.\n"),
    Mutation("deploy_step", "guides", DELIVERY, r"\Z", "\n\nDeploy by fast-forwarding main.\n"),
    Mutation("laundered", "guides", "AGENTS.md", r"\Z", "\n\nAgents may merge without Lior.\n"),
    Mutation("automation", "guides", "CLAUDE.md", r"\Z", "\n\nAuto-merge is enabled.\n"),
    Mutation("live_granted", "guides", "AGENTS.md", r"\Z", "\n\nAgents may promote to live.\n"),
    Mutation("wall_inverted", "binding", "CLAUDE.md", r"may \*\*never\*\* put", "may put"),
    Mutation("waivable", "binding", OPERATING, "is not waivable", "is waivable"),
    Mutation("frozen_edited", "binding", BOARD_SPEC, "keep lifecycle order as the default", "rank"),
    Mutation("provenance", "published", DESIGN, r"(?i)not\s+implemented", "implemented"),
    Mutation("plan_cut", "published", PLAN, r"(?m)^### Task 7 — ", "### Skipped — "),
    Mutation("acceptance", "reports", OBSERVED, "(?i)unknown", "achieved"),
    Mutation("protection", "reports", OBSERVED,
             r"`enforce_admins` \| false", "`enforce_admins` | true"),
    Mutation("erased", "supersession", RECONCILIATION, "(?i)supersed", "replac"),
)


@pytest.mark.parametrize("guard", sorted(GUARDS))
def test_repository_docs_satisfy_guard(guard: str) -> None:
    violations = GUARDS[guard](REPO)
    assert violations == [], "\n".join(violations)


@pytest.mark.parametrize("mutation", MUTATIONS, ids=lambda mutation: mutation.name)
def test_guard_catches_mutation_on_a_copy(mutation: Mutation, tmp_path: Path) -> None:
    assert GUARDS[mutation.guard](REPO) == [], "guard must start clean before sabotage"
    for relative in GUARDED:
        (tmp_path / relative).parent.mkdir(parents=True, exist_ok=True)
        shutil.copy2(REPO / relative, tmp_path / relative)
    target = tmp_path / mutation.relative
    text, count = re.subn(
        mutation.pattern, lambda _: mutation.replacement, target.read_text("utf-8")
    )
    assert count, f"anchor absent from {mutation.relative}"
    target.write_text(text, encoding="utf-8")
    assert GUARDS[mutation.guard](tmp_path), f"{mutation.name} went undetected"


@pytest.mark.parametrize(("text", "clean"), [
    ("Run `gh pr merge` only after Lior's explicit approval.", True),
    ("Agents never merge without Lior's approval.", True),
    ("Auto-merge and paper CI/CD are TARGET BLOCKED.", True),
    ("`paper merge-back` runs the gated research cycle.", True),
    ("Merge with `gh pr merge 1 --merge`.", False),
    ("Run `gh pr merge` once green; agents may merge without owner approval.", False),
    ("Lior's standing approval covers merges of routine work.", False),
])
def test_merge_guard_separates_gated_from_ungated_wording(text: str, clean: bool) -> None:
    assert (merge_violations(normalize(text)) == []) is clean


def test_parsers_handle_fences_and_wrapped_blocks() -> None:
    assert list(prd_sections("# 1. A\n\n```text\n# 2. B\n```\n")) == [1]
    assert blocks("- one\n  more\n- two\n\nA\nB.\n") == ["- one more", "- two", "a b."]


def test_acceptance_guard_ignores_story_links_but_rejects_achieved_cycles() -> None:
    text = (
        "10 unattended OpenCode-led research cycles: UNKNOWN.\n\n"
        ">=100 honest real-data attempts: UNKNOWN.\n\n"
        "Task 10 links stories/2-10-run-the-72-hour-unattended-acceptance.md.\n"
    )
    assert unknown_violations(text) == []
    assert unknown_violations(text.replace("UNKNOWN", "achieved", 1))
