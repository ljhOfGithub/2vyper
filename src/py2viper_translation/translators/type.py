import ast

from py2viper_contracts.contracts import CONTRACT_FUNCS
from py2viper_translation.lib.constants import (
    BOOL_TYPE,
    BUILTINS,
    DICT_TYPE,
    INT_TYPE,
    LIST_TYPE,
    OBJECT_TYPE,
    OPERATOR_FUNCTIONS,
    PRIMITIVES,
    RANGE_TYPE,
    SET_TYPE,
    STRING_TYPE,
    TUPLE_TYPE,
    UNION_TYPE,
)
from py2viper_translation.lib.program_nodes import (
    GenericType,
    get_type as do_get_type,
    PythonClass,
    PythonIOOperation,
    PythonMethod,
    PythonModule,
    PythonNode,
    PythonType,
    PythonVar,
    PythonVarBase,
)
from py2viper_translation.lib.jvmaccess import JVM
from py2viper_translation.lib.typedefs import (
    Expr,
    Stmt,
    StmtsAndExpr,
)
from py2viper_translation.lib.typeinfo import TypeInfo
from py2viper_translation.lib.util import (
    get_func_name,
    InvalidProgramException,
    UnsupportedException,
)
from py2viper_translation.lib.viper_ast import ViperAST
from py2viper_translation.translators.abstract import (
    Context,
    TranslatorConfig,
)
from py2viper_translation.translators.common import CommonTranslator
from typing import List


