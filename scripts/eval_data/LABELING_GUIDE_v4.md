# Gold Set V4 Labeling Guide

Label `ground_truth_type` using the strongest logical relationship that is
always true between the two markets.

## Allowed labels

- `implication`
  Use when one market outcome logically requires the other.
  Example: "Team wins tournament" implies "Team reaches semifinal".

- `mutual_exclusion`
  Use when the key winning outcomes cannot both happen.
  Example: two different winners of the same single-winner series.

- `partition`
  Use when the markets split the same event space into exhaustive buckets.
  Example: adjacent exact-count or bracket markets that cover all outcomes.

- `conditional`
  Use when markets are related but neither implication nor mutual exclusion is
  guaranteed.
  Example: spread vs totals, O/U vs BTTS, correlated same-game props.

- `none`
  Use when there is no dependable logical relationship.
  Shared topic or team name alone is not enough.

## Review rules

- Judge logic, not price behavior. Ignore whether the pair traded profitably.
- Prefer `none` over a weak theory. False positives matter more than misses.
- Use `notes` to record why a pair is tricky or borderline.
- Keep `correct` aligned with the current system label in the file:
  set `true` when `current_dependency_type` matches your ground truth,
  else `false`.

## Family cues

- `crypto_threshold_ladder`: same asset, different thresholds or deadlines.
- `fed_rate_cut_ladder`: same central-bank decision family, different cut counts.
- `date_window_nesting`: same underlying event with nested deadlines.
- `winner_duplicate`: same event winner framed in duplicate ways.
- `sports_winner_vs_game`: winner/spread market paired with map/game/set market.
- `sports_ou_btts`: totals paired with both-teams-to-score.
- `same_team_nearby_match_negative`: same team/entity, but different competitions or dates.

These tags are hints for review coverage, not ground truth by themselves.
