# Importations
from performance import Performance
from player import Player
from playerMatchPerformance import PlayerMatchPerformance

# Team
class Team:
    def __init__(self, score, player_table=None):
        self.score = score
        self.players = []

        if player_table:
            players = self._get_players_from_table(player_table)
            if len(players) == 5:
                self.players = players

    def _get_players_from_table(self, table):
        players = []
        rows = table.find_all("tr")

        for row in rows:
            columns = row.find_all("td")
            if len(columns) == 0:
                continue

            player_anchor = columns[0].find("a")
            if not player_anchor:
                continue

            player_link = player_anchor["href"]
            player_id = player_link.split("/")[2]
            name = columns[0].get_text(" ", strip=True)
            r = self._get_first_value(columns[2])
            acs = self._get_first_value(columns[3])
            k = self._get_first_value(columns[4])
            d = self._get_first_value(columns[5])
            a = self._get_first_value(columns[6])
            pm = self._get_first_value(columns[7])
            kast = self._get_first_value(columns[8])
            adr = self._get_first_value(columns[9])
            hs = self._get_first_value(columns[10])
            fk = self._get_first_value(columns[11])
            fd = self._get_first_value(columns[12])
            fpm = self._get_first_value(columns[13])

            player = Player(player_id, name)
            performance = Performance(r, acs, k, d, a, pm, kast, adr, hs, fk, fd, fpm)
            players.append(PlayerMatchPerformance(player, performance))

        return players

    def _get_first_value(self, column):
        both_value = column.find(class_="mod-both")
        if both_value:
            return both_value.get_text(strip=True)

        for value in column.get_text(" ", strip=True).split():
            if value != "/":
                return value

    def __str__(self):
        lines = [f"Score: {self.score}"]
        lines.append("ID      Player              R   ACS    K    D    A   +/-   KAST   ADR   HS%   FK   FD  +/-")

        for player in self.players:
            lines.append(str(player))

        return "\n".join(lines)
