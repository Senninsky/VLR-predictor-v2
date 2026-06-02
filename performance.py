# Performance
class Performance:
    def __init__(self, r, acs, k, d, a, pm, kast, adr, hs, fk, fd, fpm):
        self.r = r
        self.acs = acs
        self.k = k
        self.d = d
        self.a = a
        self.pm = pm
        self.kast = kast
        self.adr = adr
        self.hs = hs
        self.fk = fk
        self.fd = fd
        self.fpm = fpm

    def __str__(self):
        return (
            f"{self._show(self.r):>5}"
            f"{self._show(self.acs):>6}"
            f"{self._show(self.k):>5}"
            f"{self._show(self.d):>5}"
            f"{self._show(self.a):>5}"
            f"{self._show(self.pm):>5}"
            f"{self._show(self.kast):>7}"
            f"{self._show(self.adr):>6}"
            f"{self._show(self.hs):>6}"
            f"{self._show(self.fk):>5}"
            f"{self._show(self.fd):>5}"
            f"{self._show(self.fpm):>5}"
        )

    def _show(self, value):
        if value is None:
            return "-"

        return value
