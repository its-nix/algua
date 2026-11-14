import json
import sys

import pytest

from algua.cli.main import main


def test_bad_option_type_renders_json(monkeypatch, capsys):
    monkeypatch.setattr(sys, "argv",
                        ["algua", "backtest", "walk-forward", "x", "--demo", "--windows", "nope"])
    with pytest.raises(SystemExit) as ei:
        main()
    assert ei.value.code == 1
    assert json.loads(capsys.readouterr().out)["ok"] is False


def test_unknown_option_renders_json(monkeypatch, capsys):
    monkeypatch.setattr(sys, "argv", ["algua", "version", "--nope"])
    with pytest.raises(SystemExit) as ei:
        main()
    assert ei.value.code == 1
    assert json.loads(capsys.readouterr().out)["ok"] is False


def test_version_succeeds_via_main(monkeypatch, capsys):
    monkeypatch.setattr(sys, "argv", ["algua", "version"])
    with pytest.raises(SystemExit) as ei:
        main()
    assert ei.value.code == 0
    assert json.loads(capsys.readouterr().out)["name"] == "algua"


def test_command_body_error_exits_via_main(monkeypatch, capsys):
    # json_errors renders the error then raises typer.Exit(1); main() must map it to exit code 1.
    # Typer 0.28 moved Exit out of typer._click.exceptions, which main() used to catch.
    monkeypatch.setattr(sys, "argv", ["algua", "research", "promote", "s", "--universe", "u",
                                      "--start", "2020-01-01", "--end", "2021-01-01",
                                      "--min-holdout-sharpe", "inf"])
    with pytest.raises(SystemExit) as ei:
        main()
    assert ei.value.code == 1
    assert json.loads(capsys.readouterr().out)["ok"] is False


def test_abort_renders_json_via_main(monkeypatch, capsys):
    import typer

    import algua.cli.main as cli_main

    class _Aborting:
        def main(self, **_kwargs):
            raise typer.Abort()

    monkeypatch.setattr(cli_main, "get_command", lambda _app: _Aborting())
    monkeypatch.setattr(sys, "argv", ["algua", "version"])
    with pytest.raises(SystemExit) as ei:
        main()
    assert ei.value.code == 1
    out = json.loads(capsys.readouterr().out)
    assert out["ok"] is False and out["code"] == "aborted"
