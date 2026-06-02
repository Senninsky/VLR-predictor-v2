# Importations
import pandas as pd

from dbManager import DbManager

# DataExtractor
class DataExtractor:
    def __init__(self):
        self.dbManager = DbManager()

    def generate_trainingset_1(self):
        matches = self._sort_matches_by_date_time(self.dbManager.get_matches())
        player_rating_histories = {}
        pending_player_ratings = []
        current_date_time = None
        rows = []

        for match in matches:
            match_date_time = self._get_match_date_time(match)

            if current_date_time is None:
                current_date_time = match_date_time

            if match_date_time != current_date_time:
                self._add_pending_player_ratings(player_rating_histories, pending_player_ratings)
                pending_player_ratings = []
                current_date_time = match_date_time

            team_1_player_10_average_ratings = self._get_player_10_average_ratings(match.team_1.players, player_rating_histories)
            team_2_player_10_average_ratings = self._get_player_10_average_ratings(match.team_2.players, player_rating_histories)
            team_1_odds, team_2_odds = self._get_match_odds(match)

            rows.append(self._create_training_row(match, team_1_odds, team_2_odds, team_1_player_10_average_ratings, team_2_player_10_average_ratings))
            self._collect_team_player_ratings(match.team_1.players, pending_player_ratings)
            self._collect_team_player_ratings(match.team_2.players, pending_player_ratings)

        self._add_pending_player_ratings(player_rating_histories, pending_player_ratings)

        return pd.DataFrame(rows)

    def _sort_matches_by_date_time(self, matches):
        return sorted(matches, key=self._get_match_date_time)

    def _get_match_date_time(self, match):
        return self._get_date_time_key(match.date, match.hour)

    def _get_date_time_key(self, date, hour):
        return date[6:10] + "-" + date[3:5] + "-" + date[0:2] + " " + hour

    def _get_match_odds(self, match):
        team_1_odds = 0.0
        team_2_odds = 0.0

        if match.odds and 1.0 not in match.odds:
            average_odds = sum(match.odds) / len(match.odds)

            if match.team_1.score > match.team_2.score:
                team_1_odds = average_odds
            elif match.team_2.score > match.team_1.score:
                team_2_odds = average_odds

        return team_1_odds, team_2_odds

    def _create_training_row(self, match, team_1_odds, team_2_odds, team_1_player_10_average_ratings, team_2_player_10_average_ratings):
        return {
            "match_id": match.id,
            "date_time": match.date + " " + match.hour,
            "team_1_score": match.team_1.score,
            "team_2_score": match.team_2.score,
            "team_1_odds": team_1_odds,
            "team_2_odds": team_2_odds,
            "team_1_player_ids": self._get_player_ids(match.team_1.players),
            "team_2_player_ids": self._get_player_ids(match.team_2.players),
            "team_1_player_10_average_ratings": team_1_player_10_average_ratings,
            "team_2_player_10_average_ratings": team_2_player_10_average_ratings,
            "team_1_10_average_ratings": self._average(team_1_player_10_average_ratings),
            "team_2_10_average_ratings": self._average(team_2_player_10_average_ratings),
        }

    def _get_player_ids(self, team_players):
        player_ids = []

        for team_player in team_players:
            player_ids.append(team_player.player.id)

        return player_ids

    def _get_player_10_average_ratings(self, team_players, player_rating_histories):
        player_average_ratings = []

        for team_player in team_players:
            player_id = team_player.player.id
            player_ratings = player_rating_histories.get(player_id, [])[-10:]
            player_average_ratings.append(self._average(player_ratings))

        return player_average_ratings

    def _collect_team_player_ratings(self, team_players, pending_player_ratings):
        for team_player in team_players:
            rating = self._get_player_rating(team_player)

            if rating is not None:
                pending_player_ratings.append((team_player.player.id, rating))

    def _add_pending_player_ratings(self, player_rating_histories, pending_player_ratings):
        for player_id, rating in pending_player_ratings:
            self._add_player_rating(player_rating_histories, player_id, rating)

    def _add_player_rating(self, player_rating_histories, player_id, rating):
        if player_id not in player_rating_histories:
            player_rating_histories[player_id] = []

        player_rating_histories[player_id].append(rating)

    def _get_player_rating(self, team_player):
        try:
            return float(team_player.performance.r)
        except (TypeError, ValueError):
            return None

    def _average(self, values):
        values = [value for value in values if value != 0.0]

        if not values:
            return 0.0

        return round(sum(values) / len(values), 3)

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
    print(dataFrame[["team_1_score", "team_2_score", "team_1_odds", "team_2_odds", "team_1_player_10_average_ratings", "team_2_player_10_average_ratings", "team_1_10_average_ratings", "team_1_10_average_ratings"]].head())
    dataFrame.to_pickle("dataset_1.pkl")
