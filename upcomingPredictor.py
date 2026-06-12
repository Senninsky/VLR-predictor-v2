import re
import time
from datetime import datetime
from functools import cache
from urllib.parse import urljoin
from urllib.request import Request, urlopen

import joblib
import numpy as np
import pandas as pd
from bs4 import BeautifulSoup

from featureExtractor import DataExtractor
from modelTrainer import CalibratedModel
from vlrSearcher import VlrSearcher

from plyer import notification


class Bet:
    def __init__(self, bet_data):
        self.data = bet_data

    def __getitem__(self, key):
        return self.data[key]

    def get(self, key, default=None):
        return self.data.get(key, default)

    def __str__(self):
        team_name = self._get_team_name()
        date_time = self._get_date_time_text()

        return (
            "Bet on " + team_name + "\n"
            + date_time +
            "Match: " + self.data["match_link"] + "\n"
            "Odds: " + str(self.data["odds"]) + "\n"
            "Win probability: " + str(round(self.data["win_probability"] * 100, 1)) + "%\n"
            "Implied probability: " + str(round(self.data["implied_probability"] * 100, 1)) + "%\n"
            "Edge: " + str(round(self.data["edge"] * 100, 1)) + "%\n"
            "EV: " + str(self.data["ev"]) + "\n"
        )

    def _get_team_name(self):
        if "team_name" in self.data:
            return self.data["team_name"]

        return self.data["team"]

    def _get_date_time_text(self):
        date_time = self.data.get("date_time")

        if not date_time:
            return ""

        return "Date/time: " + date_time.strftime("%Y-%m-%d %H:%M") + "\n"


