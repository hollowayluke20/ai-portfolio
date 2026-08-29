class FakeBroker:
    def __init__(self, cash, market): self.cash, self.market, self.book, self.orders = cash, market, {}, []
    def account(self):
        equity = self.cash + sum(p['qty'] * (self.market.price(t) or p['last']) for t,p in self.book.items())
        committed = sum(o['notional'] for o in self.orders if o['side'] == 'buy')
        return {'cash': round(self.cash,2), 'equity': round(equity,2), 'buying_power': round(4*equity-committed,2), 'status':'ACTIVE', 'currency':'USD'}
    def positions(self):
        out=[]
        for t,p in list(self.book.items()):
            if self.market.is_delisted(t): self.cash += p['qty']*p['last']; del self.book[t]; continue
            price=self.market.price(t) or p['last']; p['last']=price; out.append({'symbol':t,'name':t,'qty':p['qty'],'avg_entry_price':p['avg'],'current_price':price,'market_value':round(p['qty']*price,2),'unrealized_pl':round(p['qty']*(price-p['avg']),2)})
        return out
    def open_orders(self): return list(self.orders)
    def submit(self,symbol,side,notional):
        if self.market.price(symbol) is None: raise ValueError('ticker unavailable')
        order={'order_id':str(len(self.orders)+1),'symbol':symbol,'side':side,'notional':float(notional),'status':'accepted','filled_qty':0.0}; self.orders.append(order); return dict(order)
    def settle(self):
        for o in self.orders:
            price=self.market.price(o['symbol'])
            if price is None: continue
            qty=o['notional']/price
            if o['side']=='buy':
                p=self.book.setdefault(o['symbol'],{'qty':0,'avg':price,'last':price}); p['avg']=(p['avg']*p['qty']+o['notional'])/(p['qty']+qty); p['qty']+=qty; self.cash-=o['notional']
            else:
                p=self.book[o['symbol']]; sell=min(qty,p['qty']); p['qty']-=sell; self.cash+=sell*price
            o['filled_qty']=qty; o['status']='filled'
        self.orders=[o for o in self.orders if o['status']!='filled']
