# Forecast track record

A real-time record of every forecast the site publishes: archived with a
timestamp *before* the outturn exists, then scored against realised data.

This is not the same thing as the pseudo-out-of-sample evaluation in
`papers/boe-svar/figures/rolling_evaluation.json`, which re-estimates the model
at 49 expanding-window origins and compares it with random-walk, drift and AR(1)
baselines. That tests the method; the modeller already knew what happened. This
directory tests the forecasts, in real time, where nobody does.

## Layout

| path | mutable? | what it is |
|------|----------|------------|
| `rounds/<round-id>/<model>.json` | **no** | A forecast as it stood on a date. Append-only. |
| `outturns.json` | append-only | Realised data, versioned by vintage. Written by `ingest_outturns.py` from `data/`. |
| `scorecard.json` | generated | Scores. Written by `score.py`, never by hand. |
| `index.html` | partly generated | The public page. Blocks between `<!-- scorecard-*:begin -->` markers are generated. |

## Running a round

```bash
# 1. Refresh the model artifact (in the model repo), then archive it here.
python3 forecasts/archive.py

# 2. Commit the round BEFORE the outturn is published. This is the whole point:
#    the git timestamp is what makes the forecast falsifiable.
git add forecasts/rounds && git commit -m "Archive forecast round <date>"

# 3. When outturns land, pull them from the vintage store and rescore.
python3 data/fetch.py
python3 forecasts/ingest_outturns.py
python3 forecasts/score.py
```

All three scripts take `--check` and are wired into
`.github/workflows/forecast-archive.yml`, which also fails any pull request that
modifies, renames or deletes an already-archived round.

## Rules that are not negotiable

- **Rounds are append-only.** A forecast built on a mistake is corrected by
  archiving a new round, not by editing the old one. The superseded round stays
  in the history where it can still be counted against us.
- **Outturns are versioned, not overwritten.** ONS revisions get a new vintage
  entry. Scoring always records which vintage it used, so any published score
  can be reproduced.
- **No headline accuracy figure until there is one to state.** With zero scored
  periods the page says zero. An impressive number derived from one observation
  is worse than an empty record, because the empty record is honest.
- **Every forecast is reported beside a naive baseline.** Beating a random walk
  is the minimum bar for a model to have earned its complexity.

## Adding a model

Add its artifact path to `SOURCES` in `archive.py`. The artifact needs a
`forecast` block keyed `period → variable → {median, lo68, hi68, lo90, hi90}`,
plus `data_edge` and `generated`. Rounds hold one file per model, so models can
join at different dates without disturbing the existing history.
