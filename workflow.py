# Importations
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
        print(dataFrame[["team_1_score", "team_2_score", "team_1_odds", "team_2_odds", "team_1_player_10_average_ratings", "team_2_player_10_average_ratings", "team_1_10_average_ratings", "team_1_10_average_ratings"]].head())

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
            if self._is_thunderpick_unavailable_error(error):
                print(str(error))
                print("Upcoming prediction skipped because fresh Thunderpick odds are unavailable.")
                return False

            raise

        for bet in predictor.bet():
            print(str(bet))

        return True

    def _is_thunderpick_unavailable_error(self, error):
        message = str(error).lower()
        return "thunderpick" in message and ("blocked" in message or "skipping" in message)

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
