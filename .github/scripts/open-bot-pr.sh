#!/usr/bin/env bash
# Commit the job's changes to a bot branch and open (or update) ONE pull request.
#
#   open-bot-pr.sh BRANCH TITLE BODY_FILE [LABEL]
#
# Replaces peter-evans/create-pull-request in fetch-vintages.yml and
# nowcast-round.yml. That action always tries to CREATE first and only falls
# back to updating on a 422 "already exists". Since 26 Oct 2026 the repo setting
# "Allow GitHub Actions to create and approve pull requests" is off, the create
# call returns 403 instead, and the action fails before it ever updates the PR
# that already exists (#195). This script looks for the open PR first, so an
# existing PR keeps being updated whatever that setting says; only a brand-new
# PR needs the permission (or a DATA_PR_TOKEN secret), and when it is missing
# the job says exactly that.
#
# Guarantees:
#   * never pushes to main/master or to anything outside data/ and forecasts/
#     bot namespaces;
#   * force-with-lease against the branch tip this job started from (see
#     below), so a commit pushed to the bot branch mid-run fails the push
#     rather than being silently overwritten;
#   * no commit and no PR when nothing changed.
set -euo pipefail

branch="${1:?branch}"
title="${2:?title}"
body="${3:?body file}"
label="${4:-}"

case "$branch" in
  data/*|forecasts/*) ;;
  *)
    echo "::error::refusing to push bot changes to '$branch' (allowed: data/*, forecasts/*)"
    exit 1
    ;;
esac

if [ -z "$(git status --porcelain)" ]; then
  echo "nothing changed; no commit, no PR"
  exit 0
fi

git config user.name "github-actions[bot]"
git config user.email "41898282+github-actions[bot]@users.noreply.github.com"

# The lease is the tip this job STARTED from: the tracking ref data/refresh.py
# fetched for --carry-from. A commit pushed to the bot branch after that fetch
# makes the push fail instead of being overwritten. Jobs that did not fetch the
# branch (nowcast) fall back to the tip seen now, which only guards the push
# against a concurrent bot run.
lease=""
seen="$(git rev-parse -q --verify "refs/remotes/origin/$branch" 2>/dev/null || true)"
if [ -z "$seen" ] && git ls-remote --exit-code --heads origin "$branch" >/dev/null 2>&1; then
  seen="$(git ls-remote --heads origin "$branch" | cut -f1)"
fi
[ -n "$seen" ] && lease="--force-with-lease=refs/heads/$branch:$seen"

git checkout -B "$branch"
git add -A .
git commit -q -m "$title"
# shellcheck disable=SC2086
git push $lease origin "HEAD:refs/heads/$branch" 2>&1 | sed 's/^/  /'
echo "pushed $(git rev-parse --short HEAD) to $branch"

if [ "${OPEN_PR:-true}" != "true" ]; then
  echo "OPEN_PR=${OPEN_PR}; branch pushed, PR step skipped"
  exit 0
fi

existing="$(gh pr list --head "$branch" --state open --json number --jq '.[0].number // empty')"
if [ -n "$existing" ]; then
  # REST rather than `gh pr edit`, which also queries project cards and can
  # fail with "Resource not accessible by integration" under GITHUB_TOKEN.
  gh api -X PATCH "repos/${GITHUB_REPOSITORY:-PolicyEngine/macro}/pulls/$existing" \
    -f title="$title" -F body=@"$body" --silent
  echo "updated PR #$existing"
  exit 0
fi

errfile="${RUNNER_TEMP:-/tmp}/pr-create.err"
args=(--base main --head "$branch" --title "$title" --body-file "$body")
[ -n "$label" ] && args+=(--label "$label")
if ! gh pr create "${args[@]}" 2>"$errfile"; then
  cat "$errfile"
  if grep -qi "not permitted to create" "$errfile"; then
    echo "::error::Branch $branch is pushed but no PR could be opened: GitHub Actions may not create pull requests in this repo. Either enable Settings → Actions → General → 'Allow GitHub Actions to create and approve pull requests', or add a DATA_PR_TOKEN secret (fine-grained PAT or app token with contents+pull-requests write). Meanwhile open it by hand: https://github.com/${GITHUB_REPOSITORY:-PolicyEngine/macro}/compare/main...$branch"
  fi
  exit 1
fi
