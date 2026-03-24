from scripts import export_goldset_v4
from collections import Counter


class TestGoldsetFamilyTagging:
    def test_classifies_crypto_threshold_ladder(self):
        family = export_goldset_v4.classify_pair_family(
            "Will Bitcoin be above $110k on December 31, 2026?",
            "Will Bitcoin be above $120k on December 31, 2026?",
        )

        assert family == "crypto_threshold_ladder"

    def test_classifies_sports_ou_btts(self):
        family = export_goldset_v4.classify_pair_family(
            "Arsenal vs. Chelsea: O/U 2.5",
            "Arsenal vs. Chelsea: Both Teams to Score",
        )

        assert family == "sports_ou_btts"

    def test_classifies_date_window_nesting(self):
        family = export_goldset_v4.classify_pair_family(
            "Will Bitcoin reach $100k by June 30, 2026?",
            "Will Bitcoin reach $100k by December 31, 2026?",
        )

        assert family == "date_window_nesting"

    def test_classifies_same_team_negative_for_none_candidates(self):
        family = export_goldset_v4.classify_pair_family(
            "Will Arsenal win the 2026 Champions League?",
            "Will Arsenal finish top 4 in the 2025-26 Premier League?",
            dep_type="none_candidate",
        )

        assert family == "same_team_nearby_match_negative"

    def test_classifies_weather_temp_negative(self):
        family = export_goldset_v4.classify_pair_family(
            "Will the highest temperature in Hong Kong be 22°C on March 21?",
            "Will the highest temperature in Hong Kong be 23°C on March 21?",
            dep_type="none_candidate",
        )

        assert family == "weather_temp_ladder_negative"

    def test_classifies_sports_ou_ladder_negative(self):
        family = export_goldset_v4.classify_pair_family(
            "Vancouver Whitecaps FC vs. San Jose Earthquakes: O/U 2.5",
            "Vancouver Whitecaps FC vs. San Jose Earthquakes: O/U 3.5",
            dep_type="none_candidate",
        )

        assert family == "sports_ou_ladder_negative"

    def test_classifies_sports_spread_ladder_negative(self):
        family = export_goldset_v4.classify_pair_family(
            "Spread: Brighton & Hove Albion FC (-1.5)",
            "Spread: Brighton & Hove Albion FC (-2.5)",
            dep_type="none_candidate",
        )

        assert family == "sports_spread_ladder_negative"

    def test_classifies_social_post_window_negative(self):
        family = export_goldset_v4.classify_pair_family(
            "Will Elon Musk post 140-164 tweets from March 19 to March 21, 2026?",
            "Will Elon Musk post 140-164 tweets from March 21 to March 23, 2026?",
            dep_type="none_candidate",
        )

        assert family == "social_post_window_negative"

    def test_classifies_ai_model_horizon_negative(self):
        family = export_goldset_v4.classify_pair_family(
            "Will Meituan have the best AI model at the end of March 2026?",
            "Will Meituan have the best AI model at the end of June 2026?",
            dep_type="none_candidate",
        )

        assert family == "ai_model_horizon_negative"

    def test_classifies_event_timing_negative(self):
        family = export_goldset_v4.classify_pair_family(
            "Will Backpack launch a token on March 27?",
            "Will Backpack launch a token on March 28?",
            dep_type="none_candidate",
        )

        assert family == "event_timing_negative"

    def test_classifies_intraday_direction_negative(self):
        family = export_goldset_v4.classify_pair_family(
            "Solana Up or Down - March 21, 1AM ET",
            "Solana Up or Down - March 21, 6AM ET",
            dep_type="none_candidate",
        )

        assert family == "intraday_direction_negative"

    def test_does_not_treat_solana_person_as_crypto_threshold(self):
        family = export_goldset_v4.classify_pair_family(
            "Will Solana Sierra be the 2026 Women's Wimbledon Winner?",
            "Will Ashlyn Krueger be the 2026 Women's Wimbledon Winner?",
            dep_type="mutual_exclusion",
        )

        assert family == "winner_duplicate"

    def test_ignores_description_date_boilerplate_for_winner_family(self):
        description = (
            "If no winner is announced by June 30, 2026, this market will resolve to Other."
        )
        family = export_goldset_v4.classify_pair_family(
            "Will Charles Hittler be the next mayor of Arcis-sur-Aube?",
            "Will Antoine Renault-Zielinski be the next mayor of Arcis-sur-Aube?",
            description,
            description,
            dep_type="mutual_exclusion",
        )

        assert family == "winner_duplicate"

    def test_classifies_fed_pairs_before_date_window(self):
        family = export_goldset_v4.classify_pair_family(
            "Will the Fed decrease interest rates by 50+ bps after the June 2026 meeting?",
            "Will the Fed increase interest rates by 50+ bps after the June 2026 meeting?",
            dep_type="mutual_exclusion",
        )

        assert family == "fed_rate_cut_ladder"


