#!/bin/bash
# Owner-approved isolated paper bootstrap, 2026-11-09. No live command surface.
set -euo pipefail
if [[ $EUID != 0 ]]; then
  printf '%s\n' '{"ok":false,"error":"run this installed helper as root"}'
  exit 1
fi
case "${1-} ${2-} ${3-}" in
  'paper mechanics '*|'risk configure paper'|'risk restore paper'|'risk status '|'registry list '|'version  '|'doctor  ') ;;
  *) printf '%s\n' '{"ok":false,"error":"only isolated paper mechanics and paper policy commands are allowed"}'; exit 1 ;;
esac
release=$(readlink -e /opt/algua/paper-current)
# The selector and release directories are installed root-owned and runtime-unwritable.
[[ $release =~ ^/opt/algua/releases/[0-9a-f]{40}$ ]]
exec systemd-run --quiet --collect --wait --pipe --service-type=exec \
  --uid=algua-paper --gid=algua-paper \
  --property=EnvironmentFile=/etc/algua/paper.env \
  --property=WorkingDirectory=/var/lib/algua-paper \
  --property=UMask=0077 --property=NoNewPrivileges=yes \
  --property=ProtectHome=yes --property=ProtectSystem=strict --property=PrivateTmp=yes \
  --property=RuntimeMaxSec=300 --property=KillMode=control-group \
  --property="ReadWritePaths=/var/lib/algua-paper $release/.git/operator.lock" \
  /usr/bin/env -u ALGUA_ALPACA_LIVE_API_KEY -u ALGUA_ALPACA_LIVE_API_SECRET \
  "PATH=$release/.venv/bin:/usr/bin:/bin" "PYTHONPATH=$release" \
  PYTHONNOUSERSITE=1 PYTHONDONTWRITEBYTECODE=1 HOME=/var/lib/algua-paper \
  ALGUA_DB_PATH=/var/lib/algua-paper/risk.db ALGUA_DATA_DIR=/var/lib/algua-paper/data \
  ALGUA_KNOWLEDGE_DIR=/var/lib/algua-paper/kb \
  ALGUA_MLFLOW_TRACKING_URI=/var/lib/algua-paper/mlruns \
  ALGUA_ALPACA_PAPER_URL=https://paper-api.alpaca.markets \
  ALGUA_ALPACA_DATA_URL=https://data.alpaca.markets/v2 \
  MLFLOW_DISABLE_TELEMETRY=true OMP_NUM_THREADS=1 OPENBLAS_NUM_THREADS=1 NUMBA_NUM_THREADS=1 \
  XDG_CACHE_HOME=/var/lib/algua-paper/cache NUMBA_CACHE_DIR=/var/lib/algua-paper/cache/numba \
  MPLCONFIGDIR=/var/lib/algua-paper/cache/matplotlib TMPDIR=/tmp \
  GIT_CONFIG_NOSYSTEM=1 GIT_CONFIG_GLOBAL=/dev/null GIT_OPTIONAL_LOCKS=0 \
  GIT_CONFIG_COUNT=3 GIT_CONFIG_KEY_0=safe.directory "GIT_CONFIG_VALUE_0=$release" \
  GIT_CONFIG_KEY_1=core.hooksPath GIT_CONFIG_VALUE_1=/dev/null \
  GIT_CONFIG_KEY_2=core.fsmonitor GIT_CONFIG_VALUE_2=false \
  "$release/.venv/bin/python" -c 'from algua.cli.main import main; main()' "$@"
