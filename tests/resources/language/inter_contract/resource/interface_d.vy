#
# Copyright (c) 2020 ETH Zurich
# This Source Code Form is subject to the terms of the Mozilla Public
# License, v. 2.0. If a copy of the MPL was not distributed with this
# file, You can obtain one at http://mozilla.org/MPL/2.0/.
#

#@ config: allocation

#@ interface

#@ resource: d()

#@ invariant: forall({a: address}, allocated(a) == 0)
#@ invariant: forall({a: address}, allocated[d](a) == 0)

@public
def foo():
    raise "Not implemented"
