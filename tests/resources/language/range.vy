#
# Copyright (c) 2019 ETH Zurich
# This Source Code Form is subject to the terms of the Mozilla Public
# License, v. 2.0. If a copy of the MPL was not distributed with this
# file, You can obtain one at http://mozilla.org/MPL/2.0/.
#


#@ invariant: range(5)[2] == 2
#@ invariant: range(1, 1 + 6)[2] == 3
#@ invariant: len(range(12)) == 12


@public
def __init__():
    pass