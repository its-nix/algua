"""Read-only real-bars exercise for the research-only multimodal context seam.

News and model inputs are deliberately synthetic contract fixtures.  The emitted evidence is a
mechanical interface check, never an alpha, qualification, PIT-universe, or forward-test claim.
"""

from __future__ import annotations

import argparse
import hashlib
import json
import tempfile
from collections.abc import Mapping
from datetime import UTC, datetime, timedelta
from pathlib import Path
from typing import Any

import pandas as pd

from algua.contracts.model_types import ModelRef
from algua.contracts.strategy_context import AsOfContext
from algua.data.files import logical_bars_hash
from algua.data.research_provenance import DataTier, decode_research_provenance
from algua.data.serve import StoreBackedProvider
from algua.data.store import DataStore
from algua.models import register
from algua.research.multimodal_context import build_as_of_context, score_context


class _ExerciseStrategy:
    required_features = frozenset({"bars", "news"})

    def __init__(self, ref: ModelRef) -> None:
        self.required_models: Mapping[str, ModelRef] = {"fixture_model": ref}

    def score(self, context: AsOfContext) -> pd.Series:
        bars = context.features["bars"].frame
        news = context.features["news"].frame
        model = json.loads(context.models["fixture_model"].artifact_bytes)
        close = bars.pivot_table(index=bars.index, columns="symbol", values="adj_close")
        momentum = close.iloc[-1].div(close.iloc[0]).sub(1.0)
        visible_mentions = news.groupby("symbol").size().reindex(momentum.index, fill_value=0)
        fixture_bias = pd.Series(model["bias"], dtype="float64").reindex(
            momentum.index, fill_value=0.0
        )
        return momentum + visible_mentions.astype("float64") * 0.001 + fixture_bias


def _campaign_component(payload: dict[str, Any]) -> dict[str, Any]:
    components = [item for item in payload.get("components", []) if item.get("campaign") is True]
    if len(components) != 1:
        raise ValueError("manifest must contain exactly one campaign=true component")
    return components[0]


