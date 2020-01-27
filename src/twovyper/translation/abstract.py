"""
Copyright (c) 2019 ETH Zurich
This Source Code Form is subject to the terms of the Mozilla Public
License, v. 2.0. If a copy of the MPL was not distributed with this
file, You can obtain one at http://mozilla.org/MPL/2.0/.
"""

from typing import List, Iterable, Tuple

from twovyper.ast import ast_nodes as ast
from twovyper.ast.visitors import NodeVisitor

from twovyper.translation.context import Context

from twovyper.verification import error_manager
from twovyper.verification.error import ErrorInfo, ModelTransformation, Via
from twovyper.verification.rules import Rules

from twovyper.viper.ast import ViperAST
from twovyper.viper.typedefs import Expr, Stmt, StmtsAndExpr
from twovyper.viper.typedefs import Position, Info


class CommonTranslator:

    def __init__(self, viper_ast: ViperAST):
        self.viper_ast = viper_ast

    def _register_potential_error(self,
                                  node,
                                  ctx: Context,
                                  rules: Rules = None,
                                  vias: List[Via] = [],
                                  modelt: ModelTransformation = None) -> str:
        name = None if not ctx.function else ctx.function.name
        # Inline vias are in reverse order, as the outermost is first,
        # and successive vias are appended. For the error output, changing
        # the order makes more sense.
        inline_vias = list(reversed(ctx.inline_vias))
        error_info = ErrorInfo(name, node, inline_vias + vias, modelt)
        id = error_manager.add_error_information(error_info, rules)
        return id

    def to_position(self,
                    node: ast.Node,
                    ctx: Context,
                    rules: Rules = None,
                    vias: List[Via] = [],
                    modelt: ModelTransformation = None) -> Position:
        """
        Extracts the position from a node, assigns an ID to the node and stores
        the node and the position in the context for it.
        """
        id = self._register_potential_error(node, ctx, rules, vias, modelt)
        return self.viper_ast.to_position(node, id)

    def no_position(self) -> Position:
        return self.viper_ast.NoPosition

    def to_info(self, comments: List[str]) -> Info:
        """
        Wraps the given comments into an Info object.
        """
        if comments:
            return self.viper_ast.SimpleInfo(comments)
        else:
            return self.viper_ast.NoInfo

    def no_info(self) -> Info:
        return self.to_info([])

    def collect(self, se: Iterable[StmtsAndExpr]) -> Tuple[List[Stmt], List[Expr]]:
        stmts = []
        exprs = []
        for stmt, expr in se:
            stmts.extend(stmt)
            exprs.append(expr)
        return stmts, exprs

    def fail_if(self, cond, stmts, ctx: Context, pos=None, info=None) -> Stmt:
        body = [*stmts, self.viper_ast.Goto(ctx.revert_label, pos)]
        return self.viper_ast.If(cond, body, [], pos, info)

    def seqn_with_info(self, stmts: [Stmt], comment: str) -> List[Stmt]:
        if not stmts:
            return stmts
        info = self.to_info([comment])
        return [self.viper_ast.Seqn(stmts, info=info)]


class NodeTranslator(NodeVisitor, CommonTranslator):

    def __init__(self, viper_ast: ViperAST):
        super().__init__(viper_ast)

    @property
    def method_name(self) -> str:
        return 'translate'

    def translate(self, node, ctx):
        return self.visit(node, ctx)

    def generic_visit(self, node, ctx):
        raise AssertionError(f"Node of type {type(node)} not supported.")
