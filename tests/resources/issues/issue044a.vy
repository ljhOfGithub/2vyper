#
# Copyright (c) 2020 ETH Zurich
# This Source Code Form is subject to the terms of the Mozilla Public
# License, v. 2.0. If a copy of the MPL was not distributed with this
# file, You can obtain one at http://mozilla.org/MPL/2.0/.
#

#:: ExpectedOutput(invalid.program:invariant.call)
#@ invariant: offer(1, 1, to=ZERO_ADDRESS, times=1) == offer(1, 1, to=ZERO_ADDRESS, times=1)

@public
def foo():
    pass
