#
# Copyright (c) 2020 ETH Zurich
# This Source Code Form is subject to the terms of the Mozilla Public
# License, v. 2.0. If a copy of the MPL was not distributed with this
# file, You can obtain one at http://mozilla.org/MPL/2.0/.
#


#@ requires: lemma == 0
#@ lemma_def bar(lemma: int128):
    #@ lemma == 0

@public
def foo():
    #:: ExpectedOutput(invalid.program:invalid.no.args)
    #@ lemma_assert lemma.bar()
    pass