def run_exercise(manifest_path: Path, output_path: Path) -> dict[str, Any]:
    data_dir = (manifest_path.parent / "data").resolve()
    resolved_output = output_path.resolve()
    if resolved_output.is_relative_to(data_dir):
        raise ValueError("exercise output must be outside the read-only data store")
    manifest_bytes = manifest_path.read_bytes()
    manifest = json.loads(manifest_bytes)
    component = _campaign_component(manifest)
    declared = component["snapshot"]
    snapshot_id = str(declared["snapshot_id"])
    store = DataStore(data_dir)
    record = store.get_snapshot(snapshot_id)
    if record.content_hash != declared["content_hash"]:
        raise ValueError("manifest content hash does not match the read-only data store")
    if record.metadata.timeframe != "1d":
        raise ValueError("exercise requires a daily bars snapshot")
    provenance = decode_research_provenance(record.metadata.source_metadata)
    if provenance is None or provenance.data_tier is not DataTier.PILOT_REAL_PROXY:
        raise ValueError("exercise requires declared pilot_real_proxy provenance")
    try:
        store.verify_snapshot(record)
    except (OSError, ValueError) as exc:
        raise ValueError(f"snapshot payload verification failed: {exc}") from exc
    all_bars = store.read_bars(snapshot_id)
    actual_hash = logical_bars_hash(
        all_bars.reset_index().rename(columns={"timestamp": "ts"})
    )
    if actual_hash != record.content_hash:
        raise ValueError(
            "snapshot payload verification failed: logical bars hash differs from manifest"
        )

    symbols = tuple(record.symbols[:3])
    if len(symbols) < 2:
        raise ValueError("exercise requires at least two symbols")
    start = datetime.fromisoformat(record.start).replace(tzinfo=UTC)
    end = datetime.fromisoformat(record.end).replace(tzinfo=UTC)
    bars = StoreBackedProvider(store, snapshot_id).get_bars(list(symbols), start, end, "1d")
    if bars.empty:
        raise ValueError("campaign snapshot returned no bars")
    first_decision = pd.Timestamp(bars.index.min()).to_pydatetime()
    decision = pd.Timestamp(bars.index.max()).to_pydatetime()

    news = pd.DataFrame(
        {
            "source": ["synthetic-contract-fixture", "synthetic-contract-fixture"],
            "article_id": ["visible", "future"],
            "symbol": [symbols[0], symbols[1]],
            "published_at": pd.to_datetime(
                [decision - timedelta(days=1), decision + timedelta(days=1)], utc=True
            ),
            "knowable_at": pd.to_datetime(
                [decision - timedelta(hours=1), decision + timedelta(days=1)], utc=True
            ),
            "headline": ["visible fixture", "future fixture must be hidden"],
            "url": [None, None],
            "body": [None, None],
            "retracted": [False, False],
        }
    ).sort_values(["symbol", "source", "article_id", "knowable_at"]).reset_index(drop=True)

    output_path.parent.mkdir(parents=True, exist_ok=True)
    with tempfile.TemporaryDirectory(
        prefix="task2-model-fixture-", dir=output_path.parent
    ) as model_tmp:
        model_root = Path(model_tmp)
        version = register(
            "exercise-fixture-model",
            json.dumps({"bias": {symbol: 0.0 for symbol in symbols}}, sort_keys=True).encode(),
            training_snapshot_id="synthetic-training-fixture",
            training_as_of=(first_decision - timedelta(days=1)).isoformat(),
            code_hash="synthetic-fixture-code",
            hyperparameters={"fixture": {"purpose": "interface-only"}},
            seed=0,
            eval_report={"claims": []},
            root=model_root,
        )
        strategy = _ExerciseStrategy(version.as_ref())
        context = build_as_of_context(
            decision_ts=decision,
            first_decision_ts=first_decision,
            universe=symbols,
            bars=bars,
            bars_snapshot_id=snapshot_id,
            news=news,
            news_snapshot_id="synthetic-news-fixture",
            required_features=strategy.required_features,
            model_refs=strategy.required_models,
            model_registry_root=model_root,
        )
        scores = score_context(strategy, context)
        visible_news = context.features["news"].frame

    evidence: dict[str, Any] = {
        "status": "pass",
        "exercise": "research_only_multimodal_context",
        "claims": {
            "alpha": False,
            "qualification": False,
            "point_in_time_universe": False,
            "elapsed_forward_evidence": False,
        },
        "bars": {
            "fixture": False,
            "snapshot_id": snapshot_id,
            "content_hash": record.content_hash,
            "payload_hash_verified": True,
            "manifest_sha256": hashlib.sha256(manifest_bytes).hexdigest(),
            "provider": record.provider,
            "symbols": list(symbols),
            "row_count": len(bars),
            "decision_session_label": decision.isoformat(),
            "timestamp_semantics": "session label; not observed availability",
            "data_tier": provenance.data_tier.value,
            "universe_method": provenance.universe_method,
            "coverage_start": provenance.coverage_start,
            "coverage_end": provenance.coverage_end,
            "limitations": list(provenance.limitations),
        },
        "news": {
            "fixture": True,
            "input_rows": len(news),
            "visible_rows": len(visible_news),
            "future_known_excluded": "future" not in set(visible_news["article_id"]),
        },
        "model": {
            "fixture": True,
            "name": version.name,
            "version": version.version,
            "digest": version.digest,
            "provenance_digest": version.provenance_digest,
            "training_as_of": version.training_as_of,
        },
        "scores": {
            "count": len(scores),
            "finite": bool(pd.notna(scores).all()),
            "symbols": list(scores.index),
        },
    }
    output_path.write_text(json.dumps(evidence, indent=2, sort_keys=True) + "\n")
    return evidence


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--manifest", required=True, type=Path)
    parser.add_argument("--output", required=True, type=Path)
    args = parser.parse_args()
    evidence = run_exercise(args.manifest, args.output)
    print(json.dumps(evidence, indent=2, sort_keys=True))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())

