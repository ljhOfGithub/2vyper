#
# Copyright (c) 2019 ETH Zurich
# This Source Code Form is subject to the terms of the Mozilla Public
# License, v. 2.0. If a copy of the MPL was not distributed with this
# file, You can obtain one at http://mozilla.org/MPL/2.0/.
#


#@ config: no_gas


current_sender: address


#@ always ensures: msg.sender == old(msg.sender)
#@ always ensures: self.current_sender == msg.sender
#:: Label(OO)
#@ always ensures: self.current_sender == old(self.current_sender)


#@ ensures: msg.sender == old(msg.sender)
@public
def __init__():
    self.current_sender = msg.sender


#:: ExpectedOutput(postcondition.violated:assertion.false, OO)
@public
def set_sender():
    self.current_sender = msg.sender