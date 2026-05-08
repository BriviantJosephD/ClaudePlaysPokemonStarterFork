#!/usr/bin/env bash
# Serve the stream-of-thought OBS overlay over HTTP.
#
# The overlay (thoughts.html) fetches thoughts.log via a relative URL, so the
# server's working directory MUST be the repo root. This script changes into
# the repo root regardless of where it is invoked from.
#
# Reads THOUGHTS_HTML_PORT from config.py if available; falls back to 7861.
#
# Usage:   ./scripts/serve_overlay.sh
# OBS:     add a Browser Source pointing to http://localhost:<port>/thoughts.html

set -euo pipefail

# Resolve repo root as the parent of this script's directory, regardless of cwd.
SCRIPT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
REPO_ROOT="$(cd "${SCRIPT_DIR}/.." && pwd)"
cd "${REPO_ROOT}"

# Pull THOUGHTS_HTML_PORT from config.py via Python so this stays in sync if
# the constant changes. Fall back to 7861 if config.py cannot be imported
# (e.g. someone runs this before installing deps).
PORT="$(python3 -c "import config; print(config.THOUGHTS_HTML_PORT)" 2>/dev/null || echo 7861)"

if [ ! -f "thoughts.html" ]; then
  echo "ERROR: thoughts.html not found in ${REPO_ROOT}" >&2
  exit 1
fi

echo "Serving from ${REPO_ROOT} on http://localhost:${PORT}"
echo "OBS Browser Source URL: http://localhost:${PORT}/thoughts.html"
echo "Press Ctrl+C to stop."
echo

exec python3 -m http.server "${PORT}"
