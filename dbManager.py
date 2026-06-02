import sqlite3
from match import Match
from performance import Performance
from player import Player
from playerMatchPerformance import PlayerMatchPerformance
from team import Team


class DbManager:
    def __init__(self):
        self.db = "vlr_data.db"
        self._create_tables()

    def insert_match(self, match):
        connection = sqlite3.connect(self.db)
        cursor = connection.cursor()

        cursor.execute(
            """
            INSERT OR REPLACE INTO matches (
                match_id,
                date,
                hour,
                team_1_score,
                team_2_score,
                has_player_stats
            )
            VALUES (?, ?, ?, ?, ?, ?)
            """,
            (
                match.id,
                match.date,
                match.hour,
                match.team_1.score,
                match.team_2.score,
                match.has_player_stats,
            ),
        )

        for odds in match.odds:
            cursor.execute(
                """
                INSERT OR IGNORE INTO match_odds (match_id, odds)
                VALUES (?, ?)
                """,
                (match.id, odds),
            )

        self._insert_team_players(cursor, match.id, 1, match.team_1.players)
        self._insert_team_players(cursor, match.id, 2, match.team_2.players)

        connection.commit()
        connection.close()

    def is_match_in_db(self, match_id):
        connection = sqlite3.connect(self.db)
        cursor = connection.cursor()

        cursor.execute(
            """
            SELECT 1 FROM matches
            WHERE match_id = ?
            """,
            (match_id,),
        )

        match = cursor.fetchone()
        connection.close()

        return match is not None
    
    def get_match_amount(self):
        connection = sqlite3.connect(self.db)
        cursor = connection.cursor()

        cursor.execute("SELECT COUNT(*) FROM matches")
        amount = cursor.fetchone()[0]

        connection.close()
        return amount

    def get_match_with_odds_amount(self):
        connection = sqlite3.connect(self.db)
        cursor = connection.cursor()

        cursor.execute("SELECT COUNT(DISTINCT match_id) FROM match_odds")
        amount = cursor.fetchone()[0]

        connection.close()
        return amount
    
    def get_bo1_match_amount(self):
        connection = sqlite3.connect(self.db)
        cursor = connection.cursor()

        cursor.execute(
            """
            SELECT COUNT(*) FROM matches
            WHERE team_1_score >= 13
               OR team_2_score >= 13
               OR (team_1_score = 1 AND team_2_score = 0)
               OR (team_1_score = 0 AND team_2_score = 1)
            """
        )
        amount = cursor.fetchone()[0]

        connection.close()
        return amount
    
    def rescrape_missing_player_stats(self):
        matches_without_player_stats = self._get_matches_without_player_stats()
        amount = len(matches_without_player_stats)

        for i, match_data in enumerate(matches_without_player_stats):
            match_id, date, hour = match_data
            print(f"Rescraping missing player stats: {i + 1}/{amount}", end="\r", flush=True)
            match = Match(date, hour, match_id)
            self.insert_match(match)

        print()

    def get_player_performances(self, player_id, date, time, amount):
        connection = sqlite3.connect(self.db)
        cursor = connection.cursor()

        cursor.execute(
            """
            SELECT
                performances.match_id,
                performances.r,
                performances.acs,
                performances.k,
                performances.d,
                performances.a,
                performances.pm,
                performances.kast,
                performances.adr,
                performances.hs,
                performances.fk,
                performances.fd,
                performances.fpm
            FROM performances
            JOIN matches ON matches.match_id = performances.match_id
            WHERE performances.player_id = ?
              AND (
                substr(matches.date, 7, 4) || '-' ||
                substr(matches.date, 4, 2) || '-' ||
                substr(matches.date, 1, 2) || ' ' ||
                matches.hour
              ) < (
                substr(?, 7, 4) || '-' ||
                substr(?, 4, 2) || '-' ||
                substr(?, 1, 2) || ' ' ||
                ?
              )
            ORDER BY
                substr(matches.date, 7, 4) || '-' ||
                substr(matches.date, 4, 2) || '-' ||
                substr(matches.date, 1, 2) || ' ' ||
                matches.hour DESC
            LIMIT ?
            """,
            (player_id, date, date, date, time, amount),
        )

        player_performances = []
        for row in cursor.fetchall():
            match_id = row[0]
            performance = Performance(
                row[1],
                row[2],
                row[3],
                row[4],
                row[5],
                row[6],
                row[7],
                row[8],
                row[9],
                row[10],
                row[11],
                row[12],
            )
            player_performances.append((match_id, performance))

        connection.close()

        return player_performances
    
    def get_matches(self):
        connection = sqlite3.connect(self.db)
        cursor = connection.cursor()

        cursor.execute(
            """
            SELECT
                match_id,
                date,
                hour,
                team_1_score,
                team_2_score,
                has_player_stats
            FROM matches
            """
        )

        matches = []
        for row in cursor.fetchall():
            match = object.__new__(Match)
            match.id = row[0]
            match.date = row[1]
            match.hour = row[2]
            match.has_player_stats = bool(row[5])
            match.odds = self._get_match_odds(cursor, match.id)
            match.team_1 = Team(row[3])
            match.team_2 = Team(row[4])
            match.team_1.players = self._get_match_players(cursor, match.id, 1)
            match.team_2.players = self._get_match_players(cursor, match.id, 2)

            matches.append(match)

        connection.close()

        return matches

    def _get_matches_without_player_stats(self):
        connection = sqlite3.connect(self.db)
        cursor = connection.cursor()

        cursor.execute(
            """
            SELECT match_id, date, hour FROM matches
            WHERE has_player_stats = 0
            """
        )

        matches_without_player_stats = cursor.fetchall()
        connection.close()

        return matches_without_player_stats

    def _get_match_odds(self, cursor, match_id):
        cursor.execute(
            """
            SELECT odds FROM match_odds
            WHERE match_id = ?
            """,
            (match_id,),
        )

        odds = []
        for row in cursor.fetchall():
            odds.append(row[0])

        return odds

    def _get_match_players(self, cursor, match_id, team_number):
        cursor.execute(
            """
            SELECT
                players.player_id,
                players.name,
                performances.r,
                performances.acs,
                performances.k,
                performances.d,
                performances.a,
                performances.pm,
                performances.kast,
                performances.adr,
                performances.hs,
                performances.fk,
                performances.fd,
                performances.fpm
            FROM match_players
            JOIN players ON players.player_id = match_players.player_id
            JOIN performances
                ON performances.match_id = match_players.match_id
                AND performances.player_id = match_players.player_id
            WHERE match_players.match_id = ?
              AND match_players.team_number = ?
            """,
            (match_id, team_number),
        )

        players = []
        for row in cursor.fetchall():
            player = Player(row[0], row[1])
            performance = Performance(
                row[2],
                row[3],
                row[4],
                row[5],
                row[6],
                row[7],
                row[8],
                row[9],
                row[10],
                row[11],
                row[12],
                row[13],
            )
            players.append(PlayerMatchPerformance(player, performance))

        return players

    def _create_tables(self):
        connection = sqlite3.connect(self.db)
        cursor = connection.cursor()

        cursor.execute(
            """
            CREATE TABLE IF NOT EXISTS matches (
                match_id TEXT PRIMARY KEY,
                date TEXT,
                hour TEXT,
                team_1_score INTEGER,
                team_2_score INTEGER,
                has_player_stats INTEGER
            )
            """
        )

        cursor.execute(
            """
            CREATE TABLE IF NOT EXISTS players (
                player_id TEXT PRIMARY KEY,
                name TEXT
            )
            """
        )

        cursor.execute(
            """
            CREATE TABLE IF NOT EXISTS match_players (
                match_id TEXT,
                player_id TEXT,
                team_number INTEGER,
                PRIMARY KEY (match_id, player_id)
            )
            """
        )

        cursor.execute(
            """
            CREATE TABLE IF NOT EXISTS performances (
                match_id TEXT,
                player_id TEXT,
                r TEXT,
                acs TEXT,
                k TEXT,
                d TEXT,
                a TEXT,
                pm TEXT,
                kast TEXT,
                adr TEXT,
                hs TEXT,
                fk TEXT,
                fd TEXT,
                fpm TEXT,
                PRIMARY KEY (match_id, player_id)
            )
            """
        )

        cursor.execute(
            """
            CREATE TABLE IF NOT EXISTS match_odds (
                match_id TEXT,
                odds REAL,
                PRIMARY KEY (match_id, odds)
            )
            """
        )

        cursor.execute(
            """
            CREATE INDEX IF NOT EXISTS idx_performances_player_id
            ON performances (player_id)
            """
        )

        connection.commit()
        connection.close()

    def _insert_team_players(self, cursor, match_id, team_number, team_players):
        for team_player in team_players:
            player = team_player.player
            performance = team_player.performance

            cursor.execute(
                """
                INSERT OR REPLACE INTO players (player_id, name)
                VALUES (?, ?)
                """,
                (player.id, player.name),
            )

            cursor.execute(
                """
                INSERT OR IGNORE INTO match_players (match_id, player_id, team_number)
                VALUES (?, ?, ?)
                """,
                (match_id, player.id, team_number),
            )

            cursor.execute(
                """
                INSERT OR IGNORE INTO performances (
                    match_id,
                    player_id,
                    r,
                    acs,
                    k,
                    d,
                    a,
                    pm,
                    kast,
                    adr,
                    hs,
                    fk,
                    fd,
                    fpm
                )
                VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
                """,
                (
                    match_id,
                    player.id,
                    performance.r,
                    performance.acs,
                    performance.k,
                    performance.d,
                    performance.a,
                    performance.pm,
                    performance.kast,
                    performance.adr,
                    performance.hs,
                    performance.fk,
                    performance.fd,
                    performance.fpm,
                ),
            )
