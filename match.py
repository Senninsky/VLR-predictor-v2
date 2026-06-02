# Importations
import re
import time
from urllib.request import Request, urlopen

from bs4 import BeautifulSoup

from team import Team

class Match:
    def __init__(self, date=None, hour=None, id=None):
        self.id = id

        self.date = date
        self.hour = hour
        self._clean_date_and_time()

        # Scrape all info from match_page
        self.link = "https://www.vlr.gg/" + self.id
        html = self._get_html(self.link)
        soup = BeautifulSoup(html, "html.parser")

        try:
            match_header = soup.find("div", class_="match-header-vs")
            score_box = match_header.find("div", class_="js-spoiler")
            scores = re.findall(r"\d+", score_box.get_text(" ", strip=True))
            team_1_score = int(scores[0])
            team_2_score = int(scores[1])
        except Exception:
            print(f"Could not scrape score for match_id: {self.id}")
            raise

        self.has_player_stats = False
        stats = self._get_player_stats(soup)

        if stats:
            player_tables = stats.find_all("table", class_="mod-overview")

            if len(player_tables) >= 2:
                try:
                    self.team_1 = Team(team_1_score, player_tables[0])
                    self.team_2 = Team(team_2_score, player_tables[1])
                    self.has_player_stats = True
                except Exception:
                    print(f"Could not scrape player stats for match_id: {self.id}")
                    raise
            else:
                self.team_1 = Team(team_1_score)
                self.team_2 = Team(team_2_score)
        else:
            self.team_1 = Team(team_1_score)
            self.team_2 = Team(team_2_score)

        self.odds = self._get_odds(soup)

    def __str__(self):
        return (
            f"Match {self.id} - {self.date} at {self.hour} ({self.team_1.score}:{self.team_2.score})\n"
            f"Odds: {self.odds if self.odds else 'no odds visible'}\n\n"
            f"Player stats: {'available' if self.has_player_stats else 'not available'}\n\n"
            f"Team 1\n"
            f"{self.team_1}\n\n"
            f"Team 2\n"
            f"{self.team_2}"
        )
    
    def _clean_date_and_time(self):
        # Remove the metadata "Today" or "Yesterday" if present
        if self.date:
            self.date = self.date.replace("Today", "")
            self.date = self.date.replace("Yesterday", "")
            self.date = self.date.strip()

            months = {
                "Jan": "01",
                "January": "01",
                "Feb": "02",
                "February": "02",
                "Mar": "03",
                "March": "03",
                "Apr": "04",
                "April": "04",
                "May": "05",
                "Jun": "06",
                "June": "06",
                "Jul": "07",
                "July": "07",
                "Aug": "08",
                "August": "08",
                "Sep": "09",
                "September": "09",
                "Oct": "10",
                "October": "10",
                "Nov": "11",
                "November": "11",
                "Dec": "12",
                "December": "12",
            }

            date_match = re.search(r"([A-Za-z]+) (\d{1,2}),? (\d{4})", self.date)

            if date_match:
                month_name = date_match.group(1)
                day = date_match.group(2).zfill(2)
                month = months[month_name]
                year = date_match.group(3)
                self.date = f"{day}/{month}/{year}"

        # Clean hour -> 24-hour format
        if self.hour:
            if len(self.hour.split()) == 1:
                return

            time, period = self.hour.split()
            hours, minutes = time.split(":")
            hours = int(hours)

            if period == "PM" and hours != 12:
                hours += 12

            if period == "AM" and hours == 12:
                hours = 0

            self.hour = f"{hours:02d}:{minutes}"

    def _get_odds(self, soup):
        odds = []

        for bet in soup.find_all(class_="match-bet-item"):
            bet_text = bet.get_text(" ", strip=True)
            returned_money = re.search(r"returned \$(\d+)", bet_text)

            if returned_money:
                odds.append(int(returned_money.group(1)) / 100)

        return odds

    def _get_player_stats(self, soup):
        stats = soup.find("div", class_="vm-stats-game mod-active", attrs={"data-game-id": "all"})

        if not stats:
            stats = soup.find("div", class_="vm-stats-game mod-active")

        if not stats:
            stats = soup.find("div", class_="vm-stats-game", attrs={"data-game-id": "all"})

        return stats

    def _get_html(self, link):
        for attempt in range(3):
            try:
                request = Request(link, headers={"User-Agent": "Mozilla/5.0"})
                return urlopen(request, timeout=15).read().decode("utf-8")
            except Exception:
                if attempt == 2:
                    raise

                time.sleep(2)
