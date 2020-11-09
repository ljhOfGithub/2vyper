"""
Copyright (c) 2019 ETH Zurich
This Source Code Form is subject to the terms of the Mozilla Public
License, v. 2.0. If a copy of the MPL was not distributed with this
file, You can obtain one at http://mozilla.org/MPL/2.0/.
"""

from typing import List, Optional, Tuple

from twovyper.ast import ast_nodes as ast, names

from twovyper.translation import helpers
from twovyper.translation.abstract import NodeTranslator
from twovyper.translation.context import Context

from twovyper.viper.ast import ViperAST
from twovyper.viper.typedefs import Expr, Stmt


class ResourceTranslator(NodeTranslator):

    def __init__(self, viper_ast: ViperAST):
        super().__init__(viper_ast)

    @property
    def specification_translator(self):
        from twovyper.translation.specification import SpecificationTranslator
        return SpecificationTranslator(self.viper_ast)

    def resource(self, name: str, args: List[Expr], ctx: Context, pos=None) -> Expr:
        self_address = ctx.self_address or helpers.self_address(self.viper_ast)
        args = list(args)
        args.append(self_address)
        return self._resource(name, args, ctx, pos)

    def _resource(self, name: str, args: List[Expr], ctx: Context, pos=None) -> Expr:
        resource_type = ctx.current_program.own_resources.get(name, ctx.program.resources[name][0]).type
        return helpers.struct_init(self.viper_ast, args, resource_type, pos)

    def creator_resource(self, resource: Expr, _: Context, pos=None) -> Expr:
        creator_resource_type = helpers.creator_resource().type
        return helpers.struct_init(self.viper_ast, [resource], creator_resource_type, pos)

    def translate(self, resource: Optional[ast.Node], res: List[Stmt], ctx: Context) -> Expr:
        if resource:
            return super().translate(resource, res, ctx)
        else:
            self_address = ctx.self_address or helpers.self_address(self.viper_ast)
            return self._resource(names.WEI, [self_address], ctx)

    def translate_exchange(self, exchange: Optional[ast.Exchange], res: Stmt, ctx: Context) -> Tuple[Expr, Expr]:
        if not exchange:
            wei_resource = self.translate(None, res, ctx)
            return wei_resource, wei_resource

        left = self.translate(exchange.left, res, ctx)
        right = self.translate(exchange.right, res, ctx)
        return left, right

    def translate_Name(self, node: ast.Name, _: List[Stmt], ctx: Context) -> Expr:
        pos = self.to_position(node, ctx)
        self_address = ctx.self_address or helpers.self_address(self.viper_ast)
        return self._resource(node.id, [self_address], ctx, pos)

    def translate_FunctionCall(self, node: ast.FunctionCall, res: List[Stmt], ctx: Context) -> Expr:
        pos = self.to_position(node, ctx)
        if node.name == names.CREATOR:
            resource = self.translate(node.args[0], res, ctx)
            return self.creator_resource(resource, ctx, pos)
        elif node.resource:
            address = self.specification_translator.translate(node.resource, res, ctx)
        else:
            address = ctx.self_address or helpers.self_address(self.viper_ast)
        args = [self.specification_translator.translate(arg, res, ctx) for arg in node.args]
        args.append(address)
        return self._resource(node.name, args, ctx, pos)

    def translate_Attribute(self, node: ast.Attribute, _: List[Stmt], ctx: Context) -> Expr:
        pos = self.to_position(node, ctx)
        assert isinstance(node.value, ast.Name)
        interface = ctx.current_program.interfaces[node.value.id]
        with ctx.program_scope(interface):
            self_address = ctx.self_address or helpers.self_address(self.viper_ast)
            return self._resource(node.attr, [self_address], ctx, pos)

    def translate_ReceiverCall(self, node: ast.ReceiverCall, res: List[Stmt], ctx: Context) -> Expr:
        pos = self.to_position(node, ctx)
        if isinstance(node.receiver, ast.Name):
            interface = ctx.current_program.interfaces[node.receiver.id]
            address = ctx.self_address or helpers.self_address(self.viper_ast)
        elif isinstance(node.receiver, ast.Subscript):
            assert isinstance(node.receiver.value, ast.Attribute)
            assert isinstance(node.receiver.value.value, ast.Name)
            interface_name = node.receiver.value.value.id
            interface = ctx.current_program.interfaces[interface_name]
            address = self.specification_translator.translate(node.receiver.index, res, ctx)
        else:
            assert False

        with ctx.program_scope(interface):
            args = [self.specification_translator.translate(arg, res, ctx) for arg in node.args]
            args.append(address)
            return self._resource(node.name, args, ctx, pos)

    def translate_Subscript(self, node: ast.Subscript, res: List[Stmt], ctx: Context) -> Expr:
        pos = self.to_position(node, ctx)
        other_address = self.specification_translator.translate(node.index, res, ctx)
        if isinstance(node.value, ast.Attribute):
            assert isinstance(node.value.value, ast.Name)
            interface = ctx.current_program.interfaces[node.value.value.id]
            with ctx.program_scope(interface):
                return self._resource(node.value.attr, [other_address], ctx, pos)
        elif isinstance(node.value, ast.Name):
            return self._resource(node.value.id, [other_address], ctx, pos)
        else:
            assert False
