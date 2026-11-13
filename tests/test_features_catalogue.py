# tests/test_features_catalogue.py
import importlib
import inspect
import os
import sys
from pathlib import Path

import pytest

import algua.features as _featpkg
from algua.contracts.idea import DataCapability
from algua.features import catalogue as _cat
from algua.features.catalogue import (
    FactorKind,
    FactorNotFound,
    FactorSpec,
    all_factors,
    factor,
    get_factor,
    load_all_factors,
)

pytestmark = pytest.mark.serial  # writes into the real algua/ source tree


@pytest.fixture(autouse=True)
def _clean_registry():
    _cat._reset_registry()
    yield
    _cat._reset_registry()


def _write_feature_module(stem: str, body: str) -> Path:
    path = Path(_featpkg.__path__[0]) / f"{stem}.py"
    path.write_text(body)
    return path


def _drop_module(stem: str, path: Path) -> None:
    path.unlink(missing_ok=True)
    sys.modules.pop(f"algua.features.{stem}", None)


def all_factors_names():
    return {f.name for f in all_factors()}


def test_factor_stamps_spec_and_returns_same_object():
    def raw(x):
        """One-line summary here. More detail ignored."""
        return x

    decorated = factor(kind=FactorKind.MOMENTUM, tags=["a", "b"])(raw)
    assert decorated is raw  # pure annotation, no wrapper
    spec = decorated.__factor_spec__
    assert isinstance(spec, FactorSpec)
    assert spec.name == "raw"
    assert spec.summary == "One-line summary here. More detail ignored."
    assert spec.kind is FactorKind.MOMENTUM
    assert spec.tags == ("a", "b")  # tuple, not list
    assert spec.data_needs == (DataCapability.OHLCV,)  # default
    assert spec.module == "tests.test_features_catalogue"
    assert spec.import_path == "tests.test_features_catalogue:test_factor_stamps_spec_and_returns_same_object.<locals>.raw"  # noqa: E501
    assert spec.signature == str(inspect.signature(raw))
    assert decorated(7) == 7  # behaviour unchanged


def test_explicit_overrides():
    @factor(name="z", summary="explicit", kind=FactorKind.VALUE,
            data_needs=[DataCapability.FUNDAMENTALS])
    def f(a, b):
        return a

    spec = f.__factor_spec__
    assert spec.name == "z"
    assert spec.summary == "explicit"
    assert spec.data_needs == (DataCapability.FUNDAMENTALS,)


def test_missing_summary_and_docstring_fails_closed():
    def nodoc(x):
        return x

    with pytest.raises(ValueError, match="summary"):
        factor()(nodoc)


def test_discovers_decorated_factor_in_a_feature_module():
    path = _write_feature_module(
        "tmp_disc_mod",
        "from algua.features.catalogue import factor, FactorKind\n"
        "@factor(summary='tmp', kind=FactorKind.MOMENTUM, tags=['t'])\n"
        "def tmp_fac(x):\n"
        "    return x\n",
    )
    try:
        reg = load_all_factors()
        assert "tmp_fac" in reg
        assert reg["tmp_fac"].kind is FactorKind.MOMENTUM
    finally:
        _drop_module("tmp_disc_mod", path)


def test_reexport_is_not_double_registered():
    # A module that imports another module's catalogued factor must NOT re-register it.
    defn = _write_feature_module(
        "tmp_defn_mod",
        "from algua.features.catalogue import factor\n"
        "@factor(summary='defined here')\n"
        "def shared_fac(x):\n"
        "    return x\n",
    )
    reexp = _write_feature_module(
        "tmp_reexp_mod",
        "from algua.features.tmp_defn_mod import shared_fac  # re-export\n"
        "from algua.features.catalogue import factor\n"
        "@factor(summary='own')\n"
        "def own_fac(x):\n"
        "    return x\n",
    )
    try:
        reg = load_all_factors()  # must NOT raise duplicate for shared_fac
        assert reg["shared_fac"].module == "algua.features.tmp_defn_mod"
        assert "own_fac" in reg
    finally:
        _drop_module("tmp_reexp_mod", reexp)
        _drop_module("tmp_defn_mod", defn)


