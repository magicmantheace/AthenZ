"""Privacy-safe aggregate statistics for paired decision prediction.

Operate on counts only; never handle owner choices, prompts, or model text.
Statistical tests assume independent held-out cases, which lexical dedupe
alone cannot establish.
"""
from __future__ import annotations

from math import comb, isfinite, sqrt


def exact_paired_sign_test(twin_only: int, neutral_only: int) -> float | None:
    """Two-sided exact McNemar/binomial p under equal discordant success.

    A p-value is deliberately absent when no prediction outcomes disagree.
    Total discordant pairs are bounded by evaluation's 1000 case limit.
    """
    if (type(twin_only) is not int or type(neutral_only) is not int
            or min(twin_only, neutral_only) < 0
            or twin_only + neutral_only > 1000):
        raise ValueError("Invalid paired contingency counts")
    discordant = twin_only + neutral_only
    if not discordant:
        return None
    tail = sum(comb(discordant, k)
               for k in range(min(twin_only, neutral_only) + 1))
    return min(1.0, 2 * (tail / (2 ** discordant)))


def discordant_win_interval(twin_only: int, neutral_only: int) -> list[float] | None:
    """Descriptive 95% Wilson interval for wins among discordant pairs."""
    if (type(twin_only) is not int or type(neutral_only) is not int
            or min(twin_only, neutral_only) < 0
            or twin_only + neutral_only > 1000):
        raise ValueError("Invalid paired contingency counts")
    n = twin_only + neutral_only
    if n == 0:
        return None
    z = 1.959963984540054
    p = twin_only / n
    denominator = 1 + z * z / n
    center = (p + z * z / (2 * n)) / denominator
    radius = (z * sqrt((p * (1 - p) / n) + z * z / (4 * n * n))) / denominator
    return [max(0.0, center - radius), min(1.0, center + radius)]


class ConfidenceAccumulator:
    """Bounded, aggregate-only calibration of a claimed chosen-answer chance.

    Inputs are ephemeral. Only ten fixed bins and totals are retained, never
    case-level probabilities, labels, explanations, or personal text.
    This does not learn a calibration mapping or assert well-calibrated output.
    """

    def __init__(self) -> None:
        self._count = 0
        self._sum_probability = 0.0
        self._sum_squared_error = 0.0
        self._correct = 0
        self._bins = [[0, 0.0, 0] for _ in range(10)]

    def add(self, probability: float, *, correct: bool) -> None:
        if (type(probability) not in (int, float)
                or not isfinite(probability) or not 0 <= probability <= 1
                or type(correct) is not bool
                or self._count >= 1000):
            raise ValueError("Invalid reported confidence or calibration outcome")
        chance = float(probability)
        outcome = int(correct)
        self._count += 1
        self._correct += outcome
        self._sum_probability += chance
        self._sum_squared_error += (chance - outcome) ** 2
        bucket = min(9, int(chance * 10))
        self._bins[bucket][0] += 1
        self._bins[bucket][1] += chance
        self._bins[bucket][2] += outcome

    def report(self) -> dict:
        """Summary is safe to serialize, even for zero valid predictions."""
        n = self._count
        if not n:
            return {
                "samples": 0,
                "mean_reported_confidence": None,
                "accuracy_on_scored_responses": None,
                "chosen_answer_brier_score": None,
                "expected_calibration_error_10bins": None,
            }
        # Compare model's claimed probability the selected choice is correct
        # to binary correctness; this is not a full multiclass Brier score.
        ece = sum(
            count / n * abs((confidence_sum / count) - (correct_sum / count))
            for count, confidence_sum, correct_sum in self._bins if count
        )
        return {
            "samples": n,
            "mean_reported_confidence": self._sum_probability / n,
            "accuracy_on_scored_responses": self._correct / n,
            "chosen_answer_brier_score": self._sum_squared_error / n,
            "expected_calibration_error_10bins": ece,
        }



class ChoiceStabilityCounter:
    """Within-case semantic choice agreement; only aggregate counters persist.

    The transient list handed to add_choices is discarded by the evaluator
    after each case. An ABSTAIN or invalid answer cannot count as agreement.
    This is descriptive stability, not owner-choice accuracy or independence.
    """

    def __init__(self) -> None:
        self.cases = 0
        self.all_valid_cases = 0
        self.unanimous_cases = 0
        self.valid_pair_comparisons = 0
        self.agreeing_pairs = 0
        self.valid_trials = 0
        self.invalid_trials = 0
        self.abstention_trials = 0

    def add_choices(self, choices: list[str]) -> None:
        if (not isinstance(choices, list) or len(choices) not in (2, 3)
                or any(not isinstance(x, str) for x in choices)
                or self.cases >= 1000):
            raise ValueError("Invalid bounded stability trial results")
        self.cases += 1
        valid = [value for value in choices if value and value != "ABSTAIN"]
        self.valid_trials += len(valid)
        self.invalid_trials += sum(value == "" for value in choices)
        self.abstention_trials += sum(value == "ABSTAIN" for value in choices)
        if len(valid) == len(choices):
            self.all_valid_cases += 1
            if all(value == valid[0] for value in valid):
                self.unanimous_cases += 1
        for i, value in enumerate(choices):
            if not value or value == "ABSTAIN":
                continue
            for candidate in choices[i + 1:]:
                if not candidate or candidate == "ABSTAIN":
                    continue
                self.valid_pair_comparisons += 1
                self.agreeing_pairs += int(value == candidate)

    def report(self) -> dict:
        return {
            "cases": self.cases,
            "cases_with_all_valid_choices": self.all_valid_cases,
            "unanimous_cases": self.unanimous_cases,
            "unanimous_rate_on_fully_answered_cases": (
                self.unanimous_cases / self.all_valid_cases
                if self.all_valid_cases else None),
            "valid_pair_comparisons": self.valid_pair_comparisons,
            "agreeing_pairs": self.agreeing_pairs,
            "pairwise_semantic_agreement": (
                self.agreeing_pairs / self.valid_pair_comparisons
                if self.valid_pair_comparisons else None),
            "valid_trials": self.valid_trials,
            "invalid_trials": self.invalid_trials,
            "abstention_trials": self.abstention_trials,
        }
