#
# Copyright (c) 2020 ETH Zurich
# This Source Code Form is subject to the terms of the Mozilla Public
# License, v. 2.0. If a copy of the MPL was not distributed with this
# file, You can obtain one at http://mozilla.org/MPL/2.0/.
#


#@ requires: False
#:: Label(LEMMA)
#@ lemma_def bar():
    #@ True

@public
def foo():
    #:: ExpectedOutput(lemma.application.invalid:assertion.false, LEMMA) | ExpectedOutput(carbon)(assert.failed:assertion.false)
    #@ lemma_assert lemma.bar()
    pass
