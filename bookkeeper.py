import json
from pathlib import Path


class Bookkeeper:
    def __init__(self, odds_pairs_path="bookkeeper_odds_pairs.json"):
        self.odds_pairs_path = Path(odds_pairs_path)

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

if __name__ == "__main__":
    bookkeeper = Bookkeeper()
    bookkeeper.show_odds_distribution()
