import ast

from py2viper_translation.abstract_translator import (
    Expr,
    StmtAndExpr,
    Stmt,
    CommonTranslator
)
from py2viper_translation.analyzer import (
    PythonClass,
    PythonMethod,
    PythonVar,
    PythonTryBlock,
    PythonExceptionHandler
)
from py2viper_translation.constants import PRIMITIVES
from py2viper_translation.util import (
    InvalidProgramException,
    get_func_name,
    flatten,
    get_all_fields,
    get_surrounding_try_blocks
)
from typing import Tuple, List


class MethodTranslator(CommonTranslator):

    def is_pre(self, stmt: ast.AST) -> bool:
        return get_func_name(stmt) == 'Requires'

    def is_post(self, stmt: ast.AST) -> bool:
        return get_func_name(stmt) == 'Ensures'

    def is_exception_decl(self, stmt: ast.AST) -> bool:
        return get_func_name(stmt) == 'Exsures'

    def get_parameter_typeof(self,
                             param: PythonVar,
                             ctx) -> 'silver.ast.DomainFuncApp':
        return self.var_has_type(param.sil_name, param.type, ctx)

    def translate_function(self, func: PythonMethod,
                           ctx) -> 'silver.ast.Function':
        """
        Translates a pure Python function (may or not belong to a class) to a
        Viper function
        """
        old_function = ctx.current_function
        ctx.current_function = func
        type = self.translate_type(func.type, ctx)
        args = []
        for arg in func.args:
            args.append(func.args[arg].decl)
        if func.declared_exceptions:
            raise InvalidProgramException(func.node,
                                          'function.throws.exception')
        # create preconditions
        pres = []
        for pre in func.precondition:
            stmt, expr = self.translate_expr(pre, ctx)
            if stmt:
                raise InvalidProgramException(pre, 'purity.violated')
            pres.append(expr)
        # create postconditions
        posts = []
        for post in func.postcondition:
            stmt, expr = self.translate_expr(post, ctx)
            if stmt:
                raise InvalidProgramException(post, 'purity.violated')
            posts.append(expr)
        # create typeof preconditions
        for arg in func.args:
            if not func.args[arg].type.name in PRIMITIVES:
                pres.append(self.get_parameter_typeof(func.args[arg], ctx))
        statements = func.node.body
        body_index = self.get_body_start_index(statements)
        # translate body
        body = self.translate_exprs(statements[body_index:], func, ctx)
        ctx.current_function = old_function
        name = func.sil_name
        return self.viper.Function(name, args, type, pres, posts, body,
                                   self.noposition(ctx), self.noinfo(ctx))

    def extract_contract(self, method: PythonMethod, errorvarname: str,
                         is_constructor: bool,
                         ctx) -> Tuple[List[Expr], List[Expr]]:
        """
        Extracts the pre and postcondition from a given method
        """
        error_var_ref = self.viper.LocalVar(errorvarname, self.viper.Ref,
                                            self.noposition(ctx),
                                            self.noinfo(ctx))
        # create preconditions
        pres = []
        for pre in method.precondition:
            stmt, expr = self.translate_expr(pre, ctx)
            if stmt:
                raise InvalidProgramException(pre, 'purity.violated')
            pres.append(expr)
        # create postconditions
        posts = []
        noerror = self.viper.EqCmp(error_var_ref,
                                   self.viper.NullLit(self.noposition(ctx),
                                                      self.noinfo(ctx)),
                                   self.noposition(ctx), self.noinfo(ctx))
        error = self.viper.NeCmp(error_var_ref,
                                 self.viper.NullLit(self.noposition(ctx),
                                                    self.noinfo(ctx)),
                                 self.noposition(ctx), self.noinfo(ctx))
        for post in method.postcondition:
            stmt, expr = self.translate_expr(post, ctx)
            if stmt:
                raise InvalidProgramException(post, 'purity.violated')
            if method.declared_exceptions:
                expr = self.viper.Implies(noerror, expr,
                                          self.to_position(post, ctx),
                                          self.noinfo(ctx))
            posts.append(expr)
        # create exceptional postconditions
        error_type_conds = []
        error_type_pos = self.to_position(method.node, ctx)
        for exception in method.declared_exceptions:
            oldpos = ctx.position
            if ctx.position is None:
                ctx.position = error_type_pos
            has_type = self.var_has_type('_err',
                                         ctx.program.classes[exception], ctx)
            error_type_conds.append(has_type)
            ctx.position = oldpos
            condition = self.viper.And(error, has_type, self.noposition(ctx),
                                       self.noinfo(ctx))
            for post in method.declared_exceptions[exception]:
                stmt, expr = self.translate_expr(post, ctx)
                if stmt:
                    raise InvalidProgramException(post, 'purity.violated')
                expr = self.viper.Implies(condition, expr,
                                          self.to_position(post, ctx),
                                          self.noinfo(ctx))
                posts.append(expr)

        error_type_cond = None
        for type in error_type_conds:
            if error_type_cond is None:
                error_type_cond = type
            else:
                error_type_cond = self.viper.Or(error_type_cond, type,
                                                error_type_pos,
                                                self.noinfo(ctx))
        if error_type_cond is not None:
            posts.append(self.viper.Implies(error, error_type_cond,
                                            self.to_position(post, ctx),
                                            self.noinfo(ctx)))
        # create typeof preconditions
        for arg in method.args:
            if not (method.args[arg].type.name in PRIMITIVES
                    or (is_constructor and arg == next(iter(method.args)))):
                pres.append(self.get_parameter_typeof(method.args[arg], ctx))
        return pres, posts

    def get_all_field_accs(self, fields: List['silver.ast.Field'],
                           self_var: 'silver.ast.LocalVar',
                           position: 'silver.ast.Position',
                           ctx) -> List['silver.ast.FieldAccessPredicate']:
        """
        Creates access predicates for all fields in fields.
        """
        accs = []
        for field in fields:
            acc = self.viper.FieldAccess(self_var, field,
                                         position, self.noinfo(ctx))
            perm = self.viper.FullPerm(position, self.noinfo(ctx))
            pred = self.viper.FieldAccessPredicate(acc, perm, position,
                                                   self.noinfo(ctx))
            accs.append(pred)
        return accs

    def translate_method(self, method: PythonMethod, ctx) -> 'silver.ast.Method':
        """
        Translates an impure Python function (may or not belong to a class) to
        a Viper method
        """
        old_function = ctx.current_function
        ctx.current_function = method
        results = []
        if method.type is not None:
            type = self.translate_type(method.type, ctx)
            results.append(self.viper.LocalVarDecl('_res', type,
                                                   self.to_position(
                                                       method.node, ctx),
                                                   self.noinfo(ctx)))
        error_var_decl = self.viper.LocalVarDecl('_err', self.viper.Ref,
                                                 self.noposition(ctx),
                                                 self.noinfo(ctx))
        error_var_ref = self.viper.LocalVar('_err', self.viper.Ref,
                                            self.noposition(ctx),
                                            self.noinfo(ctx))
        method.error_var = error_var_ref
        pres, posts = self.extract_contract(method, '_err', False, ctx)
        if method.cls and method.name == '__init__':
            self_var = method.args[next(iter(method.args))].ref
            fields = get_all_fields(method.cls)
            accs = self.get_all_field_accs(fields, self_var,
                                           self.to_position(method.node, ctx),
                                           ctx)
            null = self.viper.NullLit(self.noposition(ctx), self.noinfo(ctx))
            not_null = self.viper.NeCmp(self_var, null, self.noposition(ctx),
                                        self.noinfo(ctx))
            pres = [not_null] + accs + pres
        if method.declared_exceptions:
            results.append(error_var_decl)
        args = []
        for arg in method.args:
            args.append(method.args[arg].decl)

        statements = method.node.body
        body_index = self.get_body_start_index(statements)
        # translate body
        body = []
        if method.contract_only:
            false = self.viper.FalseLit(self.noposition(ctx), self.noinfo(ctx))
            assume_false = self.viper.Inhale(false, self.noposition(ctx),
                                             self.noinfo(ctx))
            body.append(assume_false)
            locals = []
        else:
            if method.declared_exceptions:
                body.append(self.viper.LocalVarAssign(error_var_ref,
                    self.viper.NullLit(self.noposition(ctx), self.noinfo(ctx)),
                    self.noposition(ctx), self.noinfo(ctx)))
            body += flatten(
                [self.translate_stmt(stmt, ctx) for stmt in
                 method.node.body[body_index:]])
            body.append(self.viper.Goto('__end', self.noposition(ctx),
                                        self.noinfo(ctx)))
            for block in method.try_blocks:
                for handler in block.handlers:
                    body += self.translate_handler(handler, ctx)
                if block.else_block:
                    body += self.translate_handler(block.else_block, ctx)
                if block.finally_block:
                    body += self.translate_finally(block, ctx)
            locals = []
            for local in method.locals:
                locals.append(method.locals[local].decl)
            body += [self.viper.Label("__end", self.noposition(ctx),
                                      self.noinfo(ctx))]
        body_block = self.translate_block(body,
                                         self.to_position(method.node, ctx),
                                         self.noinfo(ctx))
        ctx.current_function = old_function
        name = method.sil_name
        return self.viper.Method(name, args, results, pres, posts,
                                 locals, body_block,
                                 self.to_position(method.node, ctx),
                                 self.noinfo(ctx))

    def get_body_start_index(self, statements: List[ast.AST]) -> int:
        """
        Returns the index of the first statement that is not a method contract
        """
        body_index = 0
        while self.is_pre(statements[body_index]):
            body_index += 1
        while self.is_post(statements[body_index]):
            body_index += 1
        while self.is_exception_decl(statements[body_index]):
            body_index += 1
        return body_index

    def translate_finally(self, block: PythonTryBlock, ctx) -> List[Stmt]:
        """
        Creates a code block representing the finally-block belonging to block,
        to be put at the end of a Viper method.
        """
        pos = self.to_position(block.node, ctx)
        info = self.noinfo(ctx)
        label = self.viper.Label(block.finally_name,
                                 self.to_position(block.node, ctx),
                                 self.noinfo(ctx))
        body = [label]
        for stmt in block.finally_block:
            body += self.translate_stmt(stmt, ctx)
        finally_var = block.get_finally_var(self.translator)
        tries = get_surrounding_try_blocks(ctx.current_function.try_blocks,
                                           block.node)
        goto_post = self.viper.Goto('post_' + block.name, pos, info)
        goto_end = self.viper.Goto('__end', pos, info)
        empty_stmt = self.translate_block([], pos, info)
        # assert tries
        except_block = []
        return_block = []
        for current in tries:
            if not return_block and current.finally_block:
                # propagate return value
                var_next = current.get_finally_var(self.translator)
                next_assign = self.viper.LocalVarAssign(var_next.ref,
                                                        finally_var.ref,
                                                        pos, info)
                # goto finally block
                goto_next = self.viper.Goto(current.finally_name, pos, info)
                return_block = [next_assign, goto_next]
            for handler in current.handlers:
                # if handler applies
                # goto handler
                condition = self.var_has_type(block.get_error_var(
                    self.translator).sil_name, handler.exception, ctx)
                goto = self.viper.Goto(handler.name, pos, info)
                if_handler = self.viper.If(condition, goto, empty_stmt, pos,
                                           info)
                except_block.append(if_handler)
            if current.finally_block:
                # propagate return value
                # goto finally block
                except_block += return_block
                break
        if not return_block:
            return_block = [goto_end]
        if ctx.current_function.declared_exceptions:
            # assign error to error output var
            error_var = ctx.current_function.error_var
            assign = self.viper.LocalVarAssign(
                error_var, block.get_error_var(self.translator).ref, pos, info)
            except_block.append(assign)
            except_block.append(goto_end)
        else:
            false = self.viper.FalseLit(pos, info)
            assert_false = self.viper.Exhale(false, pos, info)
            except_block.append(assert_false)
        except_block = self.translate_block(except_block, pos, info)
        return_block = self.translate_block(return_block, pos, info)

        number_zero = self.viper.IntLit(0, pos, info)
        greater_zero = self.viper.GtCmp(finally_var.ref, number_zero, pos, info)
        number_one = self.viper.IntLit(1, pos, info)
        greater_one = self.viper.GtCmp(finally_var.ref, number_one, pos, info)
        if_return = self.viper.If(greater_zero, return_block, goto_post, pos,
                                  info)
        if_except = self.viper.If(greater_one, except_block, if_return, pos,
                                  info)
        body += [if_except]
        return body


    def translate_handler(self, handler: PythonExceptionHandler,
                          ctx) -> List[Stmt]:
        """
        Creates a code block representing an exception handler, to be put at
        the end of a Viper method
        """
        label = self.viper.Label(handler.name,
                                 self.to_position(handler.node, ctx),
                                 self.noinfo(ctx))
        assert not ctx.var_aliases
        if handler.exception_name:
            ctx.var_aliases = {
                handler.exception_name:
                    handler.try_block.get_error_var(self.translator)
            }
        body = []
        for stmt in handler.body:
            body += self.translate_stmt(stmt, ctx)
        body_block = self.translate_block(body,
                                          self.to_position(handler.node, ctx),
                                          self.noinfo(ctx))
        if handler.try_block.finally_block:
            next = handler.try_block.finally_name
            lhs = handler.try_block.get_finally_var(self.translator).ref
            rhs = self.viper.IntLit(0, self.noposition(ctx), self.noinfo(ctx))
            var_set = self.viper.LocalVarAssign(lhs, rhs, self.noposition(ctx),
                                                self.noinfo(ctx))
            next_var_set = [var_set]
        else:
            next = 'post_' + handler.try_block.name
            next_var_set = []
        goto_end = self.viper.Goto(next,
                                   self.to_position(handler.node, ctx),
                                   self.noinfo(ctx))
        ctx.var_aliases = None
        return [label, body_block] + next_var_set + [goto_end]