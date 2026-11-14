"""algua-monitor: FastAPI backend over the algua CLI seam (slices B+C+D + dashboard Inbox).

Read-only except the owner's Inbox (`POST /api/inbox`, `POST /share`): every write passes
backend.owner.require_owner (the `Tailscale-User-Login` header) and goes through the CLI's
`research inbox add`, the Inbox's only writer.

Same-origin by design: no CORS middleware (dev uses the Vite proxy). Production listens on a
Unix socket only tailscaled can open (web/README.md) — never 0.0.0.0.

Every user-controlled value that reaches the CLI is validated in backend.params
and passed in ``--flag=value`` form (a single argv element), so a crafted value
can never be parsed as a separate flag.

Slice D adds a background cache-prewarm poller (backend.poller, wired via the
lifespan) and static serving of the built frontend (backend.static) — active
only when a frontend build exists at the DIST dir; otherwise the app runs
api-only. ``create_app()`` is the factory (tests build isolated instances);
``app`` is the module-level instance uvicorn targets.
"""

from __future__ import annotations

import asyncio
import contextlib
import json
import logging
from collections.abc import AsyncIterator
from contextlib import asynccontextmanager
from typing import Annotated, Any

from fastapi import FastAPI, Query, Request
from fastapi import Path as ApiPath
from fastapi.exceptions import RequestValidationError
from fastapi.responses import JSONResponse, RedirectResponse
from starlette.datastructures import UploadFile

from backend import inbox, push
from backend.algua_cli import CliError, forget, run_cli
from backend.extract import extract_pdf_text, fetch_article
from backend.owner import Forbidden, refuse_cross_site, require_owner
from backend.params import (
    InvalidParam,
    validate_action,
    validate_actor,
    validate_family,
    validate_lane,
    validate_research_cycle,
    validate_run_ids,
    validate_run_kind,
    validate_since,
    validate_sort,
    validate_strategy_name,
)
from backend.poller import poll_loop
from backend.static import dist_dir, install_static
from backend.triage import build_triage

logger = logging.getLogger(__name__)

# `research idea stats` default --window-days (algua/cli/idea_cmd.py); the UI must
# label the window the stats cover.
IDEA_STATS_WINDOW_DAYS = 90

# A real PushSubscription JSON is well under 1 KiB; anything over 16 KiB is abuse.
MAX_SUBSCRIBE_BODY_BYTES = 16 * 1024

# `registry gates` returns the newest N rows PER LEDGER (its own default is 20). Passed
# explicitly and echoed back as ``gates_limit`` so the UI can say "newest N" instead of
# presenting a truncated ledger as the complete history.
GATE_HISTORY_LIMIT = 50


@asynccontextmanager
async def _lifespan(app: FastAPI) -> AsyncIterator[None]:
    # Background prewarm poller (slice D): started on startup, cancelled on shutdown.
    poll_task = asyncio.create_task(poll_loop())
    try:
        yield
    finally:
        poll_task.cancel()
        with contextlib.suppress(asyncio.CancelledError):
            await poll_task


