"""
Copyright (c) 2021 ETH Zurich
This Source Code Form is subject to the terms of the Mozilla Public
License, v. 2.0. If a copy of the MPL was not distributed with this
file, You can obtain one at http://mozilla.org/MPL/2.0/.
"""

from typing import Dict, Tuple

from twovyper.translation.variable import TranslatedVar
from twovyper.viper.typedefs import Var

State = Dict[str, TranslatedVar]
LocalVarSnapshot = Dict[str, Tuple[int, Var, bool]]
