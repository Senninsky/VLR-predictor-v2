import re
import statistics
import time
from concurrent.futures import ThreadPoolExecutor, as_completed
from datetime import datetime
from functools import cache
from urllib.parse import urljoin
from urllib.request import Request, urlopen

from bs4 import BeautifulSoup

from bookkeeper import Bookkeeper


class VlrSearcher:
    def __init__(
        self,
        default_link="https://www.vlr.gg/",
        max_event_pages=5,
        max_workers=8,
        bookmaker_key="thunderpick",
        bookmaker_priority=None,
    ):
        self.default_link = default_link
        self.max_event_pages = max_event_pages
        self.max_workers = max_workers
        self.bookmaker_priority = self._get_bookmaker_priority(bookmaker_key, bookmaker_priority)
        self.bookmaker_key = self.bookmaker_priority[0]

    def scrape_matches(self):
        events = self._get_ongoing_and_upcoming_events()
        print("Ongoing/upcoming VLR events found: " + str(len(events)))

        upcoming_matches = self._get_upcoming_matches_from_events(events)
        print("Upcoming VLR matches found in those events: " + str(len(upcoming_matches)))

        matches_with_odds = self._get_matches_with_bookmaker_odds(upcoming_matches)
        print("Upcoming VLR matches with bookmaker odds: " + str(len(matches_with_odds)))
        self._print_vig_stats(matches_with_odds)

        return matches_with_odds

    def snip(self):
        return self.scrape_matches()

    def _get_ongoing_and_upcoming_events(self):
        events = []
        seen_links = set()

        for page in range(1, self.max_event_pages + 1):
            page_events = self._get_events_from_page(page)
            eligible_events = [
                event
                for event in page_events
                if event["status"] in ("ongoing", "upcoming")
            ]

            for event in eligible_events:
                if event["link"] in seen_links:
                    continue

                seen_links.add(event["link"])
                events.append(event)

            if page > 1 and not eligible_events:
                break

        return events

    def _get_events_from_page(self, page):
        link = self.default_link + "events"

        if page > 1:
            link += "/?page=" + str(page)

        soup = BeautifulSoup(self._get_html(link), "html.parser")
        events = []

        for event in soup.find_all("a", class_="event-item", href=True):
            status = event.find("span", class_="event-item-desc-item-status")
            title = event.find("div", class_="event-item-title")

            if not status:
                continue

            events.append({
                "name": title.get_text(" ", strip=True) if title else "",
                "status": status.get_text(" ", strip=True).lower(),
                "link": urljoin(self.default_link, event["href"]),
                "matches_link": self._get_event_matches_link(event["href"]),
            })

        return events

    def _get_event_matches_link(self, event_href):
        match = re.match(r"^/event/(\d+)/([^/?#]+)", event_href)

        if not match:
            return urljoin(self.default_link, event_href)

        return urljoin(
            self.default_link,
            "/event/matches/" + match.group(1) + "/" + match.group(2) + "/?group=upcoming",
        )

    def _get_upcoming_matches_from_events(self, events):
        matches = []
        seen_links = set()

        with ThreadPoolExecutor(max_workers=self.max_workers) as executor:
            futures = {
                executor.submit(self._get_upcoming_matches_from_event, event): event
                for event in events
            }

            for future in as_completed(futures):
                event = futures[future]

                try:
                    event_matches = future.result()
                except Exception as error:
                    print("Could not scrape event matches for " + event["name"] + ": " + str(error))
                    continue

                for match in event_matches:
                    if match["match_link"] in seen_links:
                        continue

                    seen_links.add(match["match_link"])
                    matches.append(match)

        return matches

    def _get_upcoming_matches_from_event(self, event):
        soup = BeautifulSoup(self._get_html(event["matches_link"]), "html.parser")
        matches = []
        current_date = None

        for element in soup.find_all(["div", "a"]):
            if element.name == "div" and "wf-label" in element.get("class", []):
                current_date = self._parse_date_heading(element.get_text(" ", strip=True))
                continue

            if element.name != "a" or "match-item" not in element.get("class", []) or not element.get("href"):
                continue

            if not self._is_upcoming_match(element):
                continue

            date_time = self._get_match_item_date_time(element, current_date)
            teams = self._get_match_item_team_names(element)

            if len(teams) != 2 or "TBD" in teams:
                continue

            matches.append({
                "match_link": urljoin(self.default_link, element["href"]),
                "date_time": date_time,
                "event": event["name"],
                "team_1": teams[0],
                "team_2": teams[1],
            })

        return matches

    def _parse_date_heading(self, heading):
        heading = re.sub(r"\s+Today\s*$", "", heading).strip()

        try:
            return datetime.strptime(heading, "%a, %B %d, %Y").date()
        except ValueError:
            return None

    def _get_match_item_date_time(self, match, match_date):
        if match_date is None:
            return None

        time_element = match.find("div", class_="match-item-time")

        if not time_element:
            return None

        time_text = time_element.get_text(" ", strip=True)

        try:
            match_time = datetime.strptime(time_text, "%I:%M %p").time()
        except ValueError:
            return None

        return datetime.combine(match_date, match_time)

    def _is_upcoming_match(self, match):
        status = match.find("div", class_="ml-status")

        if not status:
            return False

        return status.get_text(" ", strip=True).lower() == "upcoming"

    def _get_match_item_team_names(self, match):
        teams = []

        for team in match.find_all("div", class_="match-item-vs-team-name"):
            name = team.find("div", class_="text-of")
            teams.append(self._clean_team_name(name or team))

        return teams

    def _get_matches_with_bookmaker_odds(self, matches):
        matches_with_odds = []

        with ThreadPoolExecutor(max_workers=self.max_workers) as executor:
            futures = {
                executor.submit(self._add_bookmaker_odds, match): match
                for match in matches
            }

            for index, future in enumerate(as_completed(futures), start=1):
                try:
                    match = future.result()
                except Exception as error:
                    source_match = futures[future]
                    print("Could not scrape odds for " + source_match["match_link"] + ": " + str(error))
                    continue

                print(
                    "Checking bookmaker odds on VLR match pages: " +
                    str(index) + "/" + str(len(matches)) + "     ",
                    end="\r",
                    flush=True,
                )

                if match:
                    matches_with_odds.append(match)

        if matches:
            print()

        return sorted(matches_with_odds, key=lambda match: match["match_link"])

    def _add_bookmaker_odds(self, match):
        soup = BeautifulSoup(self._get_html(match["match_link"]), "html.parser")
        bookmaker_odds = self._get_bookmaker_odds(soup)

        if not bookmaker_odds:
            return None

        return {
            "match_link": match["match_link"],
            "date_time": match.get("date_time"),
            "bookmaker": bookmaker_odds["bookmaker"],
            "team_1_odds": bookmaker_odds["odds"][0],
            "team_2_odds": bookmaker_odds["odds"][1],
        }

    def _get_bookmaker_odds(self, soup):
        bookmaker_candidates = []

        for index, bet_item in enumerate(soup.find_all("a", class_="match-bet-item")):
            if "mod-noodds" in bet_item.get("class", []):
                continue

            odds = []

            for odd in bet_item.find_all("span", class_="match-bet-item-odds"):
                odd_value = self._parse_odd(odd.get_text(" ", strip=True))

                if odd_value is not None:
                    odds.append(odd_value)

            if len(odds) < 2:
                continue

            bookmaker = self._get_bookmaker_key(bet_item)
            bookmaker_candidates.append({
                "bookmaker": bookmaker,
                "odds": odds[:2],
                "priority": self._get_bookmaker_priority_index(bookmaker, bet_item),
                "index": index,
            })

        if not bookmaker_candidates:
            return None

        return min(bookmaker_candidates, key=lambda candidate: (candidate["priority"], candidate["index"]))

    def _get_bookmaker_priority(self, bookmaker_key, bookmaker_priority):
        if bookmaker_priority is None:
            bookmaker_priority = [bookmaker_key, "rainbet"]

        priority = []
        seen_bookmakers = set()

        for bookmaker in bookmaker_priority:
            bookmaker = self._normalize_bookmaker_key(bookmaker)

            if not bookmaker or bookmaker in seen_bookmakers:
                continue

            seen_bookmakers.add(bookmaker)
            priority.append(bookmaker)

        return priority or ["thunderpick", "rainbet"]

    def _get_bookmaker_priority_index(self, bookmaker, bet_item):
        bookmaker_text = self._get_bookmaker_search_text(bet_item)

        for index, priority_bookmaker in enumerate(self.bookmaker_priority):
            if priority_bookmaker == bookmaker or priority_bookmaker in bookmaker_text:
                return index

        return len(self.bookmaker_priority)

    def _get_bookmaker_key(self, bet_item):
        for image in bet_item.find_all("img"):
            for image_class in image.get("class", []):
                if image_class.startswith("mod-") and image_class != "mod-noodds":
                    return self._normalize_bookmaker_key(image_class[4:])

        for image in bet_item.find_all("img"):
            image_source = image.get("src") or ""
            image_source_parts = re.split(r"[/._-]+", image_source)

            for part in reversed(image_source_parts):
                bookmaker = self._normalize_bookmaker_key(part)

                if bookmaker and bookmaker not in ("png", "jpg", "jpeg", "webp", "svg"):
                    return bookmaker

        href = bet_item.get("href") or ""
        href_parts = re.split(r"[/._?&=-]+", href)
        ignored_href_parts = {"http", "https", "www", "com", "gg", "net", "org"}

        for part in href_parts:
            bookmaker = self._normalize_bookmaker_key(part)

            if bookmaker and bookmaker not in ignored_href_parts:
                return bookmaker

        return None

    def _get_bookmaker_search_text(self, bet_item):
        searchable_values = []

        for image in bet_item.find_all("img"):
            searchable_values.extend(image.get("class", []))
            searchable_values.append(image.get("src") or "")
            searchable_values.append(image.get("alt") or "")
            searchable_values.append(image.get("title") or "")

        searchable_values.append(bet_item.get("href") or "")
        searchable_values.append(bet_item.get_text(" ", strip=True))

        return self._normalize_bookmaker_key(" ".join(searchable_values))

    def _normalize_bookmaker_key(self, value):
        return re.sub(r"[^a-z0-9]+", "", str(value).lower())

    def _parse_odd(self, value):
        try:
            odd = float(value)
        except (TypeError, ValueError):
            return None

        if 1.01 <= odd <= 100.0:
            return odd

        return None

    def _clean_team_name(self, element):
        return re.sub(r"\s+", " ", element.get_text(" ", strip=True)).strip()

    def _print_vig_stats(self, matches):
        Bookkeeper().keep_odds_pairs(matches)

        vigs = [
            self._calculate_vig(match["team_1_odds"], match["team_2_odds"])
            for match in matches
        ]

        if not vigs:
            print("Average vig: 0.0%")
            print("Vig standard deviation: 0.0%")
            return

        average_vig = sum(vigs) / len(vigs)
        standard_deviation = statistics.pstdev(vigs)

        print("Average vig: " + str(round(average_vig * 100, 3)) + "%")
        print("Vig standard deviation: " + str(round(standard_deviation * 100, 3)) + "%")

    def _calculate_vig(self, team_1_odds, team_2_odds):
        return (1 / team_1_odds) + (1 / team_2_odds) - 1

    @cache
    def _get_html(self, link):
        for attempt in range(3):
            try:
                request = Request(link, headers={"User-Agent": "Mozilla/5.0"})
                return urlopen(request, timeout=30).read().decode("utf-8")
            except Exception:
                if attempt == 2:
                    raise

                time.sleep(2)


if __name__ == "__main__":
    searcher = VlrSearcher()

    for match_data in searcher.scrape_matches():
        print(match_data)
