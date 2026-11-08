"""Paper-to-experimental-live handoff without tripping the strategy kill switch."""

import typer

from algua.cli.app import emit
from algua.cli.errors import json_errors
from algua.cli.experimental_handoff import handoff
from algua.contracts.lifecycle import Stage
from algua.operator.deployment_lock import operator_transition_lock
from algua.registry.db import registry_conn

handoff_app = typer.Typer(no_args_is_help=True)


@handoff_app.command("handoff")
@json_errors
def paper_handoff(name: str) -> None:
    with operator_transition_lock(Stage.FORWARD_TESTED, Stage.LIVE), registry_conn() as conn:
        emit(handoff(conn, name))
