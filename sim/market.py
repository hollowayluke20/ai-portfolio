import datetime
import random


class Market:
    def __init__(self, tickers, seed, scenario):
        self.tickers, self.scenario, self.rng = list(tickers), scenario, random.Random(seed)
        self.values = {ticker: round(self.rng.uniform(50, 150), 2) for ticker in tickers}
        self.day, self.sessions, self.delisted = datetime.date(2026, 1, 1), 0, set()

    def advance(self):
        self.day += datetime.timedelta(days=1)
        while self.day.weekday() > 4: self.day += datetime.timedelta(days=1)
        self.sessions += 1
        for ticker, value in list(self.values.items()):
            if ticker in self.delisted: continue
            factor = 1 + self.rng.uniform(-.01, .01)
            if self.scenario == "crash" and 5 <= self.sessions < 15: factor *= .95
            if self.scenario == "gap" and ticker == self.tickers[0] and self.sessions == 5: factor = .5
            if self.scenario == "zero" and ticker == self.tickers[0]: factor *= .9
            if self.scenario == "meltup" and ticker == self.tickers[0] and self.sessions < 25: factor *= 1.05
            if self.scenario == "delist" and ticker == self.tickers[0] and self.sessions == 10: self.delisted.add(ticker); continue
            self.values[ticker] = round(max(.01, value * factor), 2)
        return self.day

    def price(self, ticker):
        if ticker in self.delisted or (self.scenario == "halt" and ticker == self.tickers[0] and 5 <= self.sessions < 10): return None
        return self.values[ticker]

    def is_delisted(self, ticker): return ticker in self.delisted
    def today(self): return self.day
