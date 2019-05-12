"""
Copyright (c) 2019 ETH Zurich
This Source Code Form is subject to the terms of the Mozilla Public
License, v. 2.0. If a copy of the MPL was not distributed with this
file, You can obtain one at http://mozilla.org/MPL/2.0/.
"""

import ast

from nagini_translation.utils import seq_to_list

from nagini_translation.lib.typedefs import Program
from nagini_translation.lib.viper_ast import ViperAST

from nagini_translation.ast import names
from nagini_translation.ast import types
from nagini_translation.ast.nodes import VyperProgram, VyperVar

from nagini_translation.translation.abstract import PositionTranslator
from nagini_translation.translation.function import FunctionTranslator
from nagini_translation.translation.type import TypeTranslator
from nagini_translation.translation.specification import SpecificationTranslator
from nagini_translation.translation.context import Context

from nagini_translation.translation import builtins


class ProgramTranslator(PositionTranslator):

    def __init__(self, viper_ast: ViperAST, builtins: Program):
        self.viper_ast = viper_ast
        self.builtins = builtins
        self.function_translator = FunctionTranslator(viper_ast)
        self.type_translator = TypeTranslator(viper_ast)
        self.specification_translator = SpecificationTranslator(viper_ast)

    def _translate_field(self, var: VyperVar, ctx: Context):
        pos = self.to_position(var.node, ctx)

        name = var.name
        type = self.type_translator.translate(var.type, ctx)
        field = self.viper_ast.Field(name, type, pos)

        return field

    def _create_field_access_predicate(self, field_access, amount, ctx: Context):
        if amount == 1:
            perm = self.viper_ast.FullPerm()
        else:
            perm = builtins.read_perm(self.viper_ast)
        return self.viper_ast.FieldAccessPredicate(field_access, perm)

    def translate(self, vyper_program: VyperProgram, file: str) -> Program:
        if names.INIT not in vyper_program.functions:
            vyper_program.functions[builtins.INIT] = builtins.init_function()

        # Add self.balance field
        balance_var = VyperVar(names.SELF_BALANCE, types.VYPER_WEI_VALUE, None)
        vyper_program.state[balance_var.name] = balance_var

        # Add built-in methods
        methods = seq_to_list(self.builtins.methods())
        # Add built-in functions
        domains = seq_to_list(self.builtins.domains())

        ctx = Context(file)
        ctx.program = vyper_program
        ctx.self_var = builtins.self_var(self.viper_ast)
        ctx.msg_var = builtins.msg_var(self.viper_ast)
        ctx.block_var = builtins.block_var(self.viper_ast)

        def translate_invs(ctx: Context, ignore_old = False, ignore_msg = False):
            translate_spec = self.specification_translator.translate_invariant
            return [translate_spec(inv, ctx, ignore_old, ignore_msg) for inv in vyper_program.invariants]

        ctx.invariants = translate_invs

        ctx.fields = {}
        ctx.permissions = []
        ctx.unchecked_invariants = []
        for var in vyper_program.state.values():
            # Create field
            field = self._translate_field(var, ctx)
            ctx.fields[var.name] = field

            # Pass around the permissions for all fields
            field_acc = self.viper_ast.FieldAccess(ctx.self_var.localVar(), field)
            acc = self._create_field_access_predicate(field_acc, 1, ctx)
            ctx.permissions.append(acc)

            non_negs = self.type_translator.non_negative(field_acc, var.type, ctx)
            ctx.unchecked_invariants.extend(non_negs)
            
            array_lens = self.type_translator.array_length(field_acc, var.type, ctx)
            ctx.unchecked_invariants.extend(array_lens)
        
        ctx.balance_field = ctx.fields[names.SELF_BALANCE]

        ctx.immutable_fields = {}
        ctx.immutable_permissions = []
        # Create msg.sender field
        msg_sender = builtins.msg_sender_field(self.viper_ast)
        ctx.immutable_fields[builtins.MSG_SENDER] = msg_sender
        # Pass around the permissions for msg.sender
        sender_acc = self.viper_ast.FieldAccess(ctx.msg_var.localVar(), msg_sender)
        acc = self._create_field_access_predicate(sender_acc, 0, ctx)
        ctx.immutable_permissions.append(acc)
        # Assume msg.sender != 0
        zero = self.viper_ast.IntLit(0)
        ctx.unchecked_invariants.append(self.viper_ast.NeCmp(sender_acc, zero))

        # Create msg.value field
        msg_value = builtins.msg_value_field(self.viper_ast)
        ctx.immutable_fields[builtins.MSG_VALUE] = msg_value
        # Pass around the permissions for msg.value
        value_acc = self.viper_ast.FieldAccess(ctx.msg_var.localVar(), msg_value)
        acc = self._create_field_access_predicate(value_acc, 0, ctx)
        ctx.immutable_permissions.append(acc)
        # Assume msg.value >= 0
        ctx.unchecked_invariants.append(self.viper_ast.GeCmp(value_acc, zero))

        # Create block.timestamp field
        block_timestamp = builtins.block_timestamp_field(self.viper_ast)
        ctx.immutable_fields[builtins.BLOCK_TIMESTAMP] = block_timestamp
        # Pass around the permissions for block.timestamp
        timestamp_acc = self.viper_ast.FieldAccess(ctx.block_var.localVar(), block_timestamp)
        acc = self._create_field_access_predicate(timestamp_acc, 1, ctx)
        ctx.immutable_permissions.append(acc)
        # Assume block.timestamp >= 0
        ctx.unchecked_invariants.append(self.viper_ast.GeCmp(timestamp_acc, zero))

        fields_list = list(ctx.fields.values()) + list(ctx.immutable_fields.values())

        functions = vyper_program.functions.values()
        methods += [self.function_translator.translate(function, ctx) for function in functions]
        viper_program = self.viper_ast.Program(domains, fields_list, [], [], methods)
        return viper_program