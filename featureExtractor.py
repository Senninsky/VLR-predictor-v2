# Importations
import random

import pandas as pd

from bookkeeper import Bookkeeper
from dbManager import DbManager
from featureBuilder import FeatureBuilder


# DataExtractor
class DataExtractor:
    def __init__(self):
        self.dbManager = DbManager()
        self.bookkeeper = Bookkeeper()

    def generate_trainingset_1(self):
        matches = self._sort_matches_by_date_time(self.dbManager.get_matches())
        featureBuilder = FeatureBuilder()
        pending_updates = []
        current_date_time = None
        rows = []

        for match in matches:
            match_date_time = self._get_match_date_time(match)

            if current_date_time is None:
                current_date_time = match_date_time

            if match_date_time != current_date_time:
                self._apply_pending_updates(featureBuilder, pending_updates)
                pending_updates = []
                current_date_time = match_date_time

            rows.append(self._create_training_row(featureBuilder, match, match_date_time))
            pending_updates.append(featureBuilder.state.create_match_update(match, match_date_time))

        self._apply_pending_updates(featureBuilder, pending_updates)

        return pd.DataFrame(rows)

    def build_feature_builder_from_database(self):
        featureBuilder = FeatureBuilder()
        featureBuilder.fit_matches(self.dbManager.get_matches(), self._get_match_date_time)
        return featureBuilder

    def _create_training_row(self, featureBuilder, match, match_date_time):
        team_1_player_ids = self._get_player_ids(match.team_1.players)
        team_2_player_ids = self._get_player_ids(match.team_2.players)
        team_1_odds, team_2_odds = self._get_completed_match_odds(match)
        row = featureBuilder.build_match_features(team_1_player_ids, team_2_player_ids, match_date_time)

        row.update({
            "match_id": match.id,
            "date_time": match_date_time.strftime("%Y-%m-%d %H:%M"),
            "team_1_score": match.team_1.score,
            "team_2_score": match.team_2.score,
            "team_1_odds": team_1_odds,
            "team_2_odds": team_2_odds,
            "team_1_player_ids": team_1_player_ids,
            "team_2_player_ids": team_2_player_ids,
            "team_1_player_10_average_ratings": row["team_1_player_10_average_ratings"],
            "team_2_player_10_average_ratings": row["team_2_player_10_average_ratings"],
            "team_1_10_average_ratings": row["team_1_10_average_ratings"],
            "team_2_10_average_ratings": row["team_2_10_average_ratings"],
        })

        return row

    def _get_completed_match_odds(self, match):
        if match.team_1.score == match.team_2.score or not match.odds:
            return 0.0, 0.0

        winner_odds = self._get_random_winner_odds(match.odds)

        if winner_odds <= 0:
            return 0.0, 0.0

        loser_odds = self.bookkeeper.get_paired_odds(winner_odds)

        if match.team_1.score > match.team_2.score:
            return winner_odds, loser_odds

        return loser_odds, winner_odds

    def _get_random_winner_odds(self, odds):
        clean_odds = []

        for odd in odds:
            try:
                odd = round(float(odd), 6)
            except (TypeError, ValueError):
                continue

            if odd > 0:
                clean_odds.append(odd)

        if not clean_odds:
            return 0.0

        return random.choice(clean_odds)

    def _apply_pending_updates(self, featureBuilder, pending_updates):
        for update in pending_updates:
            featureBuilder.state.apply_update(update)

    def _sort_matches_by_date_time(self, matches):
        return sorted(matches, key=self._get_match_date_time)

    def _get_match_date_time(self, match):
        return self._get_date_time_key(match.date, match.hour)

    def _get_date_time_key(self, date, hour):
        return pd.to_datetime(date + " " + hour, dayfirst=True, format="mixed").to_pydatetime()

    def _get_player_ids(self, team_players):
        player_ids = []

        for team_player in team_players:
            player_ids.append(str(team_player.player.id))

        return player_ids

    def count_matches_with_empty_team_rating_history(self, dataFrame):
        amount = 0

        for index, match in dataFrame.iterrows():
            if self._all_values_are_zero(match["team_1_player_10_average_ratings"]) or self._all_values_are_zero(match["team_2_player_10_average_ratings"]):
                amount += 1

        return amount

    def _all_values_are_zero(self, values):
        for value in values:
            if value != 0.0:
                return False

        return True


if __name__ == "__main__":
    dataExtractor = DataExtractor()
    dataFrame = dataExtractor.generate_trainingset_1()
    print("Matches with at least 1 team having all 0 player rating histories: " + str(dataExtractor.count_matches_with_empty_team_rating_history(dataFrame)))
    print(dataFrame[["team_1_score", "team_1_player_10_average_ratings", "team_1_10_average_ratings", "team_1_mean_hist_n", "team_1_pair_winrate_mean"]].sample(10))
    dataFrame.to_pickle("dataset_1.pkl")
