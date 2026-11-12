#!/usr/bin/env bash
#
# THE AGENT-RUNTIME SEAM. The four loop drivers (research, leap, forage, and any future one) call
# this and nothing else; it is the only file in the repo that names the runtime or a model.
#
# Usage:
#   run_agent.sh --mode research|leap|forage|chooser --workdir DIR --prompt-file FILE
#                [--model PROVIDER/MODEL] [--variant high|max|minimal] [--timeout DUR]
#                [--log FILE] [--dry-run]
#
# Exit code is the agent's, except: 124 = timed out (the OS `timeout` convention the drivers
# already read), 2 = usage error, 3 = the runtime is missing or unusable.
#
# WHY A SEAM AT ALL. Under Codex each driver embedded its own `codex exec -s ... -c ...` invocation,
# so the runtime, the sandbox posture and the model choice were smeared across three scripts and a
# user-global config file that no driver passed. Moving to OpenCode with one seam means the next
# runtime change is one file, and `--dry-run` gives the tests a stable contract to assert instead of
# a vendor's flag spelling.
#
# ---------------------------------------------------------------------------------------------
# THREE THINGS THIS SEAM EXISTS TO HANDLE, all measured on opencode 1.18.30 (2026-09-13):
#
# 1. NO KERNEL SANDBOX. Codex's `-s workspace-write` was a real filesystem wall enforced below the
#    agent. OpenCode's permissions are TOOL-LEVEL only: a denied `edit` does not stop `bash` from
#    opening any absolute path, and the loops legitimately need bash for `uv run algua`. So the
#    write wall is re-imposed here with bwrap when it is available (ALGUA_AGENT_SANDBOX=bwrap|none,
#    default auto). This also closes the `/tmp` hole the Codex sandbox spike found.
#
# 2. A PROVIDER ERROR HANGS INSTEAD OF EXITING. A run against an exhausted subscription produced
#    ZERO bytes on stdout and stderr and had to be killed at the timeout. Codex exits immediately.
#    Left alone that turns a quota block into a full-length dead run every firing, so this seam
#    watches the log for a terminal provider error and kills the run early (exit 3), which the
#    drivers' existing rate-limit grep then classifies correctly.
#
# 3. `--pure` DOES NOT DISABLE SKILLS. It disables plugins only; a `--pure` run still loaded 73
#    skills from the user's global directories, with duplicate-name collisions. Hermetic runs need
#    XDG_CONFIG_HOME pointed at the repo AND the two skill-disabling env vars.
# ---------------------------------------------------------------------------------------------
set -uo pipefail

die() { echo "run_agent.sh: $*" >&2; exit 2; }

MODE=""; WORKDIR=""; PROMPT_FILE=""; MODEL=""; VARIANT=""; TIMEOUT="45m"; LOGFILE=""; DRY_RUN=0
while [ $# -gt 0 ]; do
  case "$1" in
    --mode)        MODE="${2:-}"; shift 2 ;;
    --workdir)     WORKDIR="${2:-}"; shift 2 ;;
    --prompt-file) PROMPT_FILE="${2:-}"; shift 2 ;;
    --model)       MODEL="${2:-}"; shift 2 ;;
    --variant)     VARIANT="${2:-}"; shift 2 ;;
    --timeout)     TIMEOUT="${2:-}"; shift 2 ;;
    --log)         LOGFILE="${2:-}"; shift 2 ;;
    --dry-run)     DRY_RUN=1; shift ;;
    *) die "unknown argument: $1" ;;
  esac
done

case "$MODE" in
  research|leap|forage|chooser) ;;
  "") die "--mode is required" ;;
  *)  die "unknown --mode: $MODE (expected research|leap|forage|chooser)" ;;
esac
[ -n "$WORKDIR" ] || die "--workdir is required"
[ -d "$WORKDIR" ] || die "--workdir does not exist: $WORKDIR"
[ -n "$PROMPT_FILE" ] || die "--prompt-file is required"
[ -f "$PROMPT_FILE" ] || die "--prompt-file does not exist: $PROMPT_FILE"

