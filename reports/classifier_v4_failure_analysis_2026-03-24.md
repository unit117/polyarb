# Classifier Dataset Analysis

- Total labeled pairs: 168
- Current-system accuracy: 99/168 (58.9%)

## Current Label Counts

- conditional: 25
- implication: 45
- mutual_exclusion: 35
- none: 40
- partition: 23

## Ground Truth Counts

- conditional: 40
- implication: 63
- mutual_exclusion: 53
- none: 12

## Largest Label Transitions

- none -> mutual_exclusion: 16
- none -> implication: 14
- partition -> none: 12
- none -> conditional: 10
- partition -> conditional: 7
- conditional -> implication: 4
- implication -> conditional: 2
- partition -> mutual_exclusion: 2

## Worst Families

- weather_temp_ladder_negative: 12/12 wrong (100.0%) [none->mutual_exclusion:12]
- sports_ou_ladder_negative: 12/12 wrong (100.0%) [none->implication:12]
- social_post_window_negative: 6/6 wrong (100.0%) [none->conditional:6]
- geopolitical_window_negative: 3/3 wrong (100.0%) [none->mutual_exclusion:2, none->conditional:1]
- sports_spread_ladder_negative: 2/2 wrong (100.0%) [none->implication:2]
- ai_model_horizon_negative: 2/2 wrong (100.0%) [none->conditional:2]
- scalar_threshold_negative: 1/1 wrong (100.0%) [none->mutual_exclusion:1]
- intraday_direction_negative: 1/1 wrong (100.0%) [none->conditional:1]

## Sample Disagreements

### none -> mutual_exclusion (16)

- [event_timing_negative] Will Backpack launch a token on March 27? || Will Backpack launch a token on March 28?
  note: A first launch date cannot be both March 27 and March 28.
- [scalar_threshold_negative] Will James Talarico win the Texas Democratic Senate Primary by between 9.00% and 9.50%? || Will James Talarico win the Texas Democratic Senate Primary by between 9.50% and 10.00%?
  note: Adjacent exact margin brackets cannot both resolve Yes.

### none -> implication (14)

- [sports_spread_ladder_negative] Spread: Brighton & Hove Albion FC (-1.5) || Spread: Brighton & Hove Albion FC (-2.5)
  note: The steeper handicap is nested inside the looser handicap.
- [sports_ou_ladder_negative] Vancouver Whitecaps FC vs. San Jose Earthquakes: O/U 2.5 || Vancouver Whitecaps FC vs. San Jose Earthquakes: O/U 3.5
  note: The stricter total line is nested inside the looser total line.

### partition -> none (12)

- [winner_duplicate] Will Phil Parrish win the 2026 Minnesota Governor Republican primary election? || Will Tim Walz win the 2026 Minnesota Governor Democratic primary election?
  note: Different party primaries are separate races.
- [other] T20I Series New Zealand vs South Africa, Women: New Zealand vs South Africa - Completed match? || T20 Series New Zealand vs South Africa: New Zealand vs South Africa - Completed match?
  note: Women's and men's fixtures are separate matches.

### none -> conditional (10)

- [ai_model_horizon_negative] Will Meituan have the best AI model at the end of March 2026? || Will Meituan have the best AI model at the end of June 2026?
  note: Same company across different leaderboard dates is related but not logically forced.
- [intraday_direction_negative] Solana Up or Down - March 21, 1AM ET || Solana Up or Down - March 21, 6AM ET
  note: Different hourly candles are related but neither direction implies the other.

### partition -> conditional (7)

- [other] Will "27 Dresses" be the top global Netflix movie this week? || Will "27 Dresses" be the top US Netflix movie this week?
  note: Same title across global and US Netflix rankings is related but not logically implied.
- [other] Will "Mark Normand: None Too Pleased" be the #2 global Netflix show this week? || Will "Mark Normand: None Too Pleased" be the #2 US Netflix show this week?
  note: Same title across global and US Netflix rankings is related but not logically implied.

### conditional -> implication (4)

- [winner_duplicate] Will the New York Giants win the 2027 NFL league championship? || Will New York Giants win the 2027 NFL NFC Championship?
  note: Winning the league/finals title requires winning the conference title first.
- [winner_duplicate] Will Germán Vargas Lleras win the 1st round of the 2026 Colombian presidential election? || Will Germán Vargas Lleras win the 2026 Colombian presidential election?
  note: Winning the first round of the Colombian presidential election implies winning the election outright.

### implication -> conditional (2)

- [winner_duplicate] Will the Freedom Movement (GS) win the most seats in the 2026 Slovenian parliamentary election? || Will the Freedom Movement (GS) win 40+ seats in the Slovenian National Assembly in this election?
  note: Seat-count and most-seats outcomes are related but neither implies the other.
- [winner_duplicate] Will Gretchen Whitmer win the 2028 Democratic presidential nomination? || Will Gretchen Whitmer win the 2028 US Presidential Election?
  note: Nomination and general-election win are related but neither always guarantees the other.

### partition -> mutual_exclusion (2)

- [other] T20I Series New Zealand vs South Africa, Women: New Zealand vs South Africa - Team Top Batter New Zealand Winner || T20I Series New Zealand vs South Africa, Women: New Zealand vs South Africa - Team Top Batter Draw
  note: Within the same three-way top-batter market, New Zealand winner and Draw cannot both resolve Yes.
- [other] Will "Louis Theroux: Inside The Manosphere" be the #2 global Netflix movie this week? || Will "Saw" be the #2 global Netflix movie this week?
  note: Only one title can be the #2 global Netflix movie for that week.
