# Pure observed-price linear components

These are common numerical components used by the separate [offline proxy producer](model-training.md).
They do not alone establish the offline fit → pin → canonical real-data evaluation flow or its
acceptance evidence. The producer defines its explicitly approved proxy cutoff separately. Neither module
emits `training_as_of`, consults a clock, reads a store, resolves a model or changes trading state.

`algua.features.price_linear.return_features` calculates one- and five-observed-bar adjusted-close
returns. Input is a wide frame with explicit unique nonblank string symbols and a strictly ordered,
unique, UTC-aware event-label index. There is no implicit fill or session/calendar validation.
Features have fixed order `(return_1, return_5)`, event-major/supplied-symbol row order, and explicit
NaN warmup. A next-observation return is a forecast target, not realized strategy PnL or an assertion
of same-bar execution eligibility.

`algua.training.price_linear.fit_price_linear` takes explicit aware `[train_start, train_end)`
event bounds. It clips future rows before constructing returns or next-row targets and before
validating price values. Up to five observations before the start provide causal warmup; older
unused history is excluded. Every retained price must be finite, positive and real-valued.
Validation uses the frame's current logical scalar values: a zero-imaginary complex representation
is accepted through an explicit imaginary-part check and real extraction. Nonzero imaginary
values, booleans, strings and missing values refuse. Original scalar types lost during DataFrame
construction cannot be recovered. This does not change the separate canonical bar contract.

The recipe pools symbols with one shared standard scaler and two shared coefficients. Only eligible
X rows (event at/after start, five-bar warmup defined, next observation strictly before end) fit the
existing standard scaler with population standard deviation. Zero variance fails closed. At least
three pooled observations are required. Float64 ridge solves
`||y - intercept - scaled_X @ coefficients||² + l2 * ||coefficients||²`, with an unpenalized intercept
and explicit finite positive `l2` (default `0.001`). Positive ridge permits correlated nonconstant
features; numerical failures refuse. No seed or stochastic step is involved.

The immutable report partitions interval observations, in order, into warmup, unlabelled, and fitted
counts. The final observed row is unlabelled only if it already has complete warmup. Its maximum
X and y event labels describe observations only: they do not establish historical availability,
an information cutoff, training wall-clock time or point-in-time qualification. The scaler maximum
equals maximum fitted X; maximum target event is later. The report's symbol tuple retains supplied
order. Consumed data is capped at 100,000 event rows, 512 symbols and 2,000,000 cells; these are
numerical materialization limits after the caller has supplied a DataFrame, not I/O limits.

`FrozenPriceLinear` owns detached immutable primitive parameters. Its `scaler` accessor returns a
fresh existing `FrozenScaler`. `predict` accepts only finite real feature values in the exact fixed
feature order and preserves input row order, returning finite float64 predictions without fitting.
The canonical UTF-8 JSON codec is closed at every mapping, capped at 64 KiB on decode, and rejects
duplicate keys, unknown fields, wrong types, nonfinite/overflowed numbers and inconsistent event
labels. It preserves the existing STANDARD scaler shape while validating it more strictly at this
new boundary. Structural validation is not authentication: a different valid finite coefficient
is a different numerical model, not a tamper proof identity. There is no pickle/joblib loading.

Import contracts prevent serving, research, feature, model and authority layers from importing
`algua.training`; training itself can use only the pure contracts/features/primitives leaves.
Focused tests use synthetic mathematical fixtures, not market or cycle acceptance evidence.