REPO_ROOT="$(cd "$(dirname "${BASH_SOURCE[0]}")/../.." && pwd)"

# Model precedence: --model  >  ALGUA_AGENT_MODEL_<MODE>  >  ALGUA_AGENT_MODEL  >  opencode.json.
# Empty means "let opencode.json decide", which is the normal path: the config file is where model
# choices belong, so a driver never has to know one.
if [ -z "$MODEL" ]; then
  mode_upper="$(printf '%s' "$MODE" | tr '[:lower:]' '[:upper:]')"
  eval "MODEL=\"\${ALGUA_AGENT_MODEL_${mode_upper}:-}\""
  [ -n "$MODEL" ] || MODEL="${ALGUA_AGENT_MODEL:-}"
fi

# HERMETIC CONFIG. The user's global opencode config injects plugins, ~90 skills and a global
# AGENTS.md into every run. A cheap model does not need three `brainstorming` skills competing for
# its attention, and an unattended loop must not change behaviour because a human edited their
# personal config. Legacy loops retain XDG_DATA_HOME for their native login store;
# the output-only chooser routes session writes separately and reads that store in memory.
XDG_DIR="${REPO_ROOT}/.opencode/xdg"
if [ "$MODE" = "chooser" ]; then
  # Disposable caller-owned output directory; never load project or personal agent definitions.
  XDG_DIR="${WORKDIR}/config"
  cd "$WORKDIR" || exit 3
fi
mkdir -p "${XDG_DIR}/opencode"

ENVV=(
  "XDG_CONFIG_HOME=${XDG_DIR}"
  # Usage telemetry writes generated JSON under this source-pinned XDG tree; experiment
  # tracking is separate and remains enabled.
  "MLFLOW_DISABLE_TELEMETRY=true"
  "OPENCODE_DISABLE_EXTERNAL_SKILLS=1"
  "OPENCODE_DISABLE_CLAUDE_CODE_SKILLS=1"
)
if [ "$MODE" = "chooser" ]; then
  ENVV+=("OPENCODE_CONFIG=${REPO_ROOT}/.opencode/opencode.json"
         "OPENCODE_CONFIG_CONTENT={}"
         'OPENCODE_PERMISSION={"*":"deny"}'
         "OPENCODE_DISABLE_AUTOCOMPACT=1"
         "XDG_DATA_HOME=${WORKDIR}/data"
         "XDG_CACHE_HOME=${WORKDIR}/cache" "XDG_STATE_HOME=${WORKDIR}/state")
fi
# Forage is the only loop that may reach the web, and it does so through opencode's search tool.
[ "$MODE" = "forage" ] && ENVV+=("OPENCODE_ENABLE_EXA=1")

CMD=(opencode run --pure --agent "$MODE" --dir "$WORKDIR")
[ -n "$MODEL" ]   && CMD+=(-m "$MODEL")
[ -n "$VARIANT" ] && CMD+=(--variant "$VARIANT")
CMD+=(--print-logs --log-level INFO)
[ "$MODE" = "chooser" ] && CMD+=(--format json --title "Constrained campaign choice")
if [ "$MODE" = "chooser" ]; then
  # Attachments pass through the runtime reader's 2000-char line / 50-KiB page limits. A bounded
  # JSON menu can still lose its identity and evidence there. Deliver the chooser's <=96-KiB
  # prompt literally, below Linux's 128-KiB single-argument limit, without shell evaluation.
  [ "$(wc -c < "$PROMPT_FILE")" -le 98304 ] || die "chooser prompt exceeds 96 KiB argument bound"
  CHOOSER_PROMPT="$(cat "$PROMPT_FILE")" || die "cannot read chooser prompt"
  CMD+=(-- "$CHOOSER_PROMPT")
else
  # Unbounded research/leap/forage prompts keep file delivery to avoid Linux's argument limit.
  # --file is an array flag: the message must precede it or it becomes a second filename.
  CMD+=("Follow the instructions in the attached file." -f "$PROMPT_FILE")
fi

