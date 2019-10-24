#
# Copyright (c) 2019 ETH Zurich
# This Source Code Form is subject to the terms of the Mozilla Public
# License, v. 2.0. If a copy of the MPL was not distributed with this
# file, You can obtain one at http://mozilla.org/MPL/2.0/.
#


#@ interface


#@ ensures: implies(i <= 0, not success())
#@ ensures: implies(success(), result() == i)
@public
def foo(i: int128) -> int128:
    raise "Not implemented"


#@ ensures: implies(success(), result() == u)
@public
def bar(u: uint256) -> uint256:
    raise "Not implemented"