def test_duplicate_name_fails_closed():
    a = _write_feature_module(
        "tmp_dup_a",
        "from algua.features.catalogue import factor\n"
        "@factor(summary='a')\n"
        "def clashing(x):\n"
        "    return x\n",
    )
    b = _write_feature_module(
        "tmp_dup_b",
        "from algua.features.catalogue import factor\n"
        "@factor(summary='b')\n"
        "def clashing(x):\n"  # same bare name, different module
        "    return x\n",
    )
    try:
        with pytest.raises(ValueError, match="duplicate factor name"):
            load_all_factors()
    finally:
        _drop_module("tmp_dup_a", a)
        _drop_module("tmp_dup_b", b)


def test_transactional_failed_import_preserves_prior_registry():
    good = _write_feature_module(
        "tmp_good_mod",
        "from algua.features.catalogue import factor\n"
        "@factor(summary='good')\n"
        "def good_fac(x):\n"
        "    return x\n",
    )
    try:
        load_all_factors()  # registry now has good_fac
        bad = _write_feature_module("tmp_bad_mod", "raise RuntimeError('boom')\n")
        try:
            with pytest.raises(RuntimeError, match="boom"):
                load_all_factors()
            # prior registry intact, never half-populated
            assert "good_fac" in all_factors_names()
        finally:
            _drop_module("tmp_bad_mod", bad)
    finally:
        _drop_module("tmp_good_mod", good)


@pytest.mark.parametrize("fails", [False, True], ids=["new-factor", "failing-module"])
def test_discovery_refreshes_modules_with_unchanged_directory_timestamp(
    tmp_path, monkeypatch, fails,
):
    monkeypatch.setattr(_featpkg, "__path__", [str(tmp_path)])
    prior_stem = "tmp_cache_prior"
    new_stem = "tmp_cache_new"
    (tmp_path / f"{prior_stem}.py").write_text(
        "from algua.features.catalogue import factor\n"
        "@factor(summary='prior')\n"
        "def prior_fac(x):\n"
        "    return x\n",
    )
    try:
        prior = load_all_factors()
        assert set(prior) == {"prior_fac"}
        name = f"algua.features.{new_stem}"
        with pytest.raises(ModuleNotFoundError) as missing:
            importlib.import_module(name)
        assert missing.value.name == name

        # FileFinder's negative directory cache stays valid on coarse-timestamp filesystems.
        directory_stat = tmp_path.stat()
        (tmp_path / f"{new_stem}.py").write_text(
            "raise RuntimeError('boom')\n" if fails else
            "from algua.features.catalogue import factor\n"
            "@factor(summary='new')\n"
            "def new_fac(x):\n"
            "    return x\n",
        )
        os.utime(tmp_path, ns=(directory_stat.st_atime_ns, directory_stat.st_mtime_ns))

        if fails:
            with pytest.raises(RuntimeError, match="boom"):
                load_all_factors()
            assert _cat._REGISTRY is prior
            assert all_factors_names() == {"prior_fac"}
        else:
            discovered = load_all_factors()
            assert set(discovered) == {"prior_fac", "new_fac"}
            assert discovered["new_fac"].module == name
    finally:
        for stem in (new_stem, prior_stem):
            sys.modules.pop(f"algua.features.{stem}", None)
            vars(_featpkg).pop(stem, None)
        sys.path_importer_cache.pop(str(tmp_path), None)


def test_get_factor_unknown_raises():
    with pytest.raises(FactorNotFound):
        get_factor("does_not_exist_factor")


def test_seeded_factors_present():
    reg = load_all_factors()
    assert {"momentum", "zscore"} <= set(reg)

    mom = reg["momentum"]
    assert mom.kind is FactorKind.MOMENTUM
    assert "momentum" in mom.tags
    assert mom.import_path == "algua.features.indicators:momentum"
    assert mom.data_needs == (DataCapability.OHLCV,)