class UpcomingPredictor:
    def __init__(self, model_path="model.pkl"):
        self.interpreter = VlrSearcher()
        self.matchlinks = self.interpreter.snip()
        self.model, self.feature_columns = self._load_model(model_path)
        self.featureBuilder = DataExtractor().build_feature_builder_from_database()

    def bet(self):
        recommended_bets = []
        predictions = self._predict()

        for prediction in predictions:
            team_1_bet = self._should_bet(prediction, "team_1")
            team_2_bet = self._should_bet(prediction, "team_2")

            if team_1_bet:
                recommended_bets.append(self._create_bet(prediction, "team_1"))

            if team_2_bet:
                recommended_bets.append(self._create_bet(prediction, "team_2"))

        print("Bets qualified: " + str(len(recommended_bets)) + "/" + str(len(predictions)))

        return recommended_bets
    
    def _predict(self):
        predictions = []

        for match_link_data in self.matchlinks:
            predict_info = self._scrape_predict_info(match_link_data)
            features = self._extract_features(predict_info)
            probabilities = self.model.predict_proba(features)[0]

            match_link_data.update(predict_info)
            match_link_data["team_1_win_probability"] = round(float(probabilities[1]), 3)
            match_link_data["team_2_win_probability"] = round(float(probabilities[0]), 3)
            predictions.append(match_link_data)

        return predictions
    
    def _should_bet(self, prediction, team):
        if prediction["team_1_player_amount"] != 5 or prediction["team_2_player_amount"] != 5:
            print(
                "No bet on " + prediction[team + "_name"] +
                ": not 5 players found for each team (" +
                str(prediction["team_1_player_amount"]) + " vs " +
                str(prediction["team_2_player_amount"]) + ")"
            )
            return False

        odds = prediction[team + "_odds"]

        if odds <= 1.0:
            print("No bet on " + prediction[team + "_name"] + ": invalid odds " + str(odds))
            return False

        win_probability = prediction[team + "_win_probability"]
        implied_probability = 1 / odds
        edge = win_probability - implied_probability
        ev = win_probability * odds - 1

        if not (win_probability > 0.55 and edge > 0.08 and ev > 0):
            print(
                "No bet on " + prediction[team + "_name"] +
                ": prediction strategy did not qualify " +
                "(probability=" + str(round(win_probability, 3)) +
                ", edge=" + str(round(edge, 3)) +
                ", ev=" + str(round(ev, 3)) + ")"
            )
            return False

        return True
    
    def _create_bet(self, prediction, team):
        win_probability = prediction[team + "_win_probability"]
        odds = prediction[team + "_odds"]
        implied_probability = 1 / odds

        return Bet({
            "match_link": prediction["match_link"],
            "date_time": prediction.get("date_time"),
            "team": team,
            "team_name": prediction[team + "_name"],
            "odds": odds,
            "win_probability": win_probability,
            "implied_probability": round(implied_probability, 3),
            "edge": round(win_probability - implied_probability, 3),
            "ev": round(win_probability * odds - 1, 3),
        })

    def _load_model(self, model_path):
        model_data = joblib.load(model_path)

        if isinstance(model_data, dict):
            if "base_model" in model_data:
                model = CalibratedModel(model_data["base_model"], model_data.get("calibrator"))
            else:
                model = model_data["model"]

            return model, model_data.get("feature_columns", [])

        return model_data, []

    def _scrape_predict_info(self, match_link):
        match_link_data = match_link

        if isinstance(match_link, dict):
            match_link = match_link["match_link"]

        soup = BeautifulSoup(self._get_html(match_link), "html.parser")
        team_1_players, team_2_players = self._get_match_players(soup)
        team_1_name, team_2_name = self._get_match_team_names(soup)
        date_time = self._get_predict_date_time(match_link_data)
        team_1_features = self.featureBuilder.state.build_team_features([player["id"] for player in team_1_players], date_time)
        team_2_features = self.featureBuilder.state.build_team_features([player["id"] for player in team_2_players], date_time)

        predict_info = {
            "match_link": match_link,
            "date_time": date_time,
            "team_1_name": team_1_name,
            "team_2_name": team_2_name,
            "team_1_player_ids": [player["id"] for player in team_1_players],
            "team_2_player_ids": [player["id"] for player in team_2_players],
            "team_1_player_amount": len(team_1_players),
            "team_2_player_amount": len(team_2_players),
            "team_1_player_history_match_amounts": team_1_features["player_history_counts"],
            "team_2_player_history_match_amounts": team_2_features["player_history_counts"],
        }

        if isinstance(match_link_data, dict):
            predict_info["team_1_odds"] = match_link_data["team_1_odds"]
            predict_info["team_2_odds"] = match_link_data["team_2_odds"]

        return predict_info

    def _extract_features(self, predict_info):
        row = self.featureBuilder.build_match_features(
            predict_info["team_1_player_ids"],
            predict_info["team_2_player_ids"],
            predict_info.get("date_time"),
            include_diagnostics=False,
        )
        row["team_1_odds"] = predict_info.get("team_1_odds", 0.0)
        row["team_2_odds"] = predict_info.get("team_2_odds", 0.0)
        features = pd.DataFrame([row])

        if not self.feature_columns:
            return features

        features = features.reindex(columns=self.feature_columns, fill_value=0.0)
        features = features.replace([np.inf, -np.inf], 0.0)
        features = features.fillna(0.0)

        return features

    def _get_predict_date_time(self, match_link_data):
        if isinstance(match_link_data, dict) and match_link_data.get("date_time"):
            return match_link_data["date_time"]

        return datetime.now()

    def _get_match_team_names(self, soup):
        title = soup.title.get_text(" ", strip=True)
        teams = title.split("|")[0].split(" vs. ")

        if len(teams) == 2:
            return teams[0].strip(), teams[1].strip()

        return "Team 1", "Team 2"

    def _get_match_players(self, soup):
        players = self._get_players_from_stats_tables(soup)

        if len(players) < 10:
            players = self._get_players_from_roster_links(soup)

        return players[:5], players[5:10]

    def _get_players_from_stats_tables(self, soup):
        players = []
        stats = self._get_player_stats(soup)

        if not stats:
            return players

        for table in stats.find_all("table", class_="mod-overview")[:2]:
            for player in self._get_players_from_container(table):
                if not self._has_player(players, player["id"]):
                    players.append(player)

        return players

    def _get_players_from_roster_links(self, soup):
        players = []

        for player_link in soup.find_all("a", href=re.compile(r"^/player/\d+/")):
            href = player_link["href"]
            player_id = href.split("/")[2]

            if self._has_player(players, player_id):
                continue

            players.append({
                "id": player_id,
                "name": player_link.get_text(" ", strip=True),
                "link": urljoin("https://www.vlr.gg/", href),
            })

            if len(players) == 10:
                break

        return players

    def _get_players_from_container(self, container):
        players = []

        for player_link in container.find_all("a", href=re.compile(r"^/player/\d+/")):
            href = player_link["href"]
            player_id = href.split("/")[2]

            players.append({
                "id": player_id,
                "name": player_link.get_text(" ", strip=True),
                "link": urljoin("https://www.vlr.gg/", href),
            })

        return players

    def _has_player(self, players, player_id):
        return any(player["id"] == player_id for player in players)

    def _get_player_stats(self, soup):
        all_maps_tab = soup.find("div", class_="vm-stats-game", attrs={"data-game-id": "all"})

        if all_maps_tab:
            return all_maps_tab

        active_map_tab = soup.find("div", class_="vm-stats-game mod-active")

        if active_map_tab:
            return active_map_tab

        return soup.find("div", class_="vm-stats-game")

    @cache
    def _get_html(self, link):
        attempt = 1

        while True:
            try:
                request = Request(link, headers={"User-Agent": "Mozilla/5.0"})
                return urlopen(request, timeout=30).read().decode("utf-8")
            except Exception as error:
                wait_seconds = min(10 * attempt, 60)
                print(
                    "Request failed for " + link +
                    " (attempt " + str(attempt) + "): " + str(error) +
                    ". Retrying in " + str(wait_seconds) + " seconds..."
                )

                time.sleep(wait_seconds)
                attempt += 1


if __name__ == "__main__":
    predictor = UpcomingPredictor("model.pkl")
    for bet in predictor.bet():
        print(str(bet))

    notification.notify(
        title="VLR Predictor",
        message="The predictor is done with calculation bets!",
        timeout=5
    )
