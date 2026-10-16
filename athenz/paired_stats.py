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


class SelectiveConfidenceAccumulator:
    """Finite-grid selective prediction audit with no per-case retention.

    A cutoff means the model must report confidence >= cutoff to be counted
    as an answered prediction. This does not calibrate self-reported confidence
    or authorize deployment/automatic action.
    """

    _CUTOFFS = (0.5, 0.6, 0.7, 0.8, 0.9)
    _MIN_GRID_SAMPLES = 20
    _MIN_PUBLISHED_ANSWERS = 5

    def __init__(self) -> None:
        self._bins = [[0, 0] for _ in range(10)]
        self.samples = 0

    @classmethod
    def validate_cutoff(cls, cutoff: float | None) -> float | None:
        if cutoff is None:
            return None
        if type(cutoff) not in (float, int) or not isfinite(cutoff):
            raise ValueError("Confidence cutoff must be one of 0.5, 0.6, 0.7, 0.8, 0.9")
        if float(cutoff) not in cls._CUTOFFS:
            raise ValueError("Confidence cutoff must be one of 0.5, 0.6, 0.7, 0.8, 0.9")
        return float(cutoff)

    def add(self, probability: float, *, correct: bool) -> None:
        if (type(probability) not in (int, float) or not isfinite(probability)
                or not 0 <= probability <= 1 or type(correct) is not bool
                or self.samples >= 1000):
            raise ValueError("Invalid confidence prediction outcome")
        index = min(9, int(probability * 10))
        self._bins[index][0] += 1
        self._bins[index][1] += int(correct)
        self.samples += 1

    def _threshold(self, cutoff: float, total: int, *, grid: bool) -> dict:
        threshold = int(round(cutoff * 10))
        accepted = sum(count for count, _ in self._bins[threshold:])
        correct = sum(wins for _, wins in self._bins[threshold:])
        # Exclude malformed predictions from accepted; their absence already
        # reduces coverage measured against all held-out cases.
        result = {"cutoff": cutoff}
        if accepted < self._MIN_PUBLISHED_ANSWERS:
            return {**result, "status": "insufficient-accepted-cases",
                    "coverage": None, "accuracy": None}
        return {**result, "status": "descriptive",
                "coverage": accepted / total if total else None,
                "accuracy": correct / accepted}

    def report(self, total: int, *, cutoff: float | None = None,
               calibration_grid: bool = False) -> dict:
        if (type(total) is not int or total < self.samples or total > 1000
                or type(calibration_grid) is not bool):
            raise ValueError("Invalid confidence evaluation case count")
        cutoff = self.validate_cutoff(cutoff)
        return {
            "scored_predictions": self.samples,
            "all_heldout_cases": total,
            "minimum_accepted_cases_for_accuracy": self._MIN_PUBLISHED_ANSWERS,
            "selection_rule": "self_reported_probability_at_least_cutoff",
            "selected_cutoff": cutoff,
            "selected_metrics": (
                self._threshold(cutoff, total, grid=False)
                if cutoff is not None else None),
            "calibration_grid": (
                {"status": "descriptive", "thresholds": [
                    self._threshold(t, total, grid=True)
                    for t in self._CUTOFFS]}
                if total >= self._MIN_GRID_SAMPLES
                and self.samples >= self._MIN_GRID_SAMPLES
                else {"status": "insufficient-calibration-samples",
                      "thresholds": []}
            ) if calibration_grid else {"enabled": False},
            "cutoff_chosen_by_algorithm": False,
            "confidence_is_calibrated": False,
            "selective_scores_are_independent_tests": False,
        }