def create_app() -> FastAPI:
    app = FastAPI(title="algua-monitor", lifespan=_lifespan)

    @app.exception_handler(CliError)
    async def cli_error_handler(request: Request, exc: CliError) -> JSONResponse:
        return JSONResponse(
            status_code=502,
            content={"ok": False, "error": exc.error, "code": exc.code},
        )

    @app.exception_handler(InvalidParam)
    async def invalid_param_handler(request: Request, exc: InvalidParam) -> JSONResponse:
        return JSONResponse(
            status_code=422,
            content={"ok": False, "error": exc.error, "code": "invalid_param"},
        )

    @app.exception_handler(Forbidden)
    async def forbidden_handler(request: Request, exc: Forbidden) -> JSONResponse:
        return JSONResponse(
            status_code=403,
            content={"ok": False, "error": str(exc), "code": "forbidden"},
        )

    @app.exception_handler(inbox.TooLarge)
    async def too_large_handler(request: Request, exc: inbox.TooLarge) -> JSONResponse:
        return JSONResponse(
            status_code=413,
            content={"ok": False, "error": str(exc), "code": "too_large"},
        )

    @app.exception_handler(push.SubscriptionLimit)
    async def subscription_limit_handler(
        request: Request, exc: push.SubscriptionLimit
    ) -> JSONResponse:
        return JSONResponse(
            status_code=422,
            content={"ok": False, "error": str(exc), "code": "subscription_limit"},
        )

    @app.exception_handler(RequestValidationError)
    async def request_validation_handler(
        request: Request, exc: RequestValidationError
    ) -> JSONResponse:
        # Same envelope as InvalidParam so a bad ?limit= renders like every other 422.
        detail = "; ".join(
            f"{'.'.join(str(loc) for loc in err.get('loc', ()))}: {err.get('msg', 'invalid')}"
            for err in exc.errors()
        )
        return JSONResponse(
            status_code=422,
            content={"ok": False, "error": detail, "code": "invalid_param"},
        )

    @app.get("/api/fleet")
    async def fleet() -> dict[str, Any]:
        # 10s success TTL: global_halt must not lag behind the fleet view.
        return await run_cli("fleet", "health", ttl_s=10.0)

    @app.get("/api/ops")
    async def ops() -> dict[str, Any]:
        # 30s: loop liveness moves on a timer cadence (30-60 min), not tick-by-tick.
        return await run_cli("ops", "status", ttl_s=30.0)

    @app.get("/api/book")
    async def book() -> dict[str, Any]:
        # 30s: allocations change only on an intake/allocate/revoke, which are rare and human-paced.
        return await run_cli("book", "status", ttl_s=30.0)

    @app.get("/api/triage")
    async def triage() -> dict[str, Any]:
        """The Now screen: one ranked "needs you" list across fleet + loops + capital.

        Each part degrades independently — a failed part contributes nothing and is reported in
        ``sources`` rather than blanking the screen or, worse, rendering a false all-clear.
        """
        fleet_r, ops_r, book_r = await asyncio.gather(
            run_cli("fleet", "health", ttl_s=10.0),
            run_cli("ops", "status", ttl_s=30.0),
            run_cli("book", "status", ttl_s=30.0),
            return_exceptions=True,
        )
        parts: dict[str, Any] = {}
        fetched_ats: list[str] = []
        stale = False
        for name, result in (("fleet", fleet_r), ("ops", ops_r), ("book", book_r)):
            if isinstance(result, CliError):
                parts[name] = None
            elif isinstance(result, BaseException):
                raise result
            else:
                parts[name] = result["data"]
                fetched_ats.append(result["fetched_at"])
                stale = stale or bool(result["stale"])
        if not fetched_ats:
            # Every part failed: there is nothing to triage FROM, and rendering an empty
            # "all clear" would be a lie. Fail loudly instead.
            raise CliError("triage_unavailable", "no triage source could be read")
        return {
            "ok": True,
            **build_triage(parts["fleet"], parts["ops"], parts["book"]),
            "fetched_at": min(fetched_ats),
            "stale": stale,
        }

    @app.get("/api/strategies")
    async def strategies() -> dict[str, Any]:
        # `registry list` emits a bare array; the seam wraps it as {"data": [...]} — pass through.
        return await run_cli("registry", "list", ttl_s=60.0)

    @app.get("/api/strategy/{name}")
    async def strategy_detail(name: str) -> Any:
        """Composed per-strategy drill-down: registry show + paper show + registry gates.

        registry show is authoritative: not_found -> 404, any other CliError -> 502.
        paper/gates degrade per-part: a CliError nulls that part and surfaces its code
        in ``part_errors`` (paper show returns an idle rollup for idea-stage strategies,
        so a null part is a REAL failure, render-worthy).
        """
        validate_strategy_name(name)
        registry, paper, gates = await asyncio.gather(
            run_cli("registry", "show", name, ttl_s=30.0),
            run_cli("paper", "show", name, ttl_s=30.0),
            run_cli("registry", "gates", name, f"--limit={GATE_HISTORY_LIMIT}", ttl_s=30.0),
            return_exceptions=True,
        )
        if isinstance(registry, BaseException):
            if isinstance(registry, CliError) and registry.code == "not_found":
                return JSONResponse(
                    status_code=404,
                    content={"ok": False, "error": registry.error, "code": "not_found"},
                )
            raise registry
        parts: dict[str, Any] = {}
        part_errors: dict[str, str] = {}
        fetched_ats = [registry["fetched_at"]]
        stale = bool(registry["stale"])
        for part, result in (("paper", paper), ("gates", gates)):
            if isinstance(result, CliError):
                parts[part] = None
                part_errors[part] = result.code
            elif isinstance(result, BaseException):
                raise result
            else:
                parts[part] = result["data"]
                fetched_ats.append(result["fetched_at"])
                stale = stale or bool(result["stale"])
        body: dict[str, Any] = {
            "ok": True,
            "strategy": name,
            "registry": registry["data"],
            "paper": parts["paper"],
            "gates": parts["gates"],
            "gates_limit": GATE_HISTORY_LIMIT,
            "fetched_at": min(fetched_ats),
            "stale": stale,
        }
        if part_errors:
            body["part_errors"] = part_errors
        return body

    @app.get("/api/strategy/{name}/series")
    async def strategy_series(
        name: str,
        since: str | None = None,
        lane: str | None = None,
    ) -> dict[str, Any]:
        # No-lane default returns BOTH lanes grouped (slice-A CLI contract) — pass
        # through verbatim.
        validate_strategy_name(name)
        args = ["fleet", "series", name]
        if since is not None:
            args.append(f"--since={validate_since(since)}")
        if lane is not None:
            args.append(f"--lane={validate_lane(lane)}")
        return await run_cli(*args, ttl_s=60.0)

    @app.get("/api/activity")
    async def activity(
        strategy: str | None = None,
        actor: str | None = None,
        action: str | None = None,
        limit: Annotated[int, Query(ge=1, le=500)] = 100,
    ) -> dict[str, Any]:
        args = ["audit", "log", f"--limit={limit}"]
        if strategy is not None:
            args.append(f"--strategy={validate_strategy_name(strategy)}")
        if actor is not None:
            args.append(f"--actor={validate_actor(actor)}")
        if action is not None:
            args.append(f"--action={validate_action(action)}")
        return await run_cli(*args, ttl_s=30.0)

    @app.get("/api/ideas")
    async def ideas() -> dict[str, Any]:
        idea_list, idea_stats, idea_depth, idea_scorecard = await asyncio.gather(
            run_cli("research", "idea", "list", ttl_s=300.0),
            run_cli("research", "idea", "stats", ttl_s=300.0),
            run_cli("research", "idea", "depth", ttl_s=300.0),
            run_cli("research", "idea", "scorecard", "--days", "90", ttl_s=300.0),
        )
        parts = (idea_list, idea_stats, idea_depth, idea_scorecard)
        return {
            "ok": True,
            "ideas": idea_list["data"],
            "stats": idea_stats["data"],
            "stats_window_days": IDEA_STATS_WINDOW_DAYS,
            "depth": idea_depth["data"],
            "scorecard": idea_scorecard["data"],
            "fetched_at": min(part["fetched_at"] for part in parts),
            "stale": any(bool(part["stale"]) for part in parts),
        }

    @app.get("/api/runs")
    async def runs_list(
        kind: str | None = None,
        strategy: str | None = None,
        family: str | None = None,
        sort: str | None = None,
        limit: Annotated[int, Query(ge=1, le=500)] = 100,
    ) -> dict[str, Any]:
        # `kind` is checked against RUN_KINDS; `family`/`sort` get a syntactic shape guard only —
        # `sort`'s semantic vocabulary (METRIC_COLUMNS) stays the store's allow-list
        # (algua/registry/store/runs.py), same as the CLI's own caller (see params.py docstring).
        args = ["runs", "list", f"--limit={limit}"]
        if kind is not None:
            args.append(f"--kind={validate_run_kind(kind)}")
        if strategy is not None:
            args.append(f"--strategy={validate_strategy_name(strategy)}")
        if family is not None:
            args.append(f"--family={validate_family(family)}")
        if sort is not None:
            args.append(f"--sort={validate_sort(sort)}")
        return await run_cli(*args, ttl_s=60.0)

    @app.get("/api/research-memory")
    async def retained_research(
        limit: Annotated[int, Query(ge=1, le=100)] = 20,
    ) -> dict[str, Any]:
        return await run_cli("research", "memory", "list", f"--limit={limit}", ttl_s=30.0)

    @app.get("/api/research-memory/{cycle_id}")
    async def retained_research_detail(cycle_id: str) -> dict[str, Any]:
        return await run_cli("research", "memory", "show",
                             f"--run={validate_research_cycle(cycle_id)}", ttl_s=30.0)

    @app.get("/api/strategy-board")
    async def strategy_board(
        include_evidence: bool = False, research: bool = False,
    ) -> dict[str, Any]:
        # The typed boolean maps only to one fixed argv token; no query value reaches the CLI.
        args = ["runs", "board"]
        if include_evidence:
            args.append("--include-evidence")
        if research:
            args.append("--research")
        return await run_cli(*args, ttl_s=60.0)

    @app.get("/api/strategy/{strategy_id}/research")
    async def strategy_research(
        strategy_id: Annotated[int, ApiPath(ge=1)],
        run_id: Annotated[int | None, Query(ge=1)] = None,
    ) -> dict[str, Any]:
        args = ["runs", "research", str(strategy_id)]
        if run_id is not None:
            args.append(f"--run-id={run_id}")
        return await run_cli(*args, ttl_s=30.0)

    @app.get("/api/runs/series")
    async def runs_series(ids: str) -> dict[str, Any]:
        """Registered BEFORE `/api/runs/{run_id}` so the literal path segment "series" is never
        swallowed by that route's `{run_id}` matcher.

        `ids` (comma-separated run ids) is validated and capped BEFORE shelling out — see
        `validate_run_ids`.
        """
        unique_ids = validate_run_ids(ids)
        args = ["runs", "series", str(unique_ids[0])]
        args.extend(f"--run-id={run_id}" for run_id in unique_ids[1:])
        return await run_cli(*args, ttl_s=60.0)

    @app.get("/api/runs/{run_id}")
    async def run_detail(run_id: int) -> dict[str, Any]:
        return await run_cli("runs", "show", str(run_id), ttl_s=30.0)

    @app.get("/api/push/key")
    async def push_key() -> dict[str, Any]:
        # First call generates + persists the VAPID keypair (disk + EC keygen) -> thread.
        return {"ok": True, "key": await asyncio.to_thread(push.vapid_public_key)}

    @app.post("/api/push/subscribe")
    async def push_subscribe(request: Request) -> dict[str, Any]:
        # Body cap BEFORE parsing: the Content-Length header is the cheap first
        # line; the incremental stream read is the real cap for chunked/lying
        # clients — it aborts as soon as the accumulated bytes exceed the limit,
        # never buffering an unbounded body.
        content_length = request.headers.get("content-length")
        if content_length is not None:
            try:
                declared = int(content_length)
            except ValueError:
                declared = None  # malformed header -> rely on the stream cap
            if declared is not None and declared > MAX_SUBSCRIBE_BODY_BYTES:
                raise InvalidParam("body too large")
        chunks: list[bytes] = []
        received = 0
        async for chunk in request.stream():
            received += len(chunk)
            if received > MAX_SUBSCRIBE_BODY_BYTES:
                raise InvalidParam("body too large")
            chunks.append(chunk)
        body = b"".join(chunks)
        try:
            sub = json.loads(body)
        except (json.JSONDecodeError, UnicodeDecodeError):
            raise InvalidParam("body must be valid JSON") from None
        # add_subscription re-validates shape/size/limit (R12): InvalidParam -> 422
        # invalid_param, SubscriptionLimit -> 422 subscription_limit.
        await asyncio.to_thread(push.add_subscription, sub)
        return {"ok": True}

    @app.delete("/api/push/subscribe")
    async def push_unsubscribe(endpoint: str) -> dict[str, Any]:
        # Idempotent: removing an unknown endpoint is still {ok: true}.
        await asyncio.to_thread(push.remove_subscription, endpoint)
        return {"ok": True}

    @app.get("/api/equity")
    async def equity(lane: str | None = None) -> dict[str, Any]:
        # Cached like /api/book: the curve moves once per session.
        args = ["fleet", "equity"]
        if lane is not None:
            args.append(f"--lane={validate_lane(lane)}")
        return await run_cli(*args, ttl_s=30.0)

    @app.get("/api/inbox")
    async def inbox_list(
        limit: Annotated[int | None, Query(ge=1, le=500)] = None,
    ) -> dict[str, Any]:
        # No cache: the owner expects to see their item the moment it is added.
        args = ["research", "inbox", "list"]
        if limit is not None:
            args.append(f"--limit={limit}")
        return await run_cli(*args, ttl_s=0.0)

    @app.post("/api/inbox")
    async def inbox_add(request: Request) -> JSONResponse:
        # Owner first, before a single body byte is read or spooled.
        require_owner(request)
        refuse_cross_site(request)
        if request.headers.get("content-type", "").startswith("multipart/form-data"):
            form = await inbox.read_form(request, max_files=1)
            try:
                files = inbox.form_files(form, "file")
                if not files:
                    raise InvalidParam("multipart body needs a file")
                data = await _add_file(
                    files[0], title=inbox.check_title(inbox.form_str(form, "title")),
                    note=inbox.check_note(inbox.form_str(form, "note")))
            finally:
                await form.close()
        else:
            # JSON only: a cross-site <form enctype="text/plain"> can forge a JSON-shaped body
            # without a preflight, so anything not declared application/json is refused.
            if not request.headers.get("content-type", "").startswith("application/json"):
                raise InvalidParam("body must be application/json or multipart/form-data")
            body = await inbox.read_json(request)
            if not isinstance(body, dict):
                raise InvalidParam("body must be a JSON object")
            url = inbox.check_url(body.get("url"))
            text = inbox.check_body_text(body.get("text"))
            title = inbox.check_title(body.get("title"))
            note = inbox.check_note(body.get("note"))
            if (url is None) == (text is None):
                raise InvalidParam("give exactly one of url or text")
            if url is not None:
                data = await _add_link(url, title=title, note=note)
            else:
                data = await _cli_add([f"--text={text}",
                                       *inbox.optional_args(title=title, note=note)])
        return JSONResponse(status_code=201, content=data)

    @app.post("/share")
    async def share_target(request: Request) -> RedirectResponse:
        # The PWA's Web Share Target (Android: Share -> Algua). Owner first, as for every write.
        require_owner(request)
        form = await inbox.read_form(request, max_files=inbox.MAX_SHARE_FILES)
        try:
            title = inbox.check_title(inbox.form_str(form, "title"))
            text = inbox.check_body_text(inbox.form_str(form, "text"))
            url = inbox.check_url(inbox.form_str(form, "url") or inbox.url_in_text(text))
            files = inbox.form_files(form, "files")
            # Shared text may be a long selection: keep its head as the note, never fail the share.
            note = inbox.check_note(text[:inbox.MAX_NOTE_CHARS]) if text and text != url else None
            if files:
                for upload in files:
                    await _add_file(upload, title=title, note=note)
            elif url is not None:
                await _add_link(url, title=title, note=note)
            elif text is not None:
                await _cli_add([f"--text={text}", *inbox.optional_args(title=title, note=None)])
            else:
                raise InvalidParam("nothing was shared")
        finally:
            await form.close()
        return RedirectResponse("/inbox?shared=1", status_code=303)

    @app.get("/healthz")
    async def healthz() -> dict[str, Any]:
        return {"ok": True}

    # Static serving LAST: the SPA catch-all matches everything, so every API route
    # above must already be registered. Active only when a frontend build exists.
    dist = dist_dir()
    if (dist / "index.html").is_file():
        logger.info("static mode: serving frontend build from %s", dist)
        install_static(app, dist)
    else:
        logger.info("api-only mode: no frontend build at %s (run `npm run build`)", dist)

    return app


