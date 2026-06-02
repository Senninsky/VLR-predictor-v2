import json
import re
import statistics
import time
from difflib import SequenceMatcher
from datetime import datetime, timedelta
from functools import cache
from urllib.parse import urljoin
from urllib.request import Request, urlopen
from zoneinfo import ZoneInfo

from bs4 import BeautifulSoup


class ThunderpickScraper:
    def __init__(
        self,
        url="https://thunderpick.io/esports/valorant",
        timezone="Europe/Brussels",
        headless=True,
        timeout_ms=30000,
        settle_ms=5000,
        tab=None,
        allow_json_fallback=False,
        debug_text_filename="thunderpick_debug_text.txt",
        only_today_and_tomorrow=True,
        block_cooldown_filename="thunderpick_block_cooldown.json",
        block_cooldown_minutes=60,
    ):
        self.url = url
        self.timezone = timezone
        self.headless = headless
        self.timeout_ms = timeout_ms
        self.settle_ms = settle_ms
        self.tab = tab
        self.allow_json_fallback = allow_json_fallback
        self.debug_text_filename = debug_text_filename
        self.only_today_and_tomorrow = only_today_and_tomorrow
        self.block_cooldown_filename = block_cooldown_filename
        self.block_cooldown_minutes = block_cooldown_minutes
        self.default_link = "https://www.vlr.gg/"

    def scrape_match_strings(self):
        self._raise_if_block_cooldown_active()
        match_strings = self._scrape_rendered_match_strings()

        if match_strings:
            print("Matches found on Thunderpick page: " + str(len(match_strings)))
            self._print_vig_stats(match_strings)
            return match_strings

        if self.allow_json_fallback:
            payloads = self._collect_json_payloads()
            match_data = self._extract_match_data(payloads)
            match_data = self._filter_matches_by_date(match_data)
            match_strings = [self._format_match_string(match) for match in match_data]

        print("Matches found on Thunderpick page: " + str(len(match_strings)))
        self._print_vig_stats(match_strings)

        return match_strings

    def snip(self):
        return self.scrape_match_strings()

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

    def _print_vig_stats(self, match_strings):
        vigs = self._get_vigs(match_strings)

        if not vigs:
            print("Average vig: 0.0%")
            print("Vig standard deviation: 0.0%")
            return

        average_vig = sum(vigs) / len(vigs)
        standard_deviation = statistics.pstdev(vigs)

        print("Average vig: " + str(round(average_vig * 100, 3)) + "%")
        print("Vig standard deviation: " + str(round(standard_deviation * 100, 3)) + "%")

    def _get_vigs(self, match_strings):
        vigs = []

        for match_string in match_strings:
            try:
                match_data = self._parse_match_string(match_string)
                vigs.append(self._calculate_vig(match_data["team_1_odds"], match_data["team_2_odds"]))
            except (IndexError, ValueError):
                continue

        return vigs

    def _calculate_vig(self, team_1_odds, team_2_odds):
        return (1 / team_1_odds) + (1 / team_2_odds) - 1

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
            teams = re.split(r"\s+[â€“-]\s+", text)

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
        text = text.replace("Ã¸", "o")
        text = text.replace("Ã¼", "u")
        text = text.replace("Ã¡", "a")
        text = text.replace("Ã©", "e")
        text = text.replace("Ã­", "i")
        text = text.replace("Ã³", "o")
        text = text.replace("Ãº", "u")
        text = re.sub(r"[^a-z0-9]+", " ", text)
        return " ".join(text.split())

    def _scrape_rendered_match_strings(self):
        try:
            from playwright.sync_api import sync_playwright
        except ImportError as error:
            raise RuntimeError(
                "Playwright is required for ThunderpickScraper. "
                "Install it with: pip install playwright && python -m playwright install chromium"
            ) from error

        with sync_playwright() as playwright:
            browser = playwright.chromium.launch(headless=self.headless)
            try:
                page = browser.new_page(viewport={"width": 1400, "height": 1200})
                page.goto(self.url, wait_until="domcontentloaded", timeout=self.timeout_ms)

                try:
                    page.wait_for_load_state("networkidle", timeout=self.timeout_ms)
                except Exception:
                    pass

                page.wait_for_timeout(self.settle_ms)
                self._ensure_expected_page(page)
                self._select_tab(page)
                self._wait_for_upcoming_text(page)

                page_texts = self._collect_rendered_page_texts(page)
                self._raise_if_blocked(page_texts)
                row_texts = self._collect_rendered_row_texts(page)
            finally:
                browser.close()

        matches = []
        seen = set()

        for row_text in self._get_candidate_rendered_match_texts(row_texts, page_texts):
            match = self._parse_rendered_row(row_text)

            if not match:
                continue

            key = (
                match["date"],
                match["event"],
                match["team_1"],
                match["team_2"],
                match["team_1_odds"],
                match["team_2_odds"],
            )

            if key in seen:
                continue

            seen.add(key)
            matches.append(match)

        matches = self._filter_matches_by_date(matches)
        match_strings = [self._format_match_string(match) for match in matches]

        if not match_strings:
            self._write_debug_text(page_texts)

        return match_strings

    def _filter_matches_by_date(self, matches):
        if not self.only_today_and_tomorrow:
            return matches

        allowed_dates = self._get_allowed_match_dates()
        filtered_matches = []

        for match in matches:
            match_date = self._parse_match_display_date(match.get("date"))

            if match_date in allowed_dates:
                filtered_matches.append(match)

        return filtered_matches

    def _get_allowed_match_dates(self):
        now = datetime.now(ZoneInfo(self.timezone))
        tomorrow = now + timedelta(days=1)

        return {
            (now.month, now.day),
            (tomorrow.month, tomorrow.day),
        }

    def _parse_match_display_date(self, display_date):
        if not isinstance(display_date, str):
            return None

        date_match = re.search(r"([A-Z][a-z]{2})\s+(\d{1,2}),\s+\d{2}:\d{2}", display_date)

        if not date_match:
            return None

        try:
            parsed_date = datetime.strptime(
                date_match.group(1) + " " + date_match.group(2),
                "%b %d",
            )
        except ValueError:
            return None

        return parsed_date.month, parsed_date.day

    def _get_candidate_rendered_match_texts(self, row_texts, page_texts):
        page_match_texts = []

        for page_text in page_texts:
            page_match_texts.extend(self._parse_upcoming_blocks_from_page_text(page_text))

        if page_match_texts:
            return page_match_texts

        for page_text in page_texts:
            page_match_texts.extend(self._parse_flat_upcoming_matches(page_text))

        if page_match_texts:
            return page_match_texts

        if self.tab in ("All", "Upcoming"):
            return []

        return row_texts

    def _select_tab(self, page):
        if not self.tab:
            return

        page.evaluate(
            """
            (tabName) => {
                const candidates = Array.from(document.querySelectorAll('button, a, [role="tab"], [data-testid]'));
                const tab = candidates.find((element) => {
                    const text = (element.innerText || '').trim();
                    return text === tabName || text.startsWith(tabName + ' ');
                });

                if (tab) {
                    tab.click();
                }
            }
            """,
            self.tab,
        )
        page.wait_for_timeout(1500)

    def _ensure_expected_page(self, page):
        if "valorant" in page.url.lower():
            return

        page.goto(self.url, wait_until="domcontentloaded", timeout=self.timeout_ms)

        try:
            page.wait_for_load_state("networkidle", timeout=self.timeout_ms)
        except Exception:
            pass

        page.wait_for_timeout(self.settle_ms)

    def _wait_for_upcoming_text(self, page):
        try:
            page.wait_for_function(
                "() => document.body && document.body.innerText.includes('Upcoming')",
                timeout=self.timeout_ms,
            )
        except Exception:
            pass

    def _write_debug_text(self, page_texts):
        if not self.debug_text_filename:
            return

        with open(self.debug_text_filename, "w", encoding="utf-8") as file:
            file.write("\n\n--- PAGE SNAPSHOT ---\n\n".join(page_texts))

        print("Thunderpick debug text written to: " + self.debug_text_filename)

    def _raise_if_blocked(self, page_texts):
        combined_text = "\n".join(page_texts).lower()

        if "you have been blocked" not in combined_text and "unable to access thunderpick.io" not in combined_text:
            return

        self._write_debug_text(page_texts)
        self._save_block_cooldown()
        raise RuntimeError(
            "Thunderpick blocked the automated browser request. "
            "The scraper cannot access the Valorant odds page right now without bypassing the site's protection. "
            "See thunderpick_debug_text.txt for the Cloudflare block message."
        )

    def _raise_if_block_cooldown_active(self):
        blocked_at = self._load_blocked_at()

        if blocked_at is None:
            return

        now = datetime.now(ZoneInfo(self.timezone))
        retry_at = blocked_at + timedelta(minutes=self.block_cooldown_minutes)

        if now >= retry_at:
            return

        raise RuntimeError(
            "Skipping Thunderpick request because the last attempt was blocked. "
            "Retry after " + retry_at.strftime("%Y-%m-%d %H:%M %Z") + "."
        )

    def _save_block_cooldown(self):
        if not self.block_cooldown_filename:
            return

        cooldown_data = {
            "blocked_at": datetime.now(ZoneInfo(self.timezone)).isoformat(),
            "url": self.url,
        }

        with open(self.block_cooldown_filename, "w", encoding="utf-8") as file:
            json.dump(cooldown_data, file, indent=2)

    def _load_blocked_at(self):
        if not self.block_cooldown_filename:
            return None

        try:
            with open(self.block_cooldown_filename, "r", encoding="utf-8") as file:
                cooldown_data = json.load(file)
        except (FileNotFoundError, json.JSONDecodeError):
            return None

        if cooldown_data.get("url") != self.url:
            return None

        blocked_at = cooldown_data.get("blocked_at")

        if not isinstance(blocked_at, str):
            return None

        try:
            parsed = datetime.fromisoformat(blocked_at)
        except ValueError:
            return None

        if parsed.tzinfo is None:
            return parsed.replace(tzinfo=ZoneInfo(self.timezone))

        return parsed

    def _collect_rendered_row_texts(self, page):
        row_texts = []
        seen = set()
        unchanged_scrolls = 0

        for _ in range(80):
            current_rows = page.locator('[data-testid^="match-table-row-"]').all_inner_texts()

            for row_text in current_rows:
                normalized = self._normalize_row_text(row_text)

                if normalized and normalized not in seen:
                    seen.add(normalized)
                    row_texts.append(normalized)

            did_scroll = page.evaluate(self._get_scroll_script())
            page.wait_for_timeout(300)

            if not did_scroll:
                unchanged_scrolls += 1
            else:
                unchanged_scrolls = 0

            if unchanged_scrolls >= 3:
                break

        return row_texts

    def _collect_rendered_page_texts(self, page):
        page_texts = []
        seen = set()
        unchanged_scrolls = 0

        page.evaluate("() => window.scrollTo(0, 0)")
        page.wait_for_timeout(500)

        for _ in range(80):
            page_text = self._normalize_row_text(page.locator("body").inner_text())

            if page_text and page_text not in seen:
                seen.add(page_text)
                page_texts.append(page_text)

            did_scroll = page.evaluate(self._get_scroll_script())
            page.wait_for_timeout(300)

            if not did_scroll:
                unchanged_scrolls += 1
            else:
                unchanged_scrolls = 0

            if unchanged_scrolls >= 3:
                break

        return page_texts

    def _get_scroll_script(self):
        return """
            () => {
                const rows = Array.from(document.querySelectorAll('[data-testid^="match-table-row-"]'));
                const scrollingElement = document.scrollingElement || document.documentElement;

                if (!rows.length) {
                    const before = scrollingElement.scrollTop;
                    scrollingElement.scrollBy(0, Math.floor(window.innerHeight * 0.85));
                    return scrollingElement.scrollTop !== before;
                }

                let element = rows[0].parentElement;

                while (element && element !== document.body) {
                    if (element.scrollHeight > element.clientHeight + 10) {
                        const before = element.scrollTop;
                        element.scrollBy(0, Math.floor(element.clientHeight * 0.85));

                        if (element.scrollTop !== before) {
                            return true;
                        }
                    }

                    element = element.parentElement;
                }

                const before = scrollingElement.scrollTop;
                scrollingElement.scrollBy(0, Math.floor(window.innerHeight * 0.85));
                return scrollingElement.scrollTop !== before;
            }
        """

    def _normalize_row_text(self, row_text):
        return "\n".join(line.strip() for line in row_text.splitlines() if line.strip())

    def _parse_upcoming_blocks_from_page_text(self, page_text):
        lines = self._normalize_row_text(page_text).splitlines()
        blocks = []
        current_block = []
        in_upcoming_section = False

        for line in lines:
            if line == "Live" or line.startswith("Live "):
                if current_block:
                    blocks.append("\n".join(current_block))

                in_upcoming_section = False
                current_block = []
                continue

            if line == "Upcoming" or line.startswith("Upcoming ") or self._is_date_heading(line):
                if current_block:
                    blocks.append("\n".join(current_block))

                in_upcoming_section = True
                current_block = []
                continue

            if not in_upcoming_section:
                continue

            if re.fullmatch(r"BO\d+(?:\s*(?:\|\s*)?[A-Z][a-z]{2}\s+\d{2},\s+\d{2}:\d{2})?", line):
                if current_block:
                    blocks.append("\n".join(current_block))

                current_block = [line]
                continue

            if current_block:
                current_block.append(line)

        if current_block:
            blocks.append("\n".join(current_block))

        return blocks

    def _parse_flat_upcoming_matches(self, page_text):
        text = " ".join(self._normalize_row_text(page_text).splitlines())
        upcoming_index = text.find(" Upcoming")

        if upcoming_index == -1:
            upcoming_index = text.find("Upcoming")

        if upcoming_index == -1:
            return []

        text = text[upcoming_index:]
        matches = []
        pattern = re.compile(
            r"BO\d+\s+"
            r"(?P<date>[A-Z][a-z]{2}\s+\d{2},\s+\d{2}:\d{2})\s+"
            r"(?P<event>.+?)\s+"
            r"(?P<team_1>[A-Za-z0-9][A-Za-z0-9 .'\-()&]+?)\s+"
            r"(?P<team_1_odds>\d+\.\d{2})\s+"
            r"vs\s+"
            r"(?P<team_2_odds>\d+\.\d{2})\s+"
            r"(?P<team_2>[A-Za-z0-9][A-Za-z0-9 .'\-()&]+?)"
            r"(?:\s+LIVE)?\s+\+\d+",
        )

        for match in pattern.finditer(text):
            matches.append("\n".join([
                match.group("date"),
                match.group("event").strip(),
                match.group("team_1").strip(),
                match.group("team_1_odds"),
                "vs",
                match.group("team_2_odds"),
                match.group("team_2").strip(),
            ]))

        return matches

    def _is_date_heading(self, line):
        return re.fullmatch(r"[A-Z][a-z]+,\s+[A-Z][a-z]+\s+\d+(?:st|nd|rd|th)?", line) is not None

    def _parse_rendered_row(self, row_text):
        lines = self._normalize_row_text(row_text).splitlines()

        if "vs" not in [line.lower() for line in lines]:
            return None

        odds_indexes = [
            index
            for index, line in enumerate(lines)
            if re.fullmatch(r"\d+(?:\.\d+)?", line) and self._is_valid_odd(line)
        ]

        if len(odds_indexes) < 2:
            return None

        first_odd_index = odds_indexes[0]
        second_odd_index = odds_indexes[1]
        date = self._find_rendered_date(lines)
        event = self._find_rendered_event(lines)
        team_1 = self._find_team_before_first_odd(lines, first_odd_index)
        team_2 = self._find_team_after_second_odd(lines, second_odd_index)

        if not all((date, event, team_1, team_2)):
            return None

        return {
            "date": date,
            "event": event,
            "team_1": team_1,
            "team_1_odds": float(lines[first_odd_index]),
            "team_2_odds": float(lines[second_odd_index]),
            "team_2": team_2,
        }

    def _find_rendered_date(self, lines):
        for line in lines:
            date_match = re.search(r"[A-Z][a-z]{2}\s+\d{2},\s+\d{2}:\d{2}", line)

            if date_match:
                return date_match.group(0)

        return None

    def _find_rendered_event(self, lines):
        for line in lines:
            if self._is_metadata_line(line):
                continue

            if self._is_odds_or_marker_line(line):
                continue

            return line

        return None

    def _find_team_before_first_odd(self, lines, first_odd_index):
        for line in reversed(lines[:first_odd_index]):
            if self._is_metadata_line(line) or self._is_odds_or_marker_line(line):
                continue

            return line

        return None

    def _find_team_after_second_odd(self, lines, second_odd_index):
        for line in lines[second_odd_index + 1:]:
            if self._is_metadata_line(line) or self._is_odds_or_marker_line(line):
                continue

            return line

        return None

    def _is_metadata_line(self, line):
        return (
            re.fullmatch(r"BO\d+", line) is not None
            or re.search(r"[A-Z][a-z]{2}\s+\d{2},\s+\d{2}:\d{2}", line) is not None
        )

    def _is_odds_or_marker_line(self, line):
        return (
            line.lower() == "vs"
            or line.upper() == "LIVE"
            or "|" in line
            or re.fullmatch(r"\+\d+", line) is not None
            or re.fullmatch(r"\d+", line) is not None
            or (re.fullmatch(r"\d+(?:\.\d+)?", line) is not None and self._is_valid_odd(line))
        )

    def _collect_json_payloads(self):
        try:
            from playwright.sync_api import sync_playwright
        except ImportError as error:
            raise RuntimeError(
                "Playwright is required for ThunderpickScraper. "
                "Install it with: pip install playwright && python -m playwright install chromium"
            ) from error

        payloads = []

        with sync_playwright() as playwright:
            browser = playwright.chromium.launch(headless=self.headless)
            page = browser.new_page()

            def collect_response(response):
                response_url = response.url.lower()

                if not self._is_relevant_response(response_url):
                    return

                try:
                    payloads.append(response.json())
                except Exception:
                    return

            page.on("response", collect_response)
            page.goto(self.url, wait_until="domcontentloaded", timeout=self.timeout_ms)
            try:
                page.wait_for_load_state("networkidle", timeout=self.timeout_ms)
            except Exception:
                pass

            page.wait_for_timeout(self.settle_ms)
            browser.close()

        return payloads

    def _is_relevant_response(self, response_url):
        if "thunderpick.io" not in response_url:
            return False

        return any(
            keyword in response_url
            for keyword in ("match", "market", "event", "sport", "competition", "betting")
        )

    def _extract_match_data(self, payloads):
        raw_matches = {}
        raw_markets = {}

        for payload in payloads:
            for item in self._walk(payload):
                if not isinstance(item, dict):
                    continue

                match = self._extract_match(item)

                if match:
                    raw_matches[match["id"]] = {**raw_matches.get(match["id"], {}), **match}

                market = self._extract_market(item)

                if market:
                    raw_markets.setdefault(market["match_id"], []).append(market)

        matches = []

        for match_id, match in raw_matches.items():
            odds = self._get_match_odds(match, raw_markets.get(match_id, []))

            if not odds:
                continue

            match["team_1_odds"] = odds[0]
            match["team_2_odds"] = odds[1]
            matches.append(match)

        return sorted(matches, key=lambda match: match.get("sort_date") or "")

    def _walk(self, value):
        yield value

        if isinstance(value, dict):
            for child in value.values():
                yield from self._walk(child)
        elif isinstance(value, list):
            for child in value:
                yield from self._walk(child)

    def _extract_match(self, item):
        teams = self._extract_teams(item)

        if not teams:
            return None

        match_id = self._first_value(item, ("id", "eventId", "matchId"))

        if match_id is None:
            return None

        if not self._looks_like_valorant_match(item):
            return None

        return {
            "id": str(match_id),
            "date": self._extract_date(item),
            "sort_date": self._first_value(item, ("startTime", "startDate", "date")),
            "event": self._extract_event_name(item),
            "team_1": teams[0],
            "team_2": teams[1],
            "best_of": self._first_value(item, ("bestOf", "bo", "format")),
            "inline_odds": self._extract_odds_from_item(item),
        }

    def _looks_like_valorant_match(self, item):
        text = json.dumps(item, default=str).lower()
        return "valorant" in text or '"gameid":76' in text.replace(" ", "")

    def _extract_teams(self, item):
        teams = item.get("teams")

        if isinstance(teams, dict):
            home = self._extract_name(teams.get("home"))
            away = self._extract_name(teams.get("away"))

            if home and away:
                return home, away

        if isinstance(teams, list) and len(teams) >= 2:
            team_names = [self._extract_name(team) for team in teams[:2]]

            if team_names[0] and team_names[1]:
                return team_names[0], team_names[1]

        home = self._extract_name(item.get("home") or item.get("homeTeam"))
        away = self._extract_name(item.get("away") or item.get("awayTeam"))

        if home and away:
            return home, away

        competitors = item.get("competitors") or item.get("participants")

        if isinstance(competitors, list) and len(competitors) >= 2:
            team_names = [self._extract_name(team) for team in competitors[:2]]

            if team_names[0] and team_names[1]:
                return team_names[0], team_names[1]

        return None

    def _extract_name(self, value):
        if isinstance(value, str):
            return value.strip()

        if not isinstance(value, dict):
            return None

        name = self._first_value(value, ("name", "displayName", "shortName", "title"))

        if isinstance(name, str):
            return name.strip()

        return None

    def _extract_event_name(self, item):
        competition = item.get("competition") or item.get("tournament") or item.get("league")
        name = self._extract_name(competition)

        if name:
            return name

        event_name = self._first_value(item, ("competitionName", "tournamentName", "leagueName", "eventName"))

        if isinstance(event_name, str) and event_name.strip():
            return event_name.strip()

        return "Thunderpick Valorant"

    def _extract_date(self, item):
        raw_date = self._first_value(item, ("startTime", "startDate", "date"))

        if not raw_date:
            return "Unknown date"

        if isinstance(raw_date, (int, float)):
            if raw_date > 100000000000:
                raw_date = raw_date / 1000

            date = datetime.fromtimestamp(raw_date, tz=ZoneInfo(self.timezone))
            return date.strftime("%b %d, %H:%M")

        if isinstance(raw_date, str):
            date = self._parse_datetime(raw_date)

            if date:
                return date.astimezone(ZoneInfo(self.timezone)).strftime("%b %d, %H:%M")

            return raw_date

        return str(raw_date)

    def _parse_datetime(self, value):
        normalized = value.replace("Z", "+00:00")

        try:
            date = datetime.fromisoformat(normalized)
        except ValueError:
            return None

        if date.tzinfo is None:
            return date.replace(tzinfo=ZoneInfo("UTC"))

        return date

    def _extract_market(self, item):
        match_id = self._first_value(item, ("eventId", "matchId"))

        if match_id is None:
            return None

        odds = self._extract_odds_from_item(item)

        if not odds:
            return None

        market_name = self._first_value(item, ("name", "marketName", "type", "translationId"))

        return {
            "match_id": str(match_id),
            "name": str(market_name or ""),
            "odds": odds,
        }

    def _get_match_odds(self, match, markets):
        if match.get("inline_odds"):
            return match["inline_odds"]

        preferred_market = self._find_winner_market(markets)

        if preferred_market:
            return preferred_market["odds"]

        if markets:
            return markets[0]["odds"]

        return None

    def _find_winner_market(self, markets):
        for market in markets:
            name = market["name"].lower()

            if any(keyword in name for keyword in ("winner", "moneyline", "match winner", "to win")):
                return market

        return None

    def _extract_odds_from_item(self, item):
        odds = []

        for value in self._walk(item):
            if not isinstance(value, dict):
                continue

            odd = self._first_value(value, ("odds", "price", "decimalOdds", "payoutOdds"))

            if not self._is_valid_odd(odd):
                continue

            status = str(self._first_value(value, ("status", "state")) or "").lower()

            if "suspend" in status or "lock" in status:
                continue

            odds.append(float(odd))

            if len(odds) == 2:
                return odds

        return None

    def _is_valid_odd(self, value):
        try:
            number = float(value)
        except (TypeError, ValueError):
            return False

        return 1.01 <= number <= 100.0

    def _first_value(self, item, keys):
        if not isinstance(item, dict):
            return None

        for key in keys:
            if key in item and item[key] is not None:
                return item[key]

        return None

    def _format_match_string(self, match):
        return "\n".join([
            match["date"],
            match["event"],
            match["team_1"],
            self._format_odd(match["team_1_odds"]),
            "vs",
            self._format_odd(match["team_2_odds"]),
            match["team_2"],
        ])

    def _format_odd(self, odd):
        return "{:.2f}".format(float(odd))

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
    scraper = ThunderpickScraper(headless=False)

    for match_string in scraper.scrape_match_strings():
        print(match_string)
        print()