# KERNEL WRITE WALL. Confine writes to the worktree plus the runtime's own state, so a model that
# talks its way past a tool permission still cannot reach the authoritative DB or the real checkout.
SANDBOX="${ALGUA_AGENT_SANDBOX:-auto}"
if [ "$SANDBOX" = "auto" ]; then
  SANDBOX=none
  command -v bwrap >/dev/null 2>&1 && SANDBOX=bwrap
fi
WRAP=()
if [ "$SANDBOX" = "bwrap" ]; then
  # The runtime needs its OWN state writable or it degrades in confusing ways: with
  # ~/.local/state/opencode read-only it logs "background dependency install failed ... EROFS"
  # and carries on half-initialised. Measured in the first live smoke run. These three paths are
  # the runtime's; everything else outside the worktree stays read-only.
  mkdir -p "${HOME}/.local/share/opencode" "${HOME}/.local/state/opencode" "${HOME}/.cache"
  # A fresh PID namespace keeps host-process references out of /proc; a fresh session prevents
  # the agent from inheriting the caller's terminal. Provider networking stays unchanged.
  WRAP=(bwrap --unshare-pid --ro-bind / / --dev /dev --proc /proc --tmpfs /tmp
        --bind "$WORKDIR" "$WORKDIR"
        --bind "${HOME}/.local/share/opencode" "${HOME}/.local/share/opencode"
        --bind "${HOME}/.local/state/opencode" "${HOME}/.local/state/opencode"
        --bind "${HOME}/.cache" "${HOME}/.cache"
        --bind "$XDG_DIR" "$XDG_DIR"
        --new-session --die-with-parent)
  # Agents never call Drive (spec 2026-11-12 §5): hide the owner's refresh token from the agent,
  # which runs model-written code and, for forage, reads untrusted web pages.
  if [ -n "${ALGUA_DRIVE_CREDENTIALS:-}" ] && [ -e "${ALGUA_DRIVE_CREDENTIALS}" ]; then
    WRAP+=(--ro-bind /dev/null "${ALGUA_DRIVE_CREDENTIALS}")
  fi
elif [ "$SANDBOX" != "none" ]; then
  die "unknown ALGUA_AGENT_SANDBOX: $SANDBOX (expected auto|bwrap|none)"
fi

# Strip the Drive backend from the agent's environment: with these unset every ideation CLI call
# the agent makes stays on its snapshot/scratch files and cannot write the owner's Sheets.
FULL=(timeout "$TIMEOUT" env -u ALGUA_DRIVE_FOLDER_ID -u ALGUA_DRIVE_CREDENTIALS "${ENVV[@]}"
      "${WRAP[@]}" "${CMD[@]}")

if [ "$DRY_RUN" = "1" ]; then
  printf 'would run:'
  printf ' %q' "${FULL[@]}"
  printf '\n'
  exit 0
fi

command -v opencode >/dev/null 2>&1 || { echo "run_agent.sh: opencode is not on PATH" >&2; exit 3; }

LOGFILE="${LOGFILE:-${WORKDIR}/agent.log}"
LOGS=("$LOGFILE")
[ "$MODE" = "chooser" ] && LOGS+=("${LOGFILE}.stderr")
if [ "$MODE" = "chooser" ]; then
  # Inspect the actual installed runtime. A missing agent or exposed tool stops BEFORE spending.
  timeout 15s env "${ENVV[@]}" opencode debug agent chooser --pure \
    >"${WORKDIR}/effective-agent.json" 2>"${WORKDIR}/effective-agent.stderr" || exit 3
  "${REPO_ROOT}/.venv/bin/python" - "${WORKDIR}/effective-agent.json" <<'PYCONFIG' || exit 3
import json, sys
agent = json.load(open(sys.argv[1]))
if agent.get("name") != "chooser" or agent.get("mode") != "primary" or agent.get("steps") != 1:
    raise ValueError("output-only agent unavailable")
if not agent.get("tools") or any(v is not False for v in agent["tools"].values()):
    raise ValueError("tool exposed")
if not any(r == {"permission": "*", "pattern": "*", "action": "deny"}
           for r in agent.get("permission", [])):
    raise ValueError("deny-all permission missing")