class TestGoldsetExclusions:
    def test_excludes_trivial_duplicate(self):
        assert export_goldset_v4.should_exclude_pair(
            "Will Arsenal win the 2026 Champions League?",
            "Will Arsenal win the 2026 Champions League?",
            "Long enough description to be useful.",
            "Long enough description to be useful.",
            ["Yes", "No"],
            ["Yes", "No"],
        )

    def test_excludes_missing_text(self):
        assert export_goldset_v4.should_exclude_pair(
            "BTC up?",
            "Will Bitcoin reach $100k by June 30, 2026?",
            "",
            "Long enough description to be useful.",
            ["Yes", "No"],
            ["Yes", "No"],
        )


class TestGoldsetScoring:
    def test_verified_candidates_outscore_resolved_fallbacks(self):
        candidate = {
            "pair_family": "other",
            "current_confidence": 0.9,
            "shared_keywords": ["arsenal", "chelsea"],
            "selection_bucket": "resolved_unverified",
            "verified": False,
        }

        verified_candidate = dict(candidate, verified=True, selection_bucket="resolved_verified")

        assert (
            export_goldset_v4._candidate_score(verified_candidate)
            > export_goldset_v4._candidate_score(candidate)
        )


class TestHardNegativeDiversity:
    def test_safe_none_family_allowlist_excludes_structured_negative_families(self):
        assert export_goldset_v4._is_safe_none_family("same_team_nearby_match_negative")
        assert export_goldset_v4._is_safe_none_family("other")
        assert not export_goldset_v4._is_safe_none_family("weather_temp_ladder_negative")
        assert not export_goldset_v4._is_safe_none_family("sports_ou_ladder_negative")
        assert not export_goldset_v4._is_safe_none_family("social_post_window_negative")

    def test_hard_negative_signature_drops_generic_tokens(self):
        record = {
            "shared_entities": ["2026", "elon", "march", "musk", "post"],
            "shared_keywords": ["2026", "elon", "march", "musk", "post"],
            "market_a_id": 1,
            "market_b_id": 2,
        }

        assert export_goldset_v4._hard_negative_signature(record) == ("elon", "musk")

    def test_select_balanced_caps_repeated_hard_negative_signatures(self):
        def candidate(a_id: int, b_id: int, shared_entities: list[str]) -> dict:
            return {
                "pair_id": None,
                "market_a_id": a_id,
                "market_b_id": b_id,
                "pair_family": "same_team_nearby_match_negative",
                "current_confidence": 0.0,
                "shared_keywords": shared_entities,
                "shared_entities": shared_entities,
                "selection_bucket": "hard_negative",
                "semantic_similarity": 0.99,
                "verified": False,
            }

        candidates = [
            candidate(1, 101, ["elon", "musk", "post"]),
            candidate(2, 102, ["elon", "musk", "post"]),
            candidate(3, 103, ["elon", "musk", "post"]),
            candidate(4, 104, ["meituan", "model"]),
        ]

        selected = export_goldset_v4._select_balanced(
            candidates,
            target=3,
            family_cap=10,
            signature_cap=2,
        )
        signature_counts = Counter(
            export_goldset_v4._hard_negative_signature(row) for row in selected
        )

        assert len(selected) == 3
        assert signature_counts[("elon", "musk")] == 2
        assert signature_counts[("meituan",)] == 1

    def test_seed_family_coverage_prioritizes_sparse_families(self):
        def candidate(idx: int, family: str, score: float) -> dict:
            return {
                "pair_id": None,
                "market_a_id": idx,
                "market_b_id": idx + 1000,
                "pair_family": family,
                "current_confidence": score,
                "shared_keywords": [family],
                "shared_entities": [family],
                "selection_bucket": "hard_negative",
                "semantic_similarity": score,
                "verified": False,
            }

        candidates = [
            candidate(1, "social_post_window_negative", 0.99),
            candidate(2, "social_post_window_negative", 0.98),
            candidate(3, "weather_temp_ladder_negative", 0.97),
            candidate(4, "ai_model_horizon_negative", 0.96),
        ]

        seeded = export_goldset_v4._seed_family_coverage(candidates, target=2)

        assert {row["pair_family"] for row in seeded} == {
            "ai_model_horizon_negative",
            "weather_temp_ladder_negative",
        }
