from sim.market import Market
from sim.broker import FakeBroker

def test_seed_and_weekends():
    a,b=Market(['A'],7,'calm'),Market(['A'],7,'calm')
    assert [a.advance() for _ in range(5)] == [b.advance() for _ in range(5)]
    assert all(a.today().weekday()<5 for _ in [0])

def test_queued_order_fills_at_next_price():
    market=Market(['A'],7,'calm'); broker=FakeBroker(1000,market); broker.submit('A','buy',100)
    assert not broker.positions() and broker.account()['cash']==1000
    market.advance(); broker.settle(); assert broker.positions()
