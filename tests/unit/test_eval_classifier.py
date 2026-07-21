from scripts import eval_classifier


def test_summarize_labeled_pairs_groups_confusions_and_normalizes_none_candidate():
    pairs = [
        {
            "current_dependency_type": "implication",
            "ground_truth_type": "implication",
            "correct": True,
            "pair_family": "crypto_threshold_ladder",
            "question_a": "A",
            "question_b": "B",
            "notes": "",
        },
        {
            "current_dependency_type": "partition",
            "ground_truth_type": "none",
            "correct": False,
            "pair_family": "other",
            "question_a": "Top 4 Team A?",
            "question_b": "Top 4 Team B?",
            "notes": "Different teams can independently make or miss the same league threshold.",
        },
        {
            "current_dependency_type": "none",
            "ground_truth_type": "mutual_exclusion",
            "correct": False,
            "pair_family": "weather_temp_ladder_negative",
            "question_a": "Temp 22C?",
            "question_b": "Temp 23C?",
            "notes": "These are distinct exact temperature brackets for the same day.",
        },
        {
            "current_dependency_type": "none_candidate",
            "ground_truth_type": "none",
            "correct": True,
            "pair_family": "same_team_nearby_match_negative",
            "question_a": "Arsenal win UCL?",
            "question_b": "Arsenal top 4?",
            "notes": "",
        },
    ]

    summary = eval_classifier._summarize_labeled_pairs(
        pairs,
        examples_per_transition=1,
    )

    assert summary["total"] == 4
    assert summary["correct"] == 2
    assert summary["current_counts"]["implication"] == 1
    assert summary["current_counts"]["partition"] == 1
    assert summary["current_counts"]["none"] == 2
    assert summary["ground_truth_counts"]["none"] == 2
    assert summary["ground_truth_counts"]["mutual_exclusion"] == 1
    assert summary["confusion"][("partition", "none")] == 1
    assert summary["confusion"][("none", "mutual_exclusion")] == 1
    assert summary["family_wrong"]["other"] == 1
    assert summary["family_wrong"]["weather_temp_ladder_negative"] == 1
    assert summary["family_wrong"]["same_team_nearby_match_negative"] == 0
    assert len(summary["transition_examples"][("partition", "none")]) == 1
    assert summary["transition_examples"][("partition", "none")][0]["pair_family"] == "other"
