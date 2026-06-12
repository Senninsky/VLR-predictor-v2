import json
import random
from bisect import bisect_left
from pathlib import Path


class Bookkeeper:
    def __init__(self, odds_pairs_path="bookkeeper_odds_pairs.json"):
        self.odds_pairs_path = Path(odds_pairs_path)
        self._odds_pairs_cache = None

    def show_odds_distribution(self):
        odds_pairs = sorted(self._load_odds_pairs())

        if not odds_pairs:
            print("No odds pairs available to plot.")
            return

        try:
            import matplotlib.pyplot as plt
        except ImportError as error:
            raise RuntimeError(
                "matplotlib is required to show the odds distribution. "
                "Install it with: pip install matplotlib"
            ) from error

        lower_odds = [odds_pair[0] for odds_pair in odds_pairs]
        higher_odds = [odds_pair[1] for odds_pair in odds_pairs]

        _, axis = plt.subplots(figsize=(10, 6))
        axis.scatter(lower_odds, higher_odds, s=70, alpha=0.8)

        axis.set_title("Bookkeeper Odds Distribution")
        axis.set_xlabel("Lower decimal odds")
        axis.set_ylabel("Higher decimal odds")
        axis.grid(alpha=0.3)

        plt.tight_layout()
        plt.show()

    def keep_odds_pairs(self, odds_pairs):
        stored_pairs = self._load_odds_pairs()

        for odds_pair in odds_pairs:
            normalized_pair = self._normalize_odds_pair(odds_pair)

            if normalized_pair:
                stored_pairs.add(normalized_pair)

        self._save_odds_pairs(stored_pairs)
        self._odds_pairs_cache = stored_pairs

    def get_paired_odds(self, odds):
        normalized_odds = self._normalize_single_odd(odds)

        if normalized_odds is None:
            return 0.0

        odds_pairs = self._get_odds_pairs()

        if not odds_pairs:
            return 0.0

        counterpart_map = self._get_counterpart_map(odds_pairs)

        if normalized_odds in counterpart_map:
            return random.choice(counterpart_map[normalized_odds])

        recorded_odds = sorted(counterpart_map)
        insert_index = bisect_left(recorded_odds, normalized_odds)

        if insert_index == 0 or insert_index == len(recorded_odds):
            return self._estimate_paired_odds_from_average_vig(normalized_odds, odds_pairs)

        lower_odds = recorded_odds[insert_index - 1]
        higher_odds = recorded_odds[insert_index]
        lower_counterpart = random.choice(counterpart_map[lower_odds])
        higher_counterpart = random.choice(counterpart_map[higher_odds])

        return self._interpolate(
            normalized_odds,
            lower_odds,
            lower_counterpart,
            higher_odds,
            higher_counterpart,
        )

    def _load_odds_pairs(self):
        if not self.odds_pairs_path.exists():
            return set()

        with self.odds_pairs_path.open("r", encoding="utf-8") as file:
            try:
                odds_pairs = json.load(file)
            except json.JSONDecodeError:
                return set()

        return {
            normalized_pair
            for odds_pair in odds_pairs
            if (normalized_pair := self._normalize_odds_pair(odds_pair))
        }

    def _get_odds_pairs(self):
        if self._odds_pairs_cache is None:
            self._odds_pairs_cache = self._load_odds_pairs()

        return self._odds_pairs_cache

    def _save_odds_pairs(self, odds_pairs):
        ordered_pairs = [
            [team_1_odds, team_2_odds]
            for team_1_odds, team_2_odds in sorted(odds_pairs)
        ]

        with self.odds_pairs_path.open("w", encoding="utf-8") as file:
            json.dump(ordered_pairs, file, indent=2)
            file.write("\n")

    def _normalize_odds_pair(self, odds_pair):
        if isinstance(odds_pair, dict):
            odds_pair = [odds_pair.get("team_1_odds"), odds_pair.get("team_2_odds")]

        if len(odds_pair) < 2:
            return None

        try:
            odds = sorted([round(float(odds_pair[0]), 6), round(float(odds_pair[1]), 6)])
        except (TypeError, ValueError):
            return None

        if odds[0] <= 0 or odds[1] <= 0:
            return None

        return odds[0], odds[1]

    def _normalize_single_odd(self, odds):
        try:
            odds = round(float(odds), 6)
        except (TypeError, ValueError):
            return None

        if odds <= 0:
            return None

        return odds

    def _get_counterpart_map(self, odds_pairs):
        counterpart_map = {}

        for team_1_odds, team_2_odds in odds_pairs:
            counterpart_map.setdefault(team_1_odds, []).append(team_2_odds)
            counterpart_map.setdefault(team_2_odds, []).append(team_1_odds)

        return counterpart_map

    def _interpolate(self, odds, lower_odds, lower_counterpart, higher_odds, higher_counterpart):
        if higher_odds == lower_odds:
            return round(lower_counterpart, 6)

        distance_ratio = (odds - lower_odds) / (higher_odds - lower_odds)
        interpolated_odds = lower_counterpart + (distance_ratio * (higher_counterpart - lower_counterpart))

        return round(interpolated_odds, 6)

    def _estimate_paired_odds_from_average_vig(self, odds, odds_pairs):
        average_vig = self._get_average_vig(odds_pairs)
        denominator = 1 + average_vig - (1 / odds)

        if denominator <= 0:
            return 0.0

        return round(1 / denominator, 6)

    def _get_average_vig(self, odds_pairs):
        vigs = [
            (1 / team_1_odds) + (1 / team_2_odds) - 1
            for team_1_odds, team_2_odds in odds_pairs
        ]

        if not vigs:
            return 0.0

        return sum(vigs) / len(vigs)

if __name__ == "__main__":
    bookkeeper = Bookkeeper()
    bookkeeper.show_odds_distribution()
