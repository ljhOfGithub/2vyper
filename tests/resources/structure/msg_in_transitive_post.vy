#
# Copyright (c) 2019 ETH Zurich
# This Source Code Form is subject to the terms of the Mozilla Public
# License, v. 2.0. If a copy of the MPL was not distributed with this
# file, You can obtain one at http://mozilla.org/MPL/2.0/.
#

i: public(int128)

#@ preserves:
    #:: ExpectedOutput(invalid.program:postcondition.msg)
    #@ always ensures: msg.sender == old(msg.sender)
