import re
import time
from concurrent.futures import ThreadPoolExecutor
from datetime import datetime
from functools import cache
from urllib.parse import urljoin
from urllib.request import Request, urlopen

import joblib
import pandas as pd
from bs4 import BeautifulSoup

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
        self.model = joblib.load(model_path)

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

        if any(amount < 7 for amount in prediction["team_1_player_history_match_amounts"]):
            print(
                "No bet on " + prediction[team + "_name"] +
                ": team 1 has a player with less than 7 history matches " +
                str(prediction["team_1_player_history_match_amounts"])
            )
            return False

        if any(amount < 7 for amount in prediction["team_2_player_history_match_amounts"]):
            print(
                "No bet on " + prediction[team + "_name"] +
                ": team 2 has a player with less than 7 history matches " +
                str(prediction["team_2_player_history_match_amounts"])
            )
            return False

        win_probability = prediction[team + "_win_probability"]
        odds = prediction[team + "_odds"]
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

    def _scrape_predict_info(self, match_link):
        match_link_data = match_link

        if isinstance(match_link, dict):
            match_link = match_link["match_link"]

        soup = BeautifulSoup(self._get_html(match_link), "html.parser")
        team_1_players, team_2_players = self._get_match_players(soup)
        team_1_name, team_2_name = self._get_match_team_names(soup)

        team_1_history_features = self._get_player_10_history_features(team_1_players)
        team_2_history_features = self._get_player_10_history_features(team_2_players)

        predict_info = {
            "match_link": match_link,
            "team_1_name": team_1_name,
            "team_2_name": team_2_name,
            "team_1_player_ids": [player["id"] for player in team_1_players],
            "team_2_player_ids": [player["id"] for player in team_2_players],
            "team_1_player_amount": len(team_1_players),
            "team_2_player_amount": len(team_2_players),
            "team_1_player_history_match_amounts": team_1_history_features["match_amounts"],
            "team_2_player_history_match_amounts": team_2_history_features["match_amounts"],
            "team_1_player_10_average_ratings": team_1_history_features["average_ratings"],
            "team_2_player_10_average_ratings": team_2_history_features["average_ratings"],
            "team_1_player_10_average_interval": team_1_history_features["average_intervals"],
            "team_2_player_10_average_interval": team_2_history_features["average_intervals"],
            "team_1_player_10_match_win_percentage": team_1_history_features["win_percentages"],
            "team_2_player_10_match_win_percentage": team_2_history_features["win_percentages"],
            "team_1_10_average_ratings": self._average(team_1_history_features["average_ratings"]),
            "team_2_10_average_ratings": self._average(team_2_history_features["average_ratings"]),
        }

        if isinstance(match_link_data, dict):
            predict_info["team_1_odds"] = match_link_data["team_1_odds"]
            predict_info["team_2_odds"] = match_link_data["team_2_odds"]

        return predict_info

    def _extract_features(self, predict_info):
        row = {
            "team_1_odds": predict_info["team_1_odds"],
            "team_2_odds": predict_info["team_2_odds"],
            "team_1_10_average_ratings": predict_info["team_1_10_average_ratings"],
            "team_2_10_average_ratings": predict_info["team_2_10_average_ratings"],
        }

        self._add_player_feature(row, "team_1", "10_average_rating", predict_info["team_1_player_10_average_ratings"])
        self._add_player_feature(row, "team_2", "10_average_rating", predict_info["team_2_player_10_average_ratings"])
        self._add_player_feature(row, "team_1", "10_average_interval", predict_info["team_1_player_10_average_interval"])
        self._add_player_feature(row, "team_2", "10_average_interval", predict_info["team_2_player_10_average_interval"])
        self._add_player_feature(row, "team_1", "10_match_win_percentage", predict_info["team_1_player_10_match_win_percentage"])
        self._add_player_feature(row, "team_2", "10_match_win_percentage", predict_info["team_2_player_10_match_win_percentage"])

        return pd.DataFrame([row])

    def _add_player_feature(self, row, team, feature_name, values):
        values = values[:5]

        for i, value in enumerate(values):
            row[team + "_player_" + str(i + 1) + "_" + feature_name] = value

        for i in range(len(values), 5):
            row[team + "_player_" + str(i + 1) + "_" + feature_name] = 0.0

    def _get_match_team_names(self, soup):
        title = soup.title.get_text(" ", strip=True)
        teams = title.split("|")[0].split(" vs. ")

        if len(teams) == 2:
            return teams[0].strip(), teams[1].strip()

        return "Team 1", "Team 2"

    def _get_match_players(self, soup):
        players = []

        for player_link in soup.find_all("a", href=re.compile(r"^/player/\d+/")):
            href = player_link["href"]
            player_id = href.split("/")[2]

            if any(player["id"] == player_id for player in players):
                continue

            players.append({
                "id": player_id,
                "name": player_link.get_text(" ", strip=True),
                "link": urljoin("https://www.vlr.gg/", href),
            })

            if len(players) == 10:
                break

        return players[:5], players[5:10]

    def _get_player_10_history_features(self, players):
        average_ratings = []
        average_intervals = []
        win_percentages = []
        match_amounts = []

        with ThreadPoolExecutor(max_workers=5) as executor:
            player_histories = list(executor.map(self._get_player_last_10_history, players))

        for history in player_histories:
            ratings = [entry["rating"] for entry in history if entry["rating"] is not None]
            date_times = [entry["date_time"] for entry in history if entry["date_time"] is not None]
            wins = [entry["won"] for entry in history if entry["won"] is not None]

            match_amounts.append(len(ratings))

            if ratings:
                average_ratings.append(round(sum(ratings) / len(ratings), 3))
            else:
                average_ratings.append(0.0)

            average_intervals.append(self._get_average_interval(date_times))
            win_percentages.append(self._get_win_percentage(wins))

        return {
            "average_ratings": average_ratings,
            "average_intervals": average_intervals,
            "win_percentages": win_percentages,
            "match_amounts": match_amounts,
        }

    def _get_player_last_10_history(self, player):
        soup = BeautifulSoup(self._get_html(self._get_player_matches_link(player)), "html.parser")
        history = []
        used_match_ids = set()

        for match_link in soup.find_all("a", class_="m-item", href=True):
            match_id = match_link["href"].split("/")[1]

            if match_id in used_match_ids:
                continue

            used_match_ids.add(match_id)
            rating = self._get_player_rating_from_match(match_link["href"], player["id"])
            date_time = self._get_player_match_date_time(match_link)
            won = self._get_player_match_win(match_link)

            history.append({
                "rating": rating,
                "date_time": date_time,
                "won": won,
            })

            if len(history) == 10:
                break

        return history

    def _get_player_match_date_time(self, match_link):
        date = match_link.find("div", class_="m-item-date")

        if not date:
            return None

        text = date.get_text(" ", strip=True)

        try:
            return datetime.strptime(text, "%Y/%m/%d %I:%M %p")
        except ValueError:
            return None

    def _get_player_match_win(self, match_link):
        result = match_link.find("div", class_=re.compile(r"\bm-item-result\b"))

        if not result:
            return None

        classes = result.get("class", [])

        if "mod-win" in classes:
            return 1.0

        if "mod-loss" in classes:
            return 0.0

        return None

    def _get_average_interval(self, match_date_times):
        if len(match_date_times) < 10:
            return 0.0

        match_date_times = sorted(match_date_times)
        intervals = []

        for i in range(1, len(match_date_times)):
            interval = match_date_times[i] - match_date_times[i - 1]
            intervals.append(interval.total_seconds() / 86400)

        return round(sum(intervals) / len(intervals), 3)

    def _get_win_percentage(self, wins):
        if len(wins) < 10:
            return 0.0

        return round(sum(wins) / len(wins), 3)

    def _get_player_matches_link(self, player):
        return player["link"].replace("/player/", "/player/matches/")

    def _get_player_rating_from_match(self, match_link, player_id):
        soup = BeautifulSoup(self._get_html(urljoin("https://www.vlr.gg/", match_link)), "html.parser")
        player_stats = self._get_player_stats(soup)

        if not player_stats:
            return None

        for row in player_stats.find_all("tr"):
            player_link = row.find("a", href=re.compile(rf"^/player/{player_id}/"))

            if not player_link:
                continue

            columns = row.find_all("td")

            if len(columns) < 3:
                return None

            try:
                return float(self._get_first_value(columns[2]))
            except ValueError:
                return None

        return None

    def _get_first_value(self, column):
        value = column.find(class_="mod-both")

        if value:
            return value.get_text(strip=True)

        return column.get_text(" ", strip=True).split()[0]

    def _get_player_stats(self, soup):
        all_maps_tab = soup.find("div", class_="vm-stats-game", attrs={"data-game-id": "all"})

        if all_maps_tab:
            return all_maps_tab

        active_map_tab = soup.find("div", class_="vm-stats-game mod-active")

        if active_map_tab:
            return active_map_tab

        return soup.find("div", class_="vm-stats-game")

    def _average(self, values):
        values = [value for value in values if value != 0.0]

        if not values:
            return 0.0

        return round(sum(values) / len(values), 3)

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
