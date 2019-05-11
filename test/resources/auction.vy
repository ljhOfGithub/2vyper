
beneficiary: public(address)
auctionStart: public(timestamp)
auctionEnd: public(timestamp)

highestBidder: public(address)
highestBid: public(wei_value)

ended: public(bool)

pendingReturns: public(map(address, wei_value))


#@ invariant: implies(block.timestamp < self.auctionEnd, not self.ended)
#@ invariant: implies(not self.ended, sum(self.pendingReturns) + self.highestBid <= self.balance)
#@ invariant: implies(self.ended, sum(self.pendingReturns) <= self.balance)

#@ invariant: self.highestBid >= old(self.highestBid)
#@ invariant: implies(self.ended, self.highestBid == old(self.highestBid) and self.highestBidder == old(self.highestBidder))
#@ invariant: implies(old(msg.value) > old(self.highestBid), old(msg.sender) == self.highestBidder)

#@ invariant: not (not self.ended and old(self.ended))
#@ invariant: implies(not self.ended and self.balance < old(self.balance), old(self.balance) - self.balance <= old(self.pendingReturns[msg.sender]))


@public
def __init__(_beneficiary: address, _bidding_time: timedelta):
    self.beneficiary = _beneficiary
    self.auctionStart = block.timestamp
    self.auctionEnd = self.auctionStart + _bidding_time


#@ ensures: implies(success(), self.highestBid > old(self.highestBid))
@public
@payable
def bid():
    assert block.timestamp < self.auctionEnd
    assert msg.value > self.highestBid
    self.pendingReturns[self.highestBidder] += self.highestBid
    self.highestBidder = msg.sender
    self.highestBid = msg.value


#@ ensures: implies(self.balance <= old(self.balance), self.balance - old(self.balance) <= old(self.pendingReturns[msg.sender]))
@public
def withdraw():
    pending_amount: wei_value = self.pendingReturns[msg.sender]
    self.pendingReturns[msg.sender] = 0
    send(msg.sender, pending_amount)


@public
def endAuction():
    assert block.timestamp >= self.auctionEnd
    assert not self.ended

    self.ended = True

    send(self.beneficiary, self.highestBid)
