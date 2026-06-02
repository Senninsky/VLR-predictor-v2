# Importations

# Player
class Player:
    players = {}

    def __new__(cls, id, name):
        if id in cls.players:
            return cls.players[id]

        player = super().__new__(cls)
        cls.players[id] = player
        return player

    def __init__(self, id, name):
        if hasattr(self, "id"):
            return

        self.id = id
        self.name = name
        self.performances = []

    def __str__(self):
        return (
            f"{self._show(self.id):<8}"
            f"{self._show(self.name):<16}"
        )

    def _show(self, value):
        if value is None:
            return "-"

        return value
