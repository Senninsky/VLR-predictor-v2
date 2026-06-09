# Importations
import joblib
import lightgbm as lgb
import numpy as np
import pandas as pd
from sklearn.linear_model import LogisticRegression
from sklearn.metrics import accuracy_score
from sklearn.metrics import brier_score_loss
from sklearn.metrics import log_loss
from sklearn.metrics import roc_auc_score
from sklearn.pipeline import make_pipeline
from sklearn.preprocessing import StandardScaler


# CalibratedModel
class CalibratedModel:
    def __init__(self, base_model, calibrator=None):
        self.base_model = base_model
        self.calibrator = calibrator

    def predict(self, x):
        probabilities = self.predict_proba(x)
        return (probabilities[:, 1] >= 0.5).astype(int)

    def predict_proba(self, x):
        probabilities = self.base_model.predict_proba(x)

        if self.calibrator is None:
            return probabilities

        calibrated_probability = self.calibrator.predict_proba(probabilities[:, 1].reshape(-1, 1))[:, 1]
        return np.column_stack((1 - calibrated_probability, calibrated_probability))


# ModelTrainer
class ModelTrainer:
    def __init__(self, dataset_path):
        self.dataset = pd.read_pickle(dataset_path)
        print("Dataset size before filtering: " + str(len(self.dataset)))
        self.dataset = self._filter_dataset()
        print("Dataset size after filtering: " + str(len(self.dataset)))
        self.dataset = self._sort_dataset_by_date_time()
        self.feature_columns = self._get_feature_columns(self.dataset)
        print("Feature amount: " + str(len(self.feature_columns)))

        self.training_set = self._extract_training_set()
        self.validation_set = self._extract_validation_set()
        self.test_set = self._extract_test_set()
        self.model = None

    def train(self):
        self._print_baselines()
        self._walk_forward_validate()

        x_train, y_train = self._split_features_and_target(self.training_set)
        x_validation, y_validation = self._split_features_and_target(self.validation_set)
        x_test, y_test = self._split_features_and_target(self.test_set)

        base_model = self._create_model()
        base_model.fit(x_train, y_train)
        self.model = self._calibrate_model(base_model, x_validation, y_validation)
        self._print_model_metrics("Final holdout", self.model, x_test, y_test)

        return self.model

    def save_model(self, model_path="model.pkl"):
        if self.model is None:
            self.train()

        joblib.dump({
            "base_model": self.model.base_model,
            "calibrator": self.model.calibrator,
            "feature_columns": self.feature_columns,
        }, model_path)
        print("Model saved to: " + model_path)

    def save_mode(self, model_path="model.pkl"):
        self.save_model(model_path)

    def bet(self):
        print("Historical betting backtest skipped: stored result-page odds are winner-side leaked and are not used for model validation.")
        return 0.0

    def _create_model(self):
        return lgb.LGBMClassifier(
            random_state=42,
            force_row_wise=True,
            n_estimators=400,
            learning_rate=0.04,
            num_leaves=31,
            min_child_samples=20,
            subsample=0.9,
            colsample_bytree=0.9,
            verbose=-1,
        )

    def _calibrate_model(self, base_model, x_validation, y_validation):
        if len(set(y_validation)) < 2:
            print("Calibration skipped: validation set has only one class.")
            return CalibratedModel(base_model)

        validation_probabilities = base_model.predict_proba(x_validation)[:, 1].reshape(-1, 1)
        calibrator = LogisticRegression(random_state=42)
        calibrator.fit(validation_probabilities, y_validation)
        print("Probability calibration fitted on validation set.")

        return CalibratedModel(base_model, calibrator)

    def _print_baselines(self):
        x_train, y_train = self._split_features_and_target(self.training_set)
        x_test, y_test = self._split_features_and_target(self.test_set)

        if len(y_train) == 0 or len(y_test) == 0:
            print("Baselines skipped: not enough data after filtering.")
            return

        self._print_majority_baseline(y_train, y_test)
        self._print_logistic_baseline("Logistic baseline", x_train, y_train, x_test, y_test, self.feature_columns)
        self._print_logistic_baseline("Elo-only logistic baseline", x_train, y_train, x_test, y_test, self._get_elo_feature_columns())

    def _print_majority_baseline(self, y_train, y_test):
        probability = min(max(float(np.mean(y_train)), 0.001), 0.999)
        probabilities = np.column_stack((
            np.full(len(y_test), 1 - probability),
            np.full(len(y_test), probability),
        ))

        self._print_metrics("Majority baseline", probabilities, y_test)

    def _print_logistic_baseline(self, title, x_train, y_train, x_test, y_test, feature_columns):
        if not feature_columns:
            print(title + " skipped: no matching features.")
            return

        if len(set(y_train)) < 2:
            print(title + " skipped: training set has only one class.")
            return

        model = make_pipeline(
            StandardScaler(),
            LogisticRegression(max_iter=2000, random_state=42),
        )
        model.fit(x_train[feature_columns], y_train)
        probabilities = model.predict_proba(x_test[feature_columns])
        self._print_metrics(title, probabilities, y_test)

    def _walk_forward_validate(self, fold_count=4):
        unique_date_times = list(self.dataset["date_time"].drop_duplicates())

        if len(unique_date_times) < fold_count + 2:
            print("Walk-forward CV skipped: not enough unique timestamps.")
            return

        block_size = max(int(len(unique_date_times) / (fold_count + 1)), 1)
        fold_metrics = []

        for fold in range(1, fold_count + 1):
            training_dates = unique_date_times[:fold * block_size]
            validation_dates = unique_date_times[fold * block_size:(fold + 1) * block_size]

            if not validation_dates:
                continue

            training_set = self.dataset[self.dataset["date_time"].isin(training_dates)]
            validation_set = self.dataset[self.dataset["date_time"].isin(validation_dates)]

            if len(training_set) == 0 or len(validation_set) == 0:
                continue

            x_train, y_train = self._split_features_and_target(training_set)
            x_validation, y_validation = self._split_features_and_target(validation_set)

            if len(set(y_train)) < 2 or len(set(y_validation)) < 2:
                continue

            model = self._create_model()
            model.fit(x_train, y_train)
            probabilities = model.predict_proba(x_validation)
            metrics = self._calculate_metrics(probabilities, y_validation)
            fold_metrics.append(metrics)

            print(
                "Walk-forward fold " + str(fold) +
                ": log_loss=" + str(round(metrics["log_loss"], 3)) +
                ", brier=" + str(round(metrics["brier"], 3)) +
                ", accuracy=" + str(round(metrics["accuracy"], 3))
            )

        if fold_metrics:
            print(
                "Walk-forward average: log_loss=" + str(round(self._average_metric(fold_metrics, "log_loss"), 3)) +
                ", brier=" + str(round(self._average_metric(fold_metrics, "brier"), 3)) +
                ", accuracy=" + str(round(self._average_metric(fold_metrics, "accuracy"), 3))
            )

    def _print_model_metrics(self, title, model, x, y):
        probabilities = model.predict_proba(x)
        self._print_metrics(title, probabilities, y)

    def _print_metrics(self, title, probabilities, y):
        metrics = self._calculate_metrics(probabilities, y)
        message = (
            title +
            ": log_loss=" + str(round(metrics["log_loss"], 3)) +
            ", brier=" + str(round(metrics["brier"], 3)) +
            ", accuracy=" + str(round(metrics["accuracy"], 3))
        )

        if metrics["roc_auc"] is not None:
            message += ", roc_auc=" + str(round(metrics["roc_auc"], 3))

        print(message)

    def _calculate_metrics(self, probabilities, y):
        y_probability = probabilities[:, 1]
        y_prediction = (y_probability >= 0.5).astype(int)
        metrics = {
            "log_loss": log_loss(y, probabilities, labels=[0, 1]),
            "brier": brier_score_loss(y, y_probability),
            "accuracy": accuracy_score(y, y_prediction),
            "roc_auc": None,
        }

        if len(set(y)) == 2:
            metrics["roc_auc"] = roc_auc_score(y, y_probability)

        return metrics

    def _average_metric(self, metrics, name):
        return sum(metric[name] for metric in metrics) / len(metrics)

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
            (filtered_dataset["team_1_player_amount"] == 5) &
            (filtered_dataset["team_2_player_amount"] == 5) &
            (filtered_dataset["team_1_unique_player_amount"] == 5) &
            (filtered_dataset["team_2_unique_player_amount"] == 5)
        ]

        return filtered_dataset.reset_index(drop=True)

    def _split_features_and_target(self, dataset):
        x = self._extract_features(dataset)
        y = dataset.apply(self._get_target, axis=1).to_numpy(dtype=np.int8)

        return x, y

    def _get_target(self, match):
        if match["team_1_score"] > match["team_2_score"]:
            return 1

        return 0

    def _extract_features(self, dataset):
        features = dataset.reindex(columns=self.feature_columns, fill_value=0.0).copy()
        features = features.replace([np.inf, -np.inf], 0.0)
        features = features.fillna(0.0)

        return features

    def _get_feature_columns(self, dataset):
        excluded_columns = {
            "match_id",
            "date_time",
            "team_1_score",
            "team_2_score",
            "team_1_odds",
            "team_2_odds",
            "team_1_player_ids",
            "team_2_player_ids",
            "team_1_player_10_average_ratings",
            "team_2_player_10_average_ratings",
            "team_1_player_history_counts",
            "team_2_player_history_counts",
        }
        feature_columns = []

        for column in dataset.columns:
            if column in excluded_columns:
                continue

            if pd.api.types.is_numeric_dtype(dataset[column]):
                feature_columns.append(column)

        return feature_columns

    def _get_elo_feature_columns(self):
        return [
            feature_column
            for feature_column in self.feature_columns
            if "elo" in feature_column
        ]


if __name__ == "__main__":
    trainer = ModelTrainer("dataset_1.pkl")
    trainer.train()
    trainer.bet()
    trainer.save_model()
