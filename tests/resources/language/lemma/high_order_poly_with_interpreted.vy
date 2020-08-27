#
# Copyright (c) 2020 ETH Zurich
# This Source Code Form is subject to the terms of the Mozilla Public
# License, v. 2.0. If a copy of the MPL was not distributed with this
# file, You can obtain one at http://mozilla.org/MPL/2.0/.
#

#@ ensures: success() ==> result() <= 63362376
#@ ensures: success() ==> x >= 4
@public
@constant
def get_y(x:uint256) -> uint256:
    assert x <= 400
    #@ lemma_assert interpreted(400 * 400 * 400 - 4 * 400 * 400 + 6 * 400 - 24 == 63362376)
    #@ lemma_assert interpreted((400 - 4) * (400 * 400) + 6 * 400 - 24 == 63362376)
    #@ lemma_assert x * x * x - 4 * x * x + 6 * x - 24 == x * (x * x) - 4 * (x * x) + 6 * x - 24
    #@ lemma_assert x * (x * x) - 4 * (x * x) + 6 * x - 24 == (x - 4) * (x * x) + 6 * x - 24
    #@ lemma_assert x >= 4 ==> x * x * x - 4 * x * x + 6 * x - 24 <= 63362376
    #@ lemma_assert interpreted(3 * 3 * 3 - 4 * 3 * 3 + 6 * 3 - 24 < 0)
    #@ lemma_assert x < 4 ==> x * x * x - 4 * x * x + 6 * x - 24 < 0
    #@ lemma_assert interpreted(6 * x == 4 * x + 2 * x) and interpreted(2 * x == x + x)
    return x * x * x - 4 * x * x + 6 * x - 24