PYCONFIG
  # Reuse the native login store in memory. Runtime session/cache/refresh writes stay disposable;
  # never put credential contents in argv, printed ENVV, logs or a copied configuration file.
  native_auth="${XDG_DATA_HOME:-${HOME}/.local/share}/opencode/auth.json"
  if [ -z "${OPENCODE_AUTH_CONTENT:-}" ] && [ -f "$native_auth" ]; then
    export OPENCODE_AUTH_CONTENT="$(cat "$native_auth")"
  fi
fi

# Terminal provider failures. These never resolve by waiting, so the watchdog below kills the run
# the moment one appears rather than letting it burn the whole --timeout doing nothing.
FATAL_RE='Monthly usage limit reached|usage limit|quota exceeded|Token refresh failed|AI_RetryError|insufficient_quota|401 Unauthorized|is not supported when using Codex with a ChatGPT account'

# A provider REJECTION the runtime reports without failing. On 2026-10-16 the subscription stopped
# serving the forage model: opencode logged a primary-agent `stream error ... AI_APICallError: Bad
# Request` and still exited 0 within a second -- before the watchdog's first poll, and with rc 0 so
# the rc-gated check below never looked. Forage then ran clean and empty for 3 days and starved the
# idea pool. Anchored to opencode's own ERROR line for the PRIMARY stream (small=false; the title
# agent's small=true errors are not fatal) and to non-retryable 4xx text, so a retried 5xx that
# recovers cannot flip a good run.
REJECT_RE='level=ERROR .*message="stream error" .*small=false .*AI_APICallError: (Bad Request|Unauthorized|Forbidden|Not Found)'

if [ "$MODE" = "chooser" ]; then
  "${FULL[@]}" >"$LOGFILE" 2>"${LOGFILE}.stderr" &
else
  "${FULL[@]}" >"$LOGFILE" 2>&1 &
fi
AGENT_PID=$!

(
  while kill -0 "$AGENT_PID" 2>/dev/null; do
    if grep -qE "$FATAL_RE" "${LOGS[@]}" 2>/dev/null; then
      echo "run_agent.sh: terminal provider error detected; killing the run early" >>"$LOGFILE"
      kill -TERM "$AGENT_PID" 2>/dev/null
      sleep 5
      kill -KILL "$AGENT_PID" 2>/dev/null
      exit 0
    fi
    sleep 10
  done
) &
WATCHDOG_PID=$!

wait "$AGENT_PID"; rc=$?
kill "$WATCHDOG_PID" 2>/dev/null; wait "$WATCHDOG_PID" 2>/dev/null

# A run the watchdog killed is a PROVIDER failure, not a timeout and not a model verdict. Report it
# as 3 so a driver can tell "the provider is down" from "the agent ran and produced nothing".
if [ "$rc" -ne 0 ] && grep -qE "$FATAL_RE" "${LOGS[@]}" 2>/dev/null; then
  rc=3
fi
if [ "$rc" -eq 0 ] && grep -qE "$REJECT_RE" "${LOGS[@]}" 2>/dev/null; then
  echo "run_agent.sh: the provider rejected the primary agent's request but the runtime exited 0; reporting failure" >>"$LOGFILE"
  rc=3
fi
if [ "$MODE" = "chooser" ] && [ "$rc" -eq 0 ]; then
  session_id="$("${REPO_ROOT}/.venv/bin/python" - "$LOGFILE" <<'PYSESSION'
import json, re, sys
rows = [json.loads(line) for line in open(sys.argv[1])]
sessions = {r["sessionID"] for r in rows}
if len(sessions) != 1:
    raise ValueError("missing or mixed chooser sessions")
session = sessions.pop()
if not isinstance(session, str) or not re.fullmatch(r"[A-Za-z0-9_-]{1,200}", session):
    raise ValueError("invalid chooser session")
print(session)
PYSESSION
)" || exit 3
  timeout 15s env "${ENVV[@]}" opencode export --pure --sanitize "$session_id" \
    >"${WORKDIR}/session.json" 2>"${WORKDIR}/session.stderr" || exit 3
fi
cat "$LOGFILE"
exit "$rc"
