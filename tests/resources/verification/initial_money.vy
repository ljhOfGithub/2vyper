#
# Copyright (c) 2019 ETH Zurich
# This Source Code Form is subject to the terms of the Mozilla Public
# License, v. 2.0. If a copy of the MPL was not distributed with this
# file, You can obtain one at http://mozilla.org/MPL/2.0/.
#

#:: ExpectedOutput(postcondition.violated:assertion.false)
#@ ensures: self.balance == as_wei_value(0, "wei")
@public
def __init__():
    pass