#
# Copyright (c) 2019 ETH Zurich
# This Source Code Form is subject to the terms of the Mozilla Public
# License, v. 2.0. If a copy of the MPL was not distributed with this
# file, You can obtain one at http://mozilla.org/MPL/2.0/.
#


#@ config: allocation


#@ invariant: sum(allocated[wei]()) == 0


@public
def foo():
    #:: ExpectedOutput(offer.failed:offer.not.injective)
    #@ foreach({i: uint256}, offer(i % 2, i % 2, to=ZERO_ADDRESS, times=i))
    pass


@public
def bar():
    #@ foreach({i: uint256}, offer(i % 2, i % 2, to=ZERO_ADDRESS, times=0))
    pass
