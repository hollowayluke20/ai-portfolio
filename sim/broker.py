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

    def close(self, symbol):
        """Liquidate a whole position, mirroring DELETE /v2/positions.

        NOT a notional sell of its market value. `positions()` rounds
        market_value to the cent, so a sell for exactly that amount settles
        into marginally fewer shares than are held, and the remainder survives
        as a fractional dust position that never dies - then keeps tripping
        stop-losses and "liquidate the dust" sells for the rest of the run.
        Apple was sold five times in one 2025 replay before this existed.

        Production has always closed by position rather than by dollars (ADR
        0003, and the fix on 2026-08-29 after $25 of bitcoin found the same
        edge live). The simulator being more forgiving than the real broker is
        exactly how it hid this.
        """
        if symbol not in self.book: raise ValueError(f'no position in {symbol}')
        if self.market.price(symbol) is None: raise ValueError('ticker unavailable')
        order={'order_id':str(len(self.orders)+1),'symbol':symbol,'side':'sell','notional':None,'close':True,'status':'accepted','filled_qty':0.0}
        self.orders.append(order); return dict(order)

    def settle(self):
        for o in self.orders:
            price=self.market.price(o['symbol'])
            if price is None: continue
            if o.get('close'):
                p=self.book.pop(o['symbol'],None)
                if p: self.cash+=p['qty']*price; o['filled_qty']=p['qty']
                o['status']='filled'; continue
            qty=o['notional']/price
            if o['side']=='buy':
                p=self.book.setdefault(o['symbol'],{'qty':0,'avg':price,'last':price}); p['avg']=(p['avg']*p['qty']+o['notional'])/(p['qty']+qty); p['qty']+=qty; self.cash-=o['notional']
            else:
                p=self.book[o['symbol']]; sell=min(qty,p['qty']); p['qty']-=sell; self.cash+=sell*price
                # A partial sell that leaves less than a hundredth of a share
                # is dust, not a holding. Left in the book it reads as a live
                # position forever.
                if p['qty']<1e-2: self.cash+=p['qty']*price; del self.book[o['symbol']]
            o['filled_qty']=qty; o['status']='filled'
        self.orders=[o for o in self.orders if o['status']!='filled']
