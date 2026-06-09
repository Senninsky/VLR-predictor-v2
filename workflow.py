# Importations
from datetime import datetime
from datetime import timedelta
from zoneinfo import ZoneInfo

from dbManager import DbManager
from featureExtractor import DataExtractor
from modelTrainer import ModelTrainer
from upcomingPredictor import UpcomingPredictor
from upcomingPredictor import notification
from vlrScraper import VlrScraper


# Workflow
class Workflow:
    def __init__(self):
        self.dataset_path = "dataset_1.pkl"
        self.model_path = "model.pkl"
        self.scrape_amount = 100
        self.timezone = "Europe/Brussels"

    def run(self):
        added_matches = self._refill_database()

        if added_matches:
            self._extract_features()
            self._train_model()
        else:
            print("No new matches added to database. Skipping feature extraction and model training.")

        predicted_upcoming_matches = self._predict_upcoming_matches()
        self._notify_done(predicted_upcoming_matches)

    def _refill_database(self):
        scraper = VlrScraper()
        dbManager = DbManager()

        print("Amount of total matches in database: " + str(dbManager.get_match_amount()))
        print("Amount of total matches that have at least 1 odd available: " + str(dbManager.get_match_with_odds_amount()))

        match_links = scraper.scrape_last_match_links(self.scrape_amount)
        amount = len(match_links)
        last_matches = []

        if amount == 0:
            print("No new matches found to add to database.")
            return False

        for i, match_link in enumerate(match_links):
            match = scraper.convert_match_link_to_match_object(match_link)
            dbManager.insert_match(match)

            print(str(i + 1) + "/" + str(amount) + ": " + str(match) + "\n")
            last_matches.append(match)

        dbManager.rescrape_missing_player_stats()
        return True

    def _extract_features(self):
        dataExtractor = DataExtractor()
        dataFrame = dataExtractor.generate_trainingset_1()

        print("Matches with at least 1 team having all 0 player rating histories: " + str(dataExtractor.count_matches_with_empty_team_rating_history(dataFrame)))
        print(dataFrame[["team_1_score", "team_2_score", "team_1_player_10_average_ratings", "team_2_player_10_average_ratings", "team_1_mean_hist_n", "team_2_mean_hist_n", "delta_elo_mean"]].head())

        dataFrame.to_pickle(self.dataset_path)
        print("Dataset saved to: " + self.dataset_path)

    def _train_model(self):
        trainer = ModelTrainer(self.dataset_path)
        trainer.train()
        trainer.bet()
        trainer.save_model(self.model_path)

    def _predict_upcoming_matches(self):
        try:
            predictor = UpcomingPredictor(self.model_path)
        except RuntimeError as error:
            if self._is_upcoming_odds_unavailable_error(error):
                print(str(error))
                print("Upcoming prediction skipped because fresh VLR odds are unavailable.")
                return False

            raise

        predictor.matchlinks = self._get_today_and_tomorrow_matches(predictor.matchlinks)
        self._print_upcoming_match_queue(predictor.matchlinks)

        for bet in predictor.bet():
            print(str(bet))

        return True

    def _get_today_and_tomorrow_matches(self, matches):
        today = datetime.now(ZoneInfo(self.timezone)).date()
        tomorrow = today + timedelta(days=1)
        allowed_dates = {today, tomorrow}

        filtered_matches = [
            match
            for match in matches
            if match.get("date_time") and match["date_time"].date() in allowed_dates
        ]

        return sorted(filtered_matches, key=lambda match: match["date_time"])

    def _print_upcoming_match_queue(self, matches):
        print("Upcoming matches for today/tomorrow with bookmaker odds: " + str(len(matches)))

        for match in matches:
            print(
                match["date_time"].strftime("%Y-%m-%d %H:%M") +
                " - " +
                match["match_link"]
            )

    def _is_upcoming_odds_unavailable_error(self, error):
        message = str(error).lower()
        return "vlr" in message and ("blocked" in message or "skipping" in message)

    def _notify_done(self, predicted_upcoming_matches):
        message = "The complete workflow is done!"

        if not predicted_upcoming_matches:
            message = "The workflow is done, but upcoming prediction was skipped."

        notification.notify(
            title="VLR Predictor",
            message=message,
            timeout=5
        )


if __name__ == "__main__":
    workflow = Workflow()
    workflow.run()
