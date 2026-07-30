#!/usr/bin/env bash
# Code-tab Step 1 — install dependencies.
#
# Prerequisites: Python 3.11+ and uv (https://docs.astral.sh/uv/).
# You also need a HuggingFace token with read access to
# `policyengine/policyengine-uk-data`. Create one at
# https://huggingface.co/settings/tokens.

set -euo pipefail

# Resolve and install everything in pyproject.toml.
uv sync

cat <<EOF

Done. Now set your HuggingFace token and try a steady-state solve:

  export HUGGING_FACE_TOKEN=hf_your_token_here
  uv run python scripts/03_steady_state.py
EOF
