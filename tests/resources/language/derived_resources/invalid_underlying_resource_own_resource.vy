#
# Copyright (c) 2020 ETH Zurich
# This Source Code Form is subject to the terms of the Mozilla Public
# License, v. 2.0. If a copy of the MPL was not distributed with this
# file, You can obtain one at http://mozilla.org/MPL/2.0/.
#

#@ config: allocation, no_derived_wei_resource

#@ resource: r()
#:: ExpectedOutput(invalid.program:invalid.derived.resource)
#@ derived resource: token() -> r

@public
def foo():
    pass