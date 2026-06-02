# Importations
import joblib
import lightgbm as lgb
import pandas as pd


# StackedModelTrainer
class StackedModelTrainer:
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
        self.feature_groups = self._get_feature_groups()
        self.feature_models = {}
        self.model = None

    def train(self):
        self._train_feature_models()
        self._train_stacked_model()
        self._print_test_accuracy()

        return self.model

    def save_model(self, model_path="stacked_model.pkl"):
        if self.model is None:
            self.train()

        joblib.dump({
            "feature_models": self.feature_models,
            "model": self.model,
            "feature_groups": self.feature_groups,
        }, model_path)
        print("Stacked model saved to: " + model_path)

    def _train_feature_models(self):
        for feature_name in self.feature_groups:
            x_train = self._extract_feature_group(self.training_set, feature_name)
            y_train = self._extract_target(self.training_set)

            model = lgb.LGBMClassifier(random_state=42)
            model.fit(x_train, y_train)
            self.feature_models[feature_name] = model

            print("Trained feature model: " + feature_name)

    def _train_stacked_model(self):
        x_validation = self._extract_stacked_features(self.validation_set)
        y_validation = self._extract_target(self.validation_set)

        self.model = lgb.LGBMClassifier(random_state=42)
        self.model.fit(x_validation, y_validation)

    def _print_test_accuracy(self):
        x_test = self._extract_stacked_features(self.test_set)
        y_test = self._extract_target(self.test_set)

        predictions = self.model.predict(x_test)
        accuracy = (predictions == y_test).mean()
        print("Stacked test accuracy: " + str(round(accuracy, 3)))

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
            filtered_dataset["team_1_player_10_average_ratings"].apply(self._has_5_non_zero_values) &
            filtered_dataset["team_2_player_10_average_ratings"].apply(self._has_5_non_zero_values)
        ]

        return filtered_dataset

    def _has_5_non_zero_values(self, values):
        return len(values) == 5 and 0.0 not in values

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
        bookmaker_vig = 1.09
        known_probability = 1 / odds
        opponent_probability = bookmaker_vig - known_probability

        if opponent_probability <= 0:
            return 0.0

        return round(1 / opponent_probability, 3)

    def _get_feature_groups(self):
        feature_groups = ["odds", "player_10_average_ratings"]

        if self._has_columns(["team_1_player_10_average_interval", "team_2_player_10_average_interval"]):
            feature_groups.append("player_10_average_interval")

        if self._has_columns(["team_1_player_10_match_win_percentage", "team_2_player_10_match_win_percentage"]):
            feature_groups.append("player_10_match_win_percentage")

        return feature_groups

    def _has_columns(self, columns):
        for column in columns:
            if column not in self.dataset.columns:
                return False

        return True

    def _extract_feature_group(self, dataset, feature_name):
        if feature_name == "odds":
            return self._extract_odds_features(dataset)

        return self._extract_player_list_features(dataset, feature_name)

    def _extract_odds_features(self, dataset):
        rows = []

        for index, match in dataset.iterrows():
            rows.append({
                "team_1_odds": match["team_1_odds"],
                "team_2_odds": match["team_2_odds"],
            })

        return pd.DataFrame(rows)

    def _extract_player_list_features(self, dataset, feature_name):
        rows = []

        for index, match in dataset.iterrows():
            row = {}
            team_1_values = match["team_1_" + feature_name]
            team_2_values = match["team_2_" + feature_name]

            self._add_player_values(row, "team_1", feature_name, team_1_values)
            self._add_player_values(row, "team_2", feature_name, team_2_values)
            rows.append(row)

        return pd.DataFrame(rows)

    def _add_player_values(self, row, team, feature_name, values):
        for i, value in enumerate(values[:5]):
            row[team + "_player_" + str(i + 1) + "_" + feature_name] = value

        for i in range(len(values), 5):
            row[team + "_player_" + str(i + 1) + "_" + feature_name] = 0.0

    def _extract_stacked_features(self, dataset):
        rows = []

        for feature_name in self.feature_groups:
            probabilities = self._predict_feature_model(dataset, feature_name)
            self._add_feature_model_predictions(rows, feature_name, probabilities)

        return pd.DataFrame(rows)

    def _predict_feature_model(self, dataset, feature_name):
        x = self._extract_feature_group(dataset, feature_name)
        return self.feature_models[feature_name].predict_proba(x)

    def _add_feature_model_predictions(self, rows, feature_name, probabilities):
        for i, probability in enumerate(probabilities):
            if len(rows) <= i:
                rows.append({})

            rows[i][feature_name + "_team_1_win_probability"] = probability[1]
            rows[i][feature_name + "_team_2_win_probability"] = probability[0]

    def _extract_target(self, dataset):
        return dataset.apply(lambda row: 1 if row["team_1_score"] > row["team_2_score"] else 0, axis=1)


if __name__ == "__main__":
    trainer = StackedModelTrainer("dataset_1.pkl")
    trainer.train()
    trainer.save_model()
