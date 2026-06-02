# Importations
import time
from urllib.request import Request, urlopen

from bs4 import BeautifulSoup

from dbManager import DbManager
from match import Match

# Scraper
class VlrScraper:
    def __init__(self):
        self.default_link = "https://www.vlr.gg/"
        self.dbManager = DbManager()

    def scrape_last_match_links(self, amount=10):
        # 0: Match results link
        match_results_link = self.default_link + "matches/results/"

        match_links = []
        page = 1
        checked_matches = 0
        while checked_matches < amount:
            link = match_results_link
            if page > 1:
                link += f"?page={page}"

            html = self._get_html(link)
            soup = BeautifulSoup(html, "html.parser")

            matches_on_page = 0
            current_date = None
            for element in soup.find_all(["div", "a"]):
                if checked_matches >= amount:
                    break

                if element.name == "div" and "wf-label" in element.get("class", []):
                    current_date = element.get_text(" ", strip=True)

                if element.name == "a" and "match-item" in element.get("class", []):
                    matches_on_page += 1
                    checked_matches += 1
                    print(f"Retrieving match links: {checked_matches}/{amount}     ", end="\r", flush=True)

                    match_id = self._get_match_id_from_match_link(element["href"])
                    if self.dbManager.is_match_in_db(match_id):
                        if checked_matches >= amount:
                            break
                        continue

                    match_time = element.find("div", class_="match-item-time").get_text(strip=True)
                    match_links.append((element["href"], current_date, match_time))

                    if checked_matches >= amount:
                        break

            if matches_on_page == 0:
                break

            page += 1

        print()
        return match_links

    def convert_match_link_to_match_object(self, match_link_data):
        match_link, date, match_time = match_link_data
        match_id = self._get_match_id_from_match_link(match_link)
        return Match(date, match_time, match_id)

    def _get_match_id_from_match_link(self, match_link):
        return match_link.split("/")[1]

    def _get_html(self, link):
        for attempt in range(3):
            try:
                request = Request(link, headers={"User-Agent": "Mozilla/5.0"})
                return urlopen(request, timeout=15).read().decode("utf-8")
            except Exception:
                if attempt == 2:
                    raise

                time.sleep(2)
