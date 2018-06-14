"""
This Source Code Form is subject to the terms of the Mozilla Public
License, v. 2.0. If a copy of the MPL was not distributed with this
file, You can obtain one at http://mozilla.org/MPL/2.0/.
"""

import ast

from nagini_translation.lib.program_nodes import PythonMethod, MethodType
from nagini_translation.lib.typedefs import StmtsAndExpr
from nagini_translation.lib.util import (InvalidProgramException,
                                         UnsupportedException)
from nagini_translation.translators.abstract import Context
from nagini_translation.translators.contract import ContractTranslator


class ExtendedASTContractTranslator(ContractTranslator):
    """
    Extended AST version of the contract translator.
    """

    def _is_in_postcondition(self, node: ast.Expr, func: PythonMethod) -> bool:
        post = func.postcondition
        for cond in post:
            for cond_node in ast.walk(cond[0]):
                if cond_node is node:
                    return True
        return False

    def translate_low(self, node: ast.Call, ctx: Context) -> StmtsAndExpr:
        """
        Translates a call to the Low() contract function.
        """
        if len(node.args) != 1:
            raise UnsupportedException(node, "Low() requires exactly one argument")
        stmts, expr = self.translate_expr(node.args[0], ctx)
        if stmts:
            raise InvalidProgramException(node, 'purity.violated')
        # determine if we are in a postcondition of a dynamically bound method
        if (ctx.current_class and
                ctx.current_function.method_type == MethodType.normal and
                ctx.obligation_context.is_translating_posts):
            self_type = self.type_factory.typeof(
                next(iter(ctx.actual_function.args.values())).ref(), ctx)
        else:
            self_type = None
        return [], self.viper.Low(expr, self_type, self.to_position(node, ctx),
                                  self.no_info(ctx))

    def translate_lowevent(self, node: ast.Call, ctx: Context) -> StmtsAndExpr:
        """
        Translates a call to the LowEvent() contract function.
        """
        # TODO: check that lowevent can only be in precondition
        if ctx.current_class and ctx.current_function.method_type == MethodType.normal:
            self_type = self.type_factory.typeof(
                next(iter(ctx.actual_function.args.values())).ref(), ctx)
        else:
            self_type = None
        return [], self.viper.LowEvent(self_type, self.to_position(node, ctx), self.no_info(ctx))