class TypeTranslator(CommonTranslator):

    def __init__(self, config: TranslatorConfig, jvm: JVM, source_file: str,
                 type_info: TypeInfo, viper_ast: ViperAST) -> None:
        super().__init__(config, jvm, source_file, type_info, viper_ast)
        self.builtins = {'builtins.int': viper_ast.Int,
                         'builtins.bool': viper_ast.Bool}

    def translate_type(self, cls: PythonClass,
                       ctx: Context) -> 'silver.ast.Type':
        """
        Translates the given type to the corresponding Viper type (Int, Ref, ..)
        """
        if cls.name.startswith('__prim__'):
            assert 'builtins.' + cls.name[8:] in self.builtins
            return self.builtins['builtins.' + cls.name[8:]]
        elif cls.name == 'type':
            return self.type_factory.type_type()
        else:
            return self.viper.Ref

    def get_type(self, node: ast.AST, ctx: Context) -> PythonModule:
        container = ctx.actual_function if ctx.actual_function else ctx.module
        containers = [ctx]
        if isinstance(container, (PythonMethod, PythonIOOperation)):
            containers.append(container)
            containers.extend(container.get_module().get_included_modules())
        else:
            # Assume module
            containers.extend(container.get_included_modules())
        result = do_get_type(node, containers, container)
        return result

    def _is_subtype(self, t1: PythonType, t2: PythonType) -> bool:
        if t1 == t2:
            return True
        if not t1.superclass:
            return False
        return self._is_subtype(t1.superclass, t2)

    def set_type_nargs_and_args(self, lhs: Expr, type: GenericType,
                                prefix: List[Expr], ctx: Context,
                                inhale_exhale: bool) -> Expr:
        """
        Creates an assertion containing the type argument information contained
        in 'type' about 'lhs', but not its actual, top level type. If, e.g.,
        'type' is Dict[str, C], this will generate an assertion saying that
        the type of 'lhs' has two type arguments, the first is str and the
        second is C.
        If 'inhale_exhale' is True, then this information (minus number of type
        arguments) will only be inhaled, not checked.
        """
        inhale_exhale = False
        true = self.viper.TrueLit(self.no_position(ctx), self.no_info(ctx))
        if type.name == UNION_TYPE:
            # Special case for union types: We don't want Union to show up
            # in the type info in Silver, instead, we just say that the type
            # arg is either option1, or option2 etc.
            result = self.viper.FalseLit(self.no_position(ctx),
                                         self.no_info(ctx))
            for option in type.type_args:
                option = self.normalize_type(option, ctx)
                check = self.type_factory.type_arg_check(lhs, option, prefix,
                                                         ctx)
                if inhale_exhale:
                    check = self.viper.InhaleExhaleExp(check, true,
                                                       self.no_position(ctx),
                                                       self.no_info(ctx))
                if isinstance(option, GenericType):
                    option_args = self.set_type_nargs_and_args(lhs, option,
                                                               prefix, ctx,
                                                               inhale_exhale)
                    check = self.viper.And(check, option_args,
                                           self.no_position(ctx),
                                           self.no_info(ctx))
                result = self.viper.Or(result, check,
                                       self.no_position(ctx),
                                       self.no_info(ctx))
            return result
        # Number of type arguments.
        args = type.type_args
        result = true
        if type.exact_length:
            nargs = len(type.type_args)
            result = self.type_factory.type_nargs_check(lhs, nargs,
                                                        prefix, ctx)
            for i, arg in enumerate(args):
                # Include the actual type argument information.
                lit = self.viper.IntLit(i, self.no_position(ctx), self.no_info(ctx))
                indices = prefix + [lit]

                if arg.name in PRIMITIVES:
                    arg = ctx.module.global_module.classes['__boxed_' + arg.name]
                if arg.name == UNION_TYPE:
                    check = true
                else:
                    check = self.type_factory.type_arg_check(lhs, arg, indices, ctx)
                if inhale_exhale:
                    check = self.viper.InhaleExhaleExp(check, true,
                                                       self.no_position(ctx),
                                                       self.no_info(ctx))
                result = self.viper.And(result, check, self.no_position(ctx),
                                        self.no_info(ctx))

                if isinstance(arg, GenericType):
                    # Recurse to include the type arguments of the type argument.
                    arg_nargs = self.set_type_nargs_and_args(lhs, arg, indices, ctx,
                                                             inhale_exhale)
                    result = self.viper.And(result, arg_nargs,
                                            self.no_position(ctx),
                                            self.no_info(ctx))
        else:
            assert len(args) == 1
            int_class = ctx.module.global_module.classes['__prim__int']
            index_var = ctx.actual_function.create_variable('i', int_class,
                                                            self.translator,
                                                            False)
            zero = self.viper.IntLit(0, self.no_position(ctx), self.no_info(ctx))
            ge_zero = self.viper.GeCmp(index_var.ref(), zero,
                                       self.no_position(ctx), self.no_info(ctx))
            nargs = self.type_factory.type_nargs(lhs, prefix, ctx)
            lt_nargs = self.viper.LtCmp(index_var.ref(), nargs,
                                        self.no_position(ctx),
                                        self.no_info(ctx))
            index_in_bounds = self.viper.And(ge_zero, lt_nargs,
                                             self.no_position(ctx),
                                             self.no_info(ctx))
            indices = prefix + [index_var.ref()]
            variables = [index_var.decl]
            # if covariant:
            if type.name == 'tuple':
                check = self.type_factory.type_arg_check_subtype(lhs, args[0],
                                                                 indices, ctx)
            else:
                check = self.type_factory.type_arg_check(lhs, args[0], indices,
                                                         ctx)
            body = self.viper.Implies(index_in_bounds, check,
                                      self.no_position(ctx), self.no_info(ctx))
            triggers = [self.viper.Trigger([self.type_factory.type_arg(lhs, indices, ctx)], self.no_position(ctx), self.no_info(ctx))]
            all_args = self.viper.Forall(variables, triggers, body,
                                         self.no_position(ctx),
                                         self.no_info(ctx))
            result = self.viper.And(result, all_args, self.no_position(ctx),
                                    self.no_info(ctx))
        return result

    def type_check(self, lhs: Expr, type: PythonType,
                   position: 'silver.ast.Position',
                   ctx: Context, inhale_exhale: bool=True) -> Expr:
        """
        Returns a type check expression. This may return a simple isinstance
        for simple types, or include information about type arguments for
        generic types, or things like the lengths for tuples.
        """
        inhale_exhale = False
        if type is None:
            none_type = ctx.module.global_module.classes['NoneType']
            return self.type_factory.type_check(lhs, none_type, position, ctx)
        elif type.name in PRIMITIVES or type.name == 'type':
            return self.viper.TrueLit(position, self.no_info(ctx))
        elif type.name == UNION_TYPE:
            # Union type should not directly show up on Silver level, instead
            # say the type is either type option 1 or type option 2 etc.
            result = self.viper.FalseLit(position, self.no_info(ctx))
            for type_option in type.type_args:
                option_result = self.type_check(lhs, type_option, position, ctx,
                                                inhale_exhale)
                result = self.viper.Or(result, option_result, position,
                                       self.no_info(ctx))
            return result
        else:
            result = self.type_factory.type_check(lhs, type, position, ctx)
            if isinstance(type, GenericType):
                # Add information about type arguments.
                args = self.set_type_nargs_and_args(lhs, type, [], ctx,
                                                    inhale_exhale)
                result = self.viper.And(result, args, self.no_position(ctx),
                                        self.no_info(ctx))
            return result
