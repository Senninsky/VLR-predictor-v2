# Importations
import joblib
import lightgbm as lgb
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
        x_train, y_train = self._split_features_and_target(self.training_set)
        x_test, y_test = self._split_features_and_target(self.test_set)

        self.model = lgb.LGBMClassifier(random_state=42)
        self.model.fit(x_train, y_train)

        predictions = self.model.predict(x_test)
        accuracy = (predictions == y_test).mean()
        print("Test accuracy: " + str(round(accuracy, 3)))

        return self.model

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

        x_validation = self._extract_features(self.validation_set)
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
        x = self._extract_features(dataset)
        y = dataset.apply(lambda row: 1 if row["team_1_score"] > row["team_2_score"] else 0, axis=1)

        return x, y

    def _extract_features(self, dataset):
        rows = []

        for index, match in dataset.iterrows():
            row = {
                "team_1_odds": match["team_1_odds"],
                "team_2_odds": match["team_2_odds"],
            }

            for i, rating in enumerate(match["team_1_player_10_average_ratings"]):
                row["team_1_player_" + str(i + 1) + "_10_average_rating"] = rating

            for i, rating in enumerate(match["team_2_player_10_average_ratings"]):
                row["team_2_player_" + str(i + 1) + "_10_average_rating"] = rating

            rows.append(row)

        return pd.DataFrame(rows)

if __name__ == "__main__":
    trainer = ModelTrainer("dataset_1.pkl")
    trainer.train()
    trainer.bet()
    trainer.save_model()
