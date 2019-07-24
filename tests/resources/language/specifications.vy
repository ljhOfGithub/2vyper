#
# Copyright (c) 2019 ETH Zurich
# This Source Code Form is subject to the terms of the Mozilla Public
# License, v. 2.0. If a copy of the MPL was not distributed with this
# file, You can obtain one at http://mozilla.org/MPL/2.0/.
#

#@ invariant: True

#@ ensures: implies(success(), result() == i + j)
#@ ensures: old(i) == i
#@ ensures: old(j) == j
@public
def foo(i: int128, j: int128) -> int128:
    return i + j

#:: ExpectedOutput(postcondition.violated:assertion.false)
#@ ensures: implies(success(), result() > 0)
@public
@constant
def bar(i: int128) -> int128:
    return -i