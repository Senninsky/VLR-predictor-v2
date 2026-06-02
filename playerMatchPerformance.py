class PlayerMatchPerformance:
    def __init__(self, player, performance):
        self.player = player
        self.performance = performance

        self.player.performances.append(self.performance)

    def __str__(self):
        return f"{self.player}{self.performance}"
