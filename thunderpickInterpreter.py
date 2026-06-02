import re
import time
from difflib import SequenceMatcher
from functools import cache
from urllib.parse import urljoin
from urllib.request import Request, urlopen

from bs4 import BeautifulSoup


class ThunderpickInterpreter:
    def __init__(self, text_filename):
        self.txt_file = text_filename
        self.default_link = "https://www.vlr.gg/"

    def snip(self):
        with open(self.txt_file, "r", encoding="utf-8") as file:
            lines = file.read().splitlines()

        matches = []
        current_match = []

        for line in lines:
            line = line.strip()

            if not line:
                continue

            if line.startswith("BO"):
                if current_match:
                    matches.append(self._clean_matchstring("\n".join(current_match)))

                current_match = [line]
            elif current_match:
                current_match.append(line)

        if current_match:
            matches.append(self._clean_matchstring("\n".join(current_match)))

        print("Matches found in txt file: " + str(len(matches)))

        return matches

    def map_matchstring_to_matchlink(self, match_string):
        match_data = self._parse_match_string(match_string)
        candidates = self._get_match_candidates_from_matches_page()
        best_candidate = self._find_best_match_candidate(match_data, candidates)

        if best_candidate:
            match_data = self._add_order_to_match_data(match_data, best_candidate)
            match_link_data = self._create_match_link_data(best_candidate["link"], match_data)
            return match_link_data

        event_link = self._find_event_link(match_data["event"])
        if not event_link:
            return None

        candidates = self._get_match_candidates_from_event_page(event_link)
        best_candidate = self._find_best_match_candidate(match_data, candidates)

        if best_candidate:
            match_data = self._add_order_to_match_data(match_data, best_candidate)
            match_link_data = self._create_match_link_data(best_candidate["link"], match_data)
            return match_link_data

        return None

    def map_matchstrings_to_matchlinks(self, match_strings):
        match_links = []
        unmapped_matches = []

        for match_string in match_strings:
            match_link_data = self.map_matchstring_to_matchlink(match_string)

            if match_link_data:
                match_links.append(match_link_data)
            else:
                match_data = self._parse_match_string(match_string)
                unmapped_matches.append(match_data["team_1"] + " vs " + match_data["team_2"])

        print("Matches mapped to VLR links: " + str(len(match_links)) + "/" + str(len(match_strings)))

        if unmapped_matches:
            print("Unmapped matches:")

            for match in unmapped_matches:
                print("- " + match)

        return match_links

    def _clean_matchstring(self, match_string):
        cleaned_lines = []

        for line in match_string.splitlines():
            line = line.strip()

            if line.startswith("BO"):
                continue

            if "|" in line:
                continue

            if line.startswith("+"):
                continue

            cleaned_lines.append(line)

        return "\n".join(cleaned_lines)

    def _parse_match_string(self, match_string):
        lines = match_string.splitlines()

        return {
            "date": lines[0],
            "event": lines[1],
            "team_1": lines[2],
            "team_1_odds": float(lines[3]),
            "team_2_odds": float(lines[5]),
            "team_2": lines[6],
        }

    def _create_match_link_data(self, match_link, match_data):
        team_1_odds, team_2_odds = self._get_vlr_ordered_odds(match_data)

        return {
            "match_link": match_link,
            "team_1_odds": team_1_odds,
            "team_2_odds": team_2_odds,
        }
    
    def _get_vlr_ordered_odds(self, match_data):
        if match_data.get("reversed"):
            return match_data["team_2_odds"], match_data["team_1_odds"]

        return match_data["team_1_odds"], match_data["team_2_odds"]
    
    def _add_order_to_match_data(self, match_data, candidate):
        match_data = match_data.copy()
        match_data["reversed"] = candidate["reversed"]
        return match_data

    def _get_match_candidates_from_matches_page(self):
        html = self._get_html(self.default_link + "matches")
        soup = BeautifulSoup(html, "html.parser")
        candidates = []

        for match in soup.find_all("a", class_="match-item"):
            href = match.get("href")
            teams = match.find_all("div", class_="match-item-vs-team-name")
            event = match.find("div", class_="match-item-event")

            if not href or len(teams) < 2:
                continue

            candidates.append({
                "link": urljoin(self.default_link, href),
                "team_1": teams[0].get_text(" ", strip=True),
                "team_2": teams[1].get_text(" ", strip=True),
                "event": event.get_text(" ", strip=True) if event else "",
            })

        return candidates

    def _get_match_candidates_from_event_page(self, event_link):
        html = self._get_html(event_link)
        soup = BeautifulSoup(html, "html.parser")
        candidates = []

        for match in soup.find_all("a", href=True):
            href = match.get("href")

            if not re.match(r"^/\d+/", href):
                continue

            text = match.get_text(" ", strip=True)
            teams = re.split(r"\s+[–-]\s+", text)

            if len(teams) < 2:
                continue

            candidates.append({
                "link": urljoin(self.default_link, href),
                "team_1": teams[0].strip(),
                "team_2": teams[1].strip(),
                "event": "",
            })

        return candidates

    def _find_event_link(self, event_name):
        html = self._get_html(self.default_link + "events")
        soup = BeautifulSoup(html, "html.parser")
        best_event = None
        best_score = 0

        for event in soup.find_all("a", class_="event-item"):
            score = self._similarity(event_name, event.get_text(" ", strip=True))

            if score > best_score:
                best_score = score
                best_event = event

        if best_event and best_score > 0.45:
            return urljoin(self.default_link, best_event["href"])

        return None

    def _find_best_match_candidate(self, match_data, candidates):
        best_candidate = None
        best_score = 0

        for candidate in candidates:
            same_order_score = (
                self._similarity(match_data["team_1"], candidate["team_1"]) +
                self._similarity(match_data["team_2"], candidate["team_2"])
            ) / 2
            reversed_order_score = (
                self._similarity(match_data["team_1"], candidate["team_2"]) +
                self._similarity(match_data["team_2"], candidate["team_1"])
            ) / 2
            team_score = max(same_order_score, reversed_order_score)
            event_score = self._similarity(match_data["event"], candidate["event"])
            score = (team_score * 0.8) + (event_score * 0.2)

            if score > best_score:
                best_score = score
                best_candidate = self._add_order_to_candidate(candidate, reversed_order_score > same_order_score)

        if best_candidate and best_score > 0.65:
            return best_candidate

        return None
    
    def _add_order_to_candidate(self, candidate, reversed_order):
        candidate = candidate.copy()
        candidate["reversed"] = reversed_order
        return candidate

    def _similarity(self, a, b):
        return SequenceMatcher(None, self._normalize(a), self._normalize(b)).ratio()

    def _normalize(self, text):
        text = text.lower()
        text = text.replace("ø", "o")
        text = text.replace("ü", "u")
        text = text.replace("á", "a")
        text = text.replace("é", "e")
        text = text.replace("í", "i")
        text = text.replace("ó", "o")
        text = text.replace("ú", "u")
        text = re.sub(r"[^a-z0-9]+", " ", text)
        return " ".join(text.split())

    @cache
    def _get_html(self, link):
        for attempt in range(3):
            try:
                request = Request(link, headers={"User-Agent": "Mozilla/5.0"})
                return urlopen(request, timeout=15).read().decode("utf-8")
            except Exception:
                if attempt == 2:
                    raise

                time.sleep(2)


if __name__ == "__main__":
    predictor = ThunderpickInterpreter("last_copied_thunderpick_matches.txt")
    for match_string in predictor.snip():
        print(match_string)
        print(predictor.map_matchstring_to_matchlink(match_string))
        print()
