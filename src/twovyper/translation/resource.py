"""
Copyright (c) 2019 ETH Zurich
This Source Code Form is subject to the terms of the Mozilla Public
License, v. 2.0. If a copy of the MPL was not distributed with this
file, You can obtain one at http://mozilla.org/MPL/2.0/.
"""

from typing import List, Optional

from twovyper.ast import ast_nodes as ast, names

from twovyper.translation import helpers
from twovyper.translation.abstract import NodeTranslator
from twovyper.translation.context import Context

from twovyper.viper.ast import ViperAST
from twovyper.viper.typedefs import Expr, StmtsAndExpr


class ResourceTranslator(NodeTranslator):

    def __init__(self, viper_ast: ViperAST):
        self.viper_ast = viper_ast

    @property
    def specification_translator(self):
        from twovyper.translation.specification import SpecificationTranslator
        return SpecificationTranslator(self.viper_ast)

    def resource(self, name: str, args: List[Expr], ctx: Context, pos=None) -> Expr:
        resource_type = ctx.program.resources[name].type
        return helpers.struct_init(self.viper_ast, args, resource_type, pos)

    def translate(self, resource: Optional[ast.Node], ctx: Context) -> StmtsAndExpr:
        if resource:
            return super().translate(resource, ctx)
        else:
            return [], self.resource(names.WEI, [], ctx)

    def translate_Name(self, node: ast.Name, ctx: Context) -> StmtsAndExpr:
        pos = self.to_position(node, ctx)
        return [], self.resource(node.id, [], ctx, pos)

    def translate_FunctionCall(self, node: ast.FunctionCall, ctx: Context) -> StmtsAndExpr:
        pos = self.to_position(node, ctx)
        args_stmts, args = self.collect(self.specification_translator.translate(arg, ctx) for arg in node.args)
        return args_stmts, self.resource(node.name, args, ctx, pos)
