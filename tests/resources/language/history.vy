#
# Copyright (c) 2019 ETH Zurich
# This Source Code Form is subject to the terms of the Mozilla Public
# License, v. 2.0. If a copy of the MPL was not distributed with this
# file, You can obtain one at http://mozilla.org/MPL/2.0/.
#

counter: int128

#:: Label(INC)
#@ invariant: old(self.counter) <= self.counter

@public
def increment():
    self.counter += 1

#:: ExpectedOutput(invariant.violated:assertion.false, INC)
@public
def decrease():
    self.counter -= 1