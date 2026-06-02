# Importations
import time
from itertools import permutations

import joblib
import lightgbm as lgb
import numpy as np
import pandas as pd


# ModelTrainer
class ModelTrainer:
    def __init__(self, dataset_path):
        self.dataset = pd.read_pickle(dataset_path)
        print("Dataset size before filtering: " + str(len(self.dataset)))
        self.dataset = self._filter_dataset()
        print("Dataset size after filtering: " + str(len(self.dataset)))
        self.dataset = self._add_opponent_odds()
        self.dataset = self._sort_dataset_by_date_time()

        self.training_set = self._extract_training_set()
        self.validation_set = self._extract_validation_set()
        self.test_set = self._extract_test_set()
        self.model = None

    def train(self):
        x_train, y_train = self._extract_augmented_features_and_target(self.training_set)
        x_test, y_test = self._split_features_and_target(self.test_set)

        self.model = lgb.LGBMClassifier(random_state=42, force_row_wise=True)
        self.model.fit(x_train, y_train)

        predictions = self.model.predict(x_test)
        accuracy = (predictions == y_test).mean()
        print("Test accuracy: " + str(round(accuracy, 3)))

        return self.model

    def _extract_augmented_features_and_target(self, training_set):
        player_permutations = self._get_player_permutations()
        team_1_permutations = np.repeat(player_permutations, len(player_permutations), axis=0)
        team_2_permutations = np.tile(player_permutations, (len(player_permutations), 1))
        rows_per_match = len(team_1_permutations) * 2
        total_rows = len(training_set) * rows_per_match
        feature_amount = len(self._extract_features(training_set.iloc[:1]).columns)
        estimated_gb = (total_rows * feature_amount * 4) / (1024 ** 3)
        last_status_update = time.time()

        print("Training set size before augmentation: " + str(len(training_set)))
        print("Expected training set size after augmentation: " + str(total_rows))
        print("Estimated feature matrix memory: " + str(round(estimated_gb, 3)) + " GB")

        x = np.empty((total_rows, feature_amount), dtype=np.float32)
        y = np.empty(total_rows, dtype=np.int8)

        for match_number, (index, match) in enumerate(training_set.iterrows(), start=1):
            start_index = (match_number - 1) * rows_per_match
            middle_index = start_index + len(team_1_permutations)
            end_index = start_index + rows_per_match

            team_1_player_features = self._get_permuted_player_features(match, "team_1", team_1_permutations)
            team_2_player_features = self._get_permuted_player_features(match, "team_2", team_2_permutations)

            self._add_augmented_rows(x, start_index, middle_index, match, team_1_player_features, team_2_player_features, False)
            self._add_augmented_rows(x, middle_index, end_index, match, team_2_player_features, team_1_player_features, True)
            self._add_augmented_targets(y, start_index, middle_index, end_index, match)

            last_status_update = self._print_augmentation_progress(match_number, len(training_set), end_index, total_rows, last_status_update)

        print("Training set size after augmentation: " + str(len(x)))

        return x, y

    def _print_augmentation_progress(self, match_number, total_matches, generated_rows, total_rows, last_status_update):
        now = time.time()

        if now - last_status_update < 5:
            return last_status_update

        progress = generated_rows / total_rows
        print(
            "Augmentation progress: " +
            str(round(progress * 100, 2)) + "% " +
            "(" + str(match_number) + "/" + str(total_matches) + " matches, " +
            str(generated_rows) + "/" + str(total_rows) + " rows)"
        )

        return now

    def _get_player_permutations(self):
        return np.array(list(permutations(range(5))), dtype=np.intp)

    def _get_permuted_player_features(self, match, team, team_permutations):
        player_features = np.array([
            match[team + "_player_10_average_ratings"],
            match[team + "_player_10_average_interval"],
            match[team + "_player_10_match_win_percentage"],
        ], dtype=np.float32)

        return player_features[:, team_permutations].transpose(1, 0, 2).reshape(len(team_permutations), 15)

    def _add_augmented_rows(self, x, start_index, end_index, match, team_1_player_features, team_2_player_features, swapped):
        if swapped:
            self._add_team_level_features(x, start_index, end_index, match, "team_2", "team_1")
        else:
            self._add_team_level_features(x, start_index, end_index, match, "team_1", "team_2")

        self._add_player_features(x, start_index, end_index, team_1_player_features, team_2_player_features)

    def _add_team_level_features(self, x, start_index, end_index, match, team_1, team_2):
        x[start_index:end_index, 0] = match[team_1 + "_odds"]
        x[start_index:end_index, 1] = match[team_2 + "_odds"]
        x[start_index:end_index, 2] = match[team_1 + "_10_average_ratings"]
        x[start_index:end_index, 3] = match[team_2 + "_10_average_ratings"]

    def _add_player_features(self, x, start_index, end_index, team_1_player_features, team_2_player_features):
        x[start_index:end_index, 4:9] = team_1_player_features[:, 0:5]
        x[start_index:end_index, 9:14] = team_2_player_features[:, 0:5]
        x[start_index:end_index, 14:19] = team_1_player_features[:, 5:10]
        x[start_index:end_index, 19:24] = team_2_player_features[:, 5:10]
        x[start_index:end_index, 24:29] = team_1_player_features[:, 10:15]
        x[start_index:end_index, 29:34] = team_2_player_features[:, 10:15]

    def _add_augmented_targets(self, y, start_index, middle_index, end_index, match):
        target = self._get_target(match)
        y[start_index:middle_index] = target
        y[middle_index:end_index] = 1 - target

    def save_model(self, model_path="model.pkl"):
        if self.model is None:
            self.train()

        joblib.dump(self.model, model_path)
        print("Model saved to: " + model_path)

    def save_mode(self, model_path="model.pkl"):
        self.save_model(model_path)

    def bet(self):
        if self.model is None:
            self.train()

        x_validation = self._extract_features(self.validation_set).to_numpy(dtype=np.float32)
        probabilities = self.model.predict_proba(x_validation)

        stake = 1.0
        total_bets = 0
        profit = 0.0

        for i, match in self.validation_set.reset_index(drop=True).iterrows():
            team_1_win_probability = probabilities[i][1]
            team_2_win_probability = probabilities[i][0]

            team_1_won = match["team_1_score"] > match["team_2_score"]
            team_2_won = match["team_2_score"] > match["team_1_score"]

            team_1_bet = self._should_bet(team_1_win_probability, match["team_1_odds"])
            team_2_bet = self._should_bet(team_2_win_probability, match["team_2_odds"])

            if team_1_bet:
                total_bets += 1
                if team_1_won:
                    profit += (match["team_1_odds"] - 1) * stake
                else:
                    profit -= stake

            if team_2_bet:
                total_bets += 1
                if team_2_won:
                    profit += (match["team_2_odds"] - 1) * stake
                else:
                    profit -= stake

        print("Validation bets: " + str(total_bets))
        print("Validation profit: " + str(round(profit, 3)))

        if total_bets > 0:
            roi = profit / total_bets
            print("Validation ROI: " + str(round(roi, 3)))

        return profit

    def _extract_training_set(self):
        training_end = int(len(self.dataset) * 0.7)
        return self.dataset.iloc[:training_end]

    def _extract_validation_set(self):
        training_end = int(len(self.dataset) * 0.7)
        validation_end = int(len(self.dataset) * 0.85)
        return self.dataset.iloc[training_end:validation_end]

    def _extract_test_set(self):
        validation_end = int(len(self.dataset) * 0.85)
        return self.dataset.iloc[validation_end:]
    
    def _sort_dataset_by_date_time(self):
        dataset = self.dataset.copy()
        dataset["date_time_sort"] = pd.to_datetime(dataset["date_time"], dayfirst=True, format="mixed")
        dataset = dataset.sort_values("date_time_sort")
        dataset = dataset.drop(columns=["date_time_sort"])
        return dataset.reset_index(drop=True)

    def _filter_dataset(self):
        filtered_dataset = self.dataset.copy()

        filtered_dataset = filtered_dataset[
            filtered_dataset["team_1_score"] != filtered_dataset["team_2_score"]
        ]

        filtered_dataset = filtered_dataset[
            (filtered_dataset["team_1_odds"] != 0.0) |
            (filtered_dataset["team_2_odds"] != 0.0)
        ]

        filtered_dataset = filtered_dataset[
            (filtered_dataset["team_1_odds"] != 1.0) &
            (filtered_dataset["team_2_odds"] != 1.0)
        ]

        filtered_dataset = filtered_dataset[
            filtered_dataset["team_1_player_10_average_ratings"].apply(self._has_5_non_zero_player_ratings) &
            filtered_dataset["team_2_player_10_average_ratings"].apply(self._has_5_non_zero_player_ratings)
        ]

        return filtered_dataset
    
    def _has_5_non_zero_player_ratings(self, ratings):
        return len(ratings) == 5 and 0.0 not in ratings

    def _add_opponent_odds(self):
        dataset = self.dataset.copy()

        for index, match in dataset.iterrows():
            team_1_odds = match["team_1_odds"]
            team_2_odds = match["team_2_odds"]

            if team_1_odds != 0.0 and team_2_odds == 0.0:
                dataset.at[index, "team_2_odds"] = self._calculate_opponent_odds(team_1_odds)

            if team_2_odds != 0.0 and team_1_odds == 0.0:
                dataset.at[index, "team_1_odds"] = self._calculate_opponent_odds(team_2_odds)

        return dataset

    def _calculate_opponent_odds(self, odds):
        bookmaker_vig = 1.08
        known_probability = 1 / odds
        opponent_probability = bookmaker_vig - known_probability

        if opponent_probability <= 0:
            return 0.0

        return round(1 / opponent_probability, 3)

    def _should_bet(self, win_probability, odds):
        implied_probability = 1 / odds
        edge = win_probability - implied_probability
        ev = win_probability * odds - 1

        return win_probability > 0.55 and edge > 0.08 and ev > 0

    def _split_features_and_target(self, dataset):
        x = self._extract_features(dataset).to_numpy(dtype=np.float32)
        y = dataset.apply(self._get_target, axis=1).to_numpy(dtype=np.int8)

        return x, y

    def _get_target(self, match):
        if match["team_1_score"] > match["team_2_score"]:
            return 1

        return 0

    def _extract_features(self, dataset):
        rows = []

        for index, match in dataset.iterrows():
            row = {
                "team_1_odds": match["team_1_odds"],
                "team_2_odds": match["team_2_odds"],
                "team_1_10_average_ratings": match["team_1_10_average_ratings"],
                "team_2_10_average_ratings": match["team_2_10_average_ratings"],
            }

            self._add_player_feature(row, "team_1", "10_average_rating", match["team_1_player_10_average_ratings"])
            self._add_player_feature(row, "team_2", "10_average_rating", match["team_2_player_10_average_ratings"])
            self._add_player_feature(row, "team_1", "10_average_interval", match["team_1_player_10_average_interval"])
            self._add_player_feature(row, "team_2", "10_average_interval", match["team_2_player_10_average_interval"])
            self._add_player_feature(row, "team_1", "10_match_win_percentage", match["team_1_player_10_match_win_percentage"])
            self._add_player_feature(row, "team_2", "10_match_win_percentage", match["team_2_player_10_match_win_percentage"])

            rows.append(row)

        return pd.DataFrame(rows)

    def _add_player_feature(self, row, team, feature_name, values):
        for i, value in enumerate(values):
            row[team + "_player_" + str(i + 1) + "_" + feature_name] = value

if __name__ == "__main__":
    trainer = ModelTrainer("dataset_1.pkl")
    trainer.train()
    trainer.bet()
    trainer.save_model()
