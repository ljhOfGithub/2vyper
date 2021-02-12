# @version 0.2.x

#
# Copyright (c) 2019 ETH Zurich
# This Source Code Form is subject to the terms of the Mozilla Public
# License, v. 2.0. If a copy of the MPL was not distributed with this
# file, You can obtain one at http://mozilla.org/MPL/2.0/.
#

exampleMapping: HashMap[int128, decimal]

#@ ensures: success() ==> self.exampleMapping[0] == 10.1
@external
def foo():
    self.exampleMapping[0] = 10.1