async def _cli_add(source_args: list[str]) -> dict[str, Any]:
    """Run `research inbox add` once, uncached; returns ``{"ok", "item", "duplicate"}``.

    run_cli stale-serves a cached value when the CLI fails; for a write that would be a fake
    success, so a stale result is the failure it stands for."""
    args = ("research", "inbox", "add", *source_args)
    try:
        result = await run_cli(*args, ttl_s=0.0)
    finally:
        forget(*args)
    if result.get("stale"):
        raise CliError(str(result.get("last_error_code") or "cli_error"), "inbox add failed")
    data = result["data"]
    return {"ok": True, "item": data.get("item"), "duplicate": bool(data.get("duplicate"))}


async def _add_link(url: str, *, title: str | None, note: str | None) -> dict[str, Any]:
    fetched_title, text = await fetch_article(url)
    with inbox.extracted_text_arg(text) as extracted:
        return await _cli_add([f"--url={url}", *extracted,
                               *inbox.optional_args(title=title or fetched_title, note=note)])


async def _add_file(upload: UploadFile, *, title: str | None, note: str | None) -> dict[str, Any]:
    path = await inbox.save_upload(upload)
    try:
        if await asyncio.to_thread(inbox.is_pdf, path, upload.content_type):
            text = await asyncio.to_thread(extract_pdf_text, path)
        elif inbox.is_text_file(path, upload.content_type):
            text = await asyncio.to_thread(inbox.read_text_file, path)
        else:
            text = None
        with inbox.extracted_text_arg(text) as extracted:
            return await _cli_add([
                f"--file={path}", *extracted,
                *inbox.optional_args(title=title or inbox.sanitize_name(upload.filename),
                                     note=note)])
    except BaseException:
        inbox.discard_upload(path)
        raise


app = create_app()


if __name__ == "__main__":
    import uvicorn

    uvicorn.run(app, host="127.0.0.1", port=8787)
