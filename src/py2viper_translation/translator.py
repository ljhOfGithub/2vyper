import ast

from collections import OrderedDict
from py2viper_contracts.contracts import (
    CONTRACT_FUNCS,
    CONTRACT_WRAPPER_FUNCS
    )
from py2viper_translation.analyzer import (
    PythonVar,
    PythonMethod,
    PythonClass,
    PythonField,
    PythonProgram,
    PythonExceptionHandler,
    PythonTryBlock
)
from py2viper_translation.constants import PRIMITIVES, BUILTINS
from py2viper_translation.jvmaccess import JVM
from py2viper_translation.type_domain_factory import TypeDomainFactory
from py2viper_translation.typeinfo import TypeInfo
from py2viper_translation.viper_ast import ViperAST
from py2viper_translation.util import (
    flatten, 
    get_func_name, 
    UnsupportedException
)
from toposort import toposort_flatten, toposort
from typing import Any, TypeVar, List, Tuple, Optional, Union, Dict


T = TypeVar('T')
V = TypeVar('V')


Expr = 'silver.ast.Exp'
Stmt = 'silver.ast.Stmt'
StmtAndExpr = Tuple[List[Stmt], Expr]


class AssignWrapper:
    """
    Represents an assignment of expr to a var named name, to
    be executed under conditions conds.
    """

    def __init__(self, name: str, conds: List, expr: ast.AST, node: ast.AST):
        self.name = name
        self.cond = conds
        self.expr = expr
        self.node = node
        self.names = {}


class ReturnWrapper:
    """
    Represents a return of expr, to be executed under condition conds.
    """
    def __init__(self, cond: List, expr: ast.AST, node: ast.AST):
        self.cond = cond
        self.expr = expr
        self.node = node
        self.names = {}


class NotWrapper:
    """
    Represents a negation of the condition cond.
    """
    def __init__(self, cond):
        self.cond = cond

Wrapper = Union[AssignWrapper, ReturnWrapper]


class InvalidProgramException(Exception):
    """
    Signals that the input program is invalid and cannot be translated
    """

    def __init__(self, node: ast.AST, code: str, message: str = None):
        self.node = node
        self.code = code
        self.message = message


class Translator:
    """
    Translates a Python AST to a Silver AST
    """

    def __init__(self, jvm: JVM, sourcefile: str, typeinfo: TypeInfo,
                 viperast: ViperAST):
        self.jvm = jvm
        self.types = typeinfo
        self.prefix = []
        self.typedomain = "PyType"
        self.viper = viperast
        self.position = None
        self.info = None
        self.current_class = None
        self.current_function = None
        self.program = None
        self.type_factory = TypeDomainFactory(viperast, self)
        self.var_aliases = None
        self.builtins = {'builtins.int': viperast.Int,
                         'builtins.bool': viperast.Bool}

    def translate_pure(self, conds: List, node: ast.AST) -> List[Wrapper]:
        method = 'translate_pure_' + node.__class__.__name__
        visitor = getattr(self, method, self.translate_pure_generic)
        return visitor(conds, node)

    def translate_pure_generic(self, conds: List, node: ast.AST) \
            -> List[Wrapper]:
        raise UnsupportedException(node)

    def translate_pure_If(self, conds: List, node: ast.If) -> List[Wrapper]:
        """
        Translates an if-block to a list of Return- and AssignWrappers which
        contain the condition(s) introduced by the if-block.
        """
        cond = node.test
        cond_var = self.current_function.create_variable('cond',
            self.program.classes['bool'], self)
        cond_let = AssignWrapper(cond_var.name, conds, cond, node)
        then_cond = conds + [cond_var.name]
        else_cond = conds + [NotWrapper(cond_var.name)]
        then = [self.translate_pure(then_cond, stmt) for stmt in node.body]
        then = flatten(then)
        else_ = []
        if node.orelse:
            else_ = [self.translate_pure(else_cond, stmt) for stmt
                     in node.orelse]
            else_ = flatten(else_)
        return [cond_let] + then + else_

    def translate_pure_Return(self, conds: List, node: ast.Return) \
            -> List[Wrapper]:
        """
        Translates a return statement to a ReturnWrapper
        """
        wrapper = ReturnWrapper(conds, node.value, node)
        return [wrapper]

    def translate_pure_Assign(self, conds: List, node: ast.Assign) \
            -> List[Wrapper]:
        """
        Translates an assign statement to an AssignWrapper
        """
        assert len(node.targets) == 1
        assert isinstance(node.targets[0], ast.Name)
        wrapper = AssignWrapper(node.targets[0].id, conds, node.value, node)
        return [wrapper]

    def translate_exprs(self, nodes: List[ast.AST], function: PythonMethod) \
            -> Expr:
        """
        Translates a list of nodes to a single (let-)expression if the nodes
        are only returns, assignments and if-blocks. First translates them to
        Assign- and ReturnWrappers with conditions derived from surrounding
        if-blocks (if any), then creates one big expression out of a list
        of wrappers.
        """
        wrappers = flatten([self.translate_pure([], node) for node in nodes])
        previous = None
        added = {}
        for wrapper in wrappers:
            if previous:
                wrapper.names.update(previous.names)
            if added:
                wrapper.names.update(added)
            added = {}
            if isinstance(wrapper, AssignWrapper):
                name = wrapper.name
                cls = function.get_variable(name).type
                new_name = function.create_variable(name, cls, self)
                added[name] = new_name
                wrapper.variable = new_name
            previous = wrapper
        previous = None
        info = self.noinfo()
        assert not self.var_aliases
        for wrapper in reversed(wrappers):
            position = self.to_position(wrapper.node)
            self.var_aliases = wrapper.names
            stmt, val = self.translate_expr(wrapper.expr)
            if stmt:
                raise InvalidProgramException(wrapper.expr,
                                              'purity.violated')
            if isinstance(wrapper, ReturnWrapper):
                if wrapper.cond:
                    if not previous:
                        raise InvalidProgramException(function.node,
                                                      'function.return.missing')
                    cond = self._translate_condition(wrapper.cond,
                                                     wrapper.names)
                    previous = self.viper.CondExp(cond, val, previous, position,
                                                  info)
                else:
                    if previous:
                        raise InvalidProgramException(function.node,
                                                      'function.dead.code')
                    previous = val
            elif isinstance(wrapper, AssignWrapper):
                if not previous:
                    raise InvalidProgramException(function.node,
                                                  'function.return.missing')
                if wrapper.cond:
                    cond = self._translate_condition(wrapper.cond,
                                                     wrapper.names)
                    old_val = wrapper.names[wrapper.name].ref
                    new_val = self.viper.CondExp(cond, val, old_val, position,
                                                 info)
                    let = self.viper.Let(wrapper.variable.decl, new_val,
                                         previous, position, info)
                    previous = let
                else:
                    let = self.viper.Let(wrapper.variable.decl, val,
                                         previous, position, info)
                    previous = let
            else:
                raise UnsupportedException(wrapper)
        self.var_aliases = None
        return previous


    def _translate_condition(self, conds: List, names: Dict[str, PythonVar]) \
            -> Expr:
        """
        Translates the conditions in conds to a big conjunctive expression,
        using the renamings in names.
        """
        previous = self.viper.TrueLit(self.noposition(), self.noinfo())
        for cond in conds:
            if isinstance(cond, NotWrapper):
                current = names.get(cond.cond).ref
                current = self.viper.Not(current, self.noposition(),
                                         self.noinfo())
            else:
                current = names.get(cond).ref
            previous = self.viper.And(previous, current, self.noposition(),
                                      self.noinfo())
        return previous

    def translate_expr(self, node: ast.AST) -> StmtAndExpr:
        """
        Generic visitor function for translating an expression
        """
        method = 'translate_' + node.__class__.__name__
        visitor = getattr(self, method, self.translate_generic)
        return visitor(node)

    def translate_perm(self, node: ast.AST) -> Expr:
        """
        Generic visitor function for translating a permission amount
        """
        method = 'translate_perm_' + node.__class__.__name__
        visitor = getattr(self, method, self.translate_generic)
        return visitor(node)

    def translate_perm_Num(self, node: ast.Num) -> Expr:
        if node.n == 1:
            return self.viper.FullPerm(self.to_position(node),
                                       self.noinfo())
        raise UnsupportedException(node)

    def translate_perm_BinOp(self, node: ast.BinOp) -> Expr:
        if isinstance(node.op, ast.Div):
            left_stmt, left = self.translate_expr(node.left)
            right_stmt, right = self.translate_expr(node.right)
            if left_stmt or right_stmt:
                raise InvalidProgramException(node, 'purity.violated')
            return self.viper.FractionalPerm(left, right,
                                             self.to_position(node),
                                             self.noinfo())
        raise UnsupportedException(node)

    def translate_generic(self, node: ast.AST) -> None:
        """
        Visitor that is used if no other visitor is implemented.
        Simply raises an exception.
        """
        raise UnsupportedException(node)

    def translate_Assign(self, node: ast.Assign) -> StmtAndExpr:
        if len(node.targets) != 1:
            raise UnsupportedException(node)
        target = self.current_function.get_variable(node.targets[0].id).decl
        stmt, expr = self.translate_expr(node.value)
        return (stmt, AssignWrapper(target, expr, node))

    def translate_contract(self, node: ast.AST) -> Expr:
        """
        Generic visitor function for translating contracts (i.e. calls to
        contract functions)
        """
        method = 'translate_contract_' + node.__class__.__name__
        visitor = getattr(self, method, self.translate_generic)
        return visitor(node)

    def translate_stmt(self, node: ast.AST) -> List[Stmt]:
        """
        Generic visitor function for translating statements
        """
        method = 'translate_stmt_' + node.__class__.__name__
        visitor = getattr(self, method, self.translate_generic)
        return visitor(node)

    def translate_contract_Call(self,
                                node: ast.Call) -> Expr:
        if get_func_name(node) in CONTRACT_WRAPPER_FUNCS:
            stmt, res = self.translate_expr(node.args[0])
            if stmt:
                raise InvalidProgramException(node, 'purity.violated')
            return res
        else:
            raise UnsupportedException(node)

    def translate_contract_Expr(self,
                                node: ast.Expr) -> Expr:
        if isinstance(node.value, ast.Call):
            return self.translate_contract(node.value)
        else:
            raise UnsupportedException(node)

    def translate_Num(self, node: ast.Num) -> StmtAndExpr:
        return ([], self.viper.IntLit(node.n, self.to_position(node),
                                      self.noinfo()))

    def translate_Dict(self, node: ast.Dict) -> StmtAndExpr:
        args = []
        res_var = self.current_function.create_variable('dict',
            self.program.classes['dict'], self)
        targets = [res_var.ref]
        constr_call = self.viper.MethodCall('dict___init__', args, targets,
                                            self.to_position(node),
                                            self.noinfo())
        stmt = [constr_call]
        for index in range(len(node.keys)):
            key = node.keys[index]
            val = node.values[index]
            key_stmt, key_val = self.translate_expr(key)
            val_stmt, val_val = self.translate_expr(val)
            append_call = self.viper.MethodCall('dict___setitem__',
                                                [res_var.ref, key_val, val_val],
                                                [], self.to_position(node),
                                                self.noinfo())
            stmt += key_stmt + val_stmt + [append_call]
        return stmt, res_var.ref

    def translate_Set(self, node: ast.Set) -> StmtAndExpr:
        args = []
        res_var = self.current_function.create_variable('set',
            self.program.classes['set'], self)
        targets = [res_var.ref]
        constr_call = self.viper.MethodCall('set___init__', args, targets,
                                            self.to_position(node),
                                            self.noinfo())
        stmt = [constr_call]
        for el in node.elts:
            el_stmt, el_val = self.translate_expr(el)
            append_call = self.viper.MethodCall('set_add',
                                                [res_var.ref, el_val],
                                                [], self.to_position(node),
                                                self.noinfo())
            stmt += el_stmt + [append_call]
        return stmt, res_var.ref

    def translate_List(self, node: ast.List) -> StmtAndExpr:
        args = []
        res_var = self.current_function.create_variable('list',
            self.program.classes['list'], self)
        targets = [res_var.ref]
        constr_call = self.viper.MethodCall('list___init__', args, targets,
                                            self.to_position(node),
                                            self.noinfo())
        stmt = [constr_call]
        for element in node.elts:
            el_stmt, el = self.translate_expr(element)
            append_call = self.viper.MethodCall('list_append',
                                                [res_var.ref, el], [],
                                                self.to_position(node),
                                                self.noinfo())
            stmt += el_stmt + [append_call]
        return stmt, res_var.ref

    def translate_Subscript(self, node: ast.Subscript) -> StmtAndExpr:
        if not isinstance(node.slice, ast.Index):
            raise UnsupportedException(node)
        target_stmt, target = self.translate_expr(node.value)
        index_stmt, index = self.translate_expr(node.slice.value)
        args = [target, index]
        call = self._get_function_call(node.value, '__getitem__', args, node)
        return target_stmt + index_stmt, call

    def translate_Return(self, node: ast.Return) -> StmtAndExpr:
        return self.translate_expr(node.value)

    def translate_result(self, node: ast.Call) -> StmtAndExpr:
        assert len(node.args) == 0
        type = self.current_function.type
        if not self.current_function.pure:
            return (
                [], self.viper.LocalVar('_res', self.translate_type(type),
                                        self.noposition(),
                                        self.noinfo()))
        else:
            return ([], self.viper.Result(self.translate_type(type),
                                          self.to_position(node),
                                          self.noinfo()))

    def translate_acc(self, node: ast.Call) -> StmtAndExpr:
        if len(node.args) == 1:
            perm = self.viper.FullPerm(self.to_position(node),
                                       self.noinfo())
        elif len(node.args) == 2:
            perm = self.translate_perm(node.args[1])
        else:
            raise UnsupportedException(node)
        if isinstance(node.args[0], ast.Call):
            call = node.args[0]
            # this is a predicate.
            args = []
            arg_stmts = []
            for arg in call.args:
                arg_stmt, arg_expr = self.translate_expr(arg)
                arg_stmts = arg_stmts + arg_stmt
                args.append(arg_expr)
            if isinstance(call.func, ast.Name):
                pred = self.program.get_predicate(call.func.id)
            elif isinstance(call.func, ast.Attribute):
                rec_stmt, receiver = self.translate_expr(call.func.value)
                assert not rec_stmt
                receiver_class = self.get_type(call.func.value)
                name = call.func.attr
                pred = receiver_class.get_predicate(name)
                args = [receiver] + args
            else:
                raise UnsupportedException(node)
            pred_name = pred.sil_name
            if pred.cls:
                family_root = pred.cls
                while (family_root.superclass and
                       family_root.superclass.get_predicate(name)):
                    family_root = family_root.superclass
                pred_name = family_root.get_predicate(name).sil_name
            return [], self._create_predicate_access(pred_name, args, perm,
                                                     node)
        stmt, fieldacc = self.translate_expr(node.args[0])
        if stmt:
            raise InvalidProgramException(node, 'purity.violated')
        pred = self.viper.FieldAccessPredicate(fieldacc, perm,
                                               self.to_position(node),
                                               self.noinfo())
        return [], pred

    def translate_implies(self, node: ast.Call) -> StmtAndExpr:
        assert len(node.args) == 2
        cond_stmt, cond = self.translate_expr(node.args[0])
        then_stmt, then = self.translate_expr(node.args[1])
        implication = self.viper.Implies(cond, then,
                                         self.to_position(node),
                                         self.noinfo())
        return (cond_stmt + then_stmt, implication)

    def translate_old(self, node: ast.Call) -> StmtAndExpr:
        assert len(node.args) == 1
        stmt, exp = self.translate_expr(node.args[0])
        res = self.viper.Old(exp, self.to_position(node), self.noinfo())
        return (stmt, res)

    def translate_fold(self, node: ast.Call) -> StmtAndExpr:
        assert len(node.args) == 1
        pred_stmt, pred = self.translate_expr(node.args[0])
        assert not pred_stmt
        fold = self.viper.Fold(pred, self.to_position(node), self.noinfo())
        return [fold], None

    def translate_unfold(self, node: ast.Call) -> StmtAndExpr:
        assert len(node.args) == 1
        pred_stmt, pred = self.translate_expr(node.args[0])
        assert not pred_stmt
        unfold = self.viper.Unfold(pred, self.to_position(node), self.noinfo())
        return [unfold], None

    def translate_unfolding(self, node: ast.Call) -> StmtAndExpr:
        assert len(node.args) == 2
        pred_stmt, pred = self.translate_expr(node.args[0])
        assert not pred_stmt
        expr_stmt, expr = self.translate_expr(node.args[1])
        unfold = self.viper.Unfolding(pred, expr, self.to_position(node),
                                      self.noinfo())
        return expr_stmt, unfold

    def translate_contractfunc_call(self, node: ast.Call) -> StmtAndExpr:
        """
        Translates calls to contract functions like Result() and Acc()
        """
        if get_func_name(node) == "Result":
            return self.translate_result(node)
        elif get_func_name(node) == 'Acc':
            return self.translate_acc(node)
        elif get_func_name(node) == 'Implies':
            return self.translate_implies(node)
        elif get_func_name(node) == 'Old':
            return self.translate_old(node)
        elif get_func_name(node) == 'Fold':
            return self.translate_fold(node)
        elif get_func_name(node) == 'Unfold':
            return self.translate_unfold(node)
        elif get_func_name(node) == 'Unfolding':
            return self.translate_unfolding(node)
        else:
            raise UnsupportedException(node)

    def _get_function_call(self, receiver, func_name, args, node):
        target_cls = self.get_type(receiver)
        func = target_cls.get_function(func_name)
        formal_args = []
        for arg in func.args:
            formal_args.append(func.args[arg].decl)
        type = self.translate_type(func.type)
        sil_name = func.sil_name
        call = self.viper.FuncApp(sil_name, args, self.to_position(node),
                                  self.noinfo(), type, formal_args)
        return call

    def translate_isinstance(self, node: ast.Call) -> StmtAndExpr:
        assert len(node.args) == 2
        assert isinstance(node.args[1], ast.Name)
        stmt, obj = self.translate_expr(node.args[0])
        cls = self.program.classes[node.args[1].id]
        return stmt, self.type_factory.has_type(obj, cls)

    def translate_len(self, node: ast.Call) -> StmtAndExpr:
        assert len(node.args) == 1
        stmt, target = self.translate_expr(node.args[0])
        args = [target]
        call = self._get_function_call(node.args[0], '__len__', args, node)
        return stmt, call

    def translate_super(self, node: ast.Call) -> StmtAndExpr:
        if len(node.args) == 2:
            if (isinstance(node.args[0], ast.Name) and
                    (node.args[0].id in self.program.classes) and
                    isinstance(node.args[1], ast.Name) and
                    (node.args[1].id == next(iter(self.current_function.args)))):
                return self.translate_expr(node.args[1])
            else:
                raise InvalidProgramException(node, 'invalid.super.call')
        elif not node.args:
            arg_name = next(iter(self.current_function.args))
            return [], self.current_function.args[arg_name].ref
        else:
            raise InvalidProgramException(node, 'invalid.super.call')

    def _create_predicate_access(self, pred_name: str, args: List, perm: Expr,
                                 node: ast.AST) -> Expr:
        pred_acc = self.viper.PredicateAccess(args, pred_name,
                                              self.to_position(node),
                                              self.noinfo())
        pred_acc_pred = self.viper.PredicateAccessPredicate(pred_acc, perm,
            self.to_position(node), self.noinfo())
        return pred_acc_pred

    def _translate_constructor_call(self, target_class: PythonClass,
            node: ast.Call, args: List, arg_stmts: List) -> StmtAndExpr:
        """
        Translates a call to the constructor of target_class with args, where
        node is the call node and arg_stmts are statements related to argument
        evaluation.
        """
        position = self.to_position(node)
        res_var = self.current_function.create_variable(target_class.name +'_res',
                                                        target_class,
                                                        self)
        fields, _ = self._get_all_fields(target_class, res_var.ref, position)
        new = self.viper.NewStmt(res_var.ref, fields, self.noposition(),
                                 self.noinfo())
        result_has_type = self.var_has_concrete_type(res_var.name, target_class)
        type_inhale = self.viper.Inhale(result_has_type, self.noposition(),
                                        self.noinfo())
        args = [res_var.ref] + args
        stmts = [new, type_inhale]
        target = target_class.get_method('__init__')
        if target:
            target_class = target.cls
            targets = []
            if target.declared_exceptions:
                error_var = self._get_error_var(node)
                targets.append(error_var)
            method_name = target_class.get_method('__init__').sil_name
            init = self.viper.MethodCall(method_name,
                                         args, targets,
                                         self.to_position(node),
                                         self.noinfo())
            stmts.append(init)
            if target.declared_exceptions:
                catchers = self.create_exception_catchers(error_var,
                    self.current_function.try_blocks, node)
                stmts = stmts + catchers
        return arg_stmts + stmts, res_var.ref

    def translate_set(self, node: ast.Call) -> StmtAndExpr:
        if node.args:
            raise UnsupportedException(node)
        args = []
        res_var = self.current_function.create_variable('set',
            self.program.classes['set'], self)
        targets = [res_var.ref]
        constr_call = self.viper.MethodCall('set___init__', args, targets,
                                            self.to_position(node),
                                            self.noinfo())
        return [constr_call], res_var.ref

    def translate_builtin_func(self, node: ast.Call) -> StmtAndExpr:
        """
        Translates a call to a builtin function like len() or isinstance()
        """
        if get_func_name(node) == 'isinstance':
            return self.translate_isinstance(node)
        elif get_func_name(node) == 'super':
            return self.translate_super(node)
        elif get_func_name(node) == 'len':
            return self.translate_len(node)
        elif get_func_name(node) == 'set':
            return self.translate_set(node)
        else:
            raise UnsupportedException(node)

    def translate_Call(self, node: ast.Call) -> StmtAndExpr:
        """
        Translates any kind of call. This can be a call to a contract function
        like Assert, a builtin Python function like isinstance, a
        constructor call, a 'call' to a predicate, a pure function or impure
        method call, on a receiver object or not.
        """
        if get_func_name(node) in CONTRACT_WRAPPER_FUNCS:
            raise ValueError('Contract call translated as normal call.')
        elif get_func_name(node) in CONTRACT_FUNCS:
            return self.translate_contractfunc_call(node)
        elif get_func_name(node) in BUILTINS:
            return self.translate_builtin_func(node)
        args = []
        formal_args = []
        arg_stmts = []
        for arg in node.args:
            arg_stmt, arg_expr = self.translate_expr(arg)
            arg_stmts = arg_stmts + arg_stmt
            args.append(arg_expr)
        name = get_func_name(node)
        position = self.to_position(node)
        if name in self.program.classes:
            # this is a constructor call
            target_class = self.program.classes[name]
            return self._translate_constructor_call(target_class, node, args,
                                                    arg_stmts)
        is_predicate = True
        if isinstance(node.func, ast.Attribute):
            # method called on an object
            rec_stmt, receiver = self.translate_expr(node.func.value)
            receiver_class = self.get_type(node.func.value)
            target = receiver_class.get_predicate(node.func.attr)
            if not target:
                target = receiver_class.get_func_or_method(node.func.attr)
                is_predicate = False
            receiver_class = target.cls
            arg_stmts = rec_stmt + arg_stmts
            args = [receiver] + args
        else:
            # global function/method called
            receiver_class = None
            target = self.program.predicates.get(name)
            if not target:
                target = self.program.get_func_or_method(name)
                is_predicate = False
        for arg in target.args:
            formal_args.append(target.args[arg].decl)
        target_name = target.sil_name
        if is_predicate:
            if receiver_class:
                family_root = receiver_class
                while (family_root.superclass and
                       family_root.superclass.get_predicate(name)):
                    family_root = family_root.superclass
                target_name = family_root.get_predicate(name).sil_name
            perm = self.viper.FullPerm(position, self.noinfo())
            return arg_stmts, self._create_predicate_access(target_name, args,
                                                            perm, node)
        elif target.pure:
            type = self.translate_type(target.type)
            return (arg_stmts, self.viper.FuncApp(target_name, args,
                                                  position,
                                                  self.noinfo(),
                                                  type,
                                                  formal_args))
        else:
            targets = []
            result_var = None
            if self.current_function is None:
                if self.current_class is None:
                    # global variable
                    raise InvalidProgramException(node, 'purity.violated')
                else:
                    # static field
                    raise UnsupportedException(node)
            if target.type is not None:
                result_var = self.current_function.create_variable(
                    target.name + '_res', target.type, self)
                targets.append(result_var.ref)
            if target.declared_exceptions:
                errorvar = self.current_function.create_variable(
                    target.name + '_err',
                    self.program.classes['Exception'], self)
                targets.append(errorvar.ref)
            call = [self.viper.MethodCall(target_name, args, targets,
                                          position,
                                          self.noinfo())]
            if target.declared_exceptions:
                call = call + self.create_exception_catchers(errorvar,
                    self.current_function.try_blocks, node)
            return (arg_stmts + call,
                    result_var.ref if result_var else None)

    def _get_surrounding_try_blocks(self, try_blocks: List[PythonTryBlock],
                                    stmt: ast.AST) -> List[PythonTryBlock]:
        """
        Finds the try blocks in try_blocks that protect the statement stmt.
        """
        tb = try_blocks
        blocks = [b for b in tb if self.contains_stmt(b.protected_region, stmt)]
        deps = {(b, len({1 for b2 in blocks
                         if self.contains_stmt(b2.protected_region, b.node)}))
                for b in blocks}
        deps = sorted(deps,key=lambda k: -k[1])
        deps = [b for (b, r) in deps]
        return deps

    def create_exception_catchers(self, var: PythonVar,
                                  try_blocks: List[PythonTryBlock],
                                  call: ast.Call) -> List[Stmt]:
        """
        Creates the code for catching an exception, i.e. redirecting control
        flow to the handlers, to a finally block, or giving the exception to
        the caller function.
        """
        if isinstance(var, PythonVar):
            var = var.ref
        cases = []
        position = self.to_position(call)
        err_var = self.viper.LocalVar('_err', self.viper.Ref,
                                      self.noposition(),
                                      self.noinfo())

        relevant_try_blocks = self._get_surrounding_try_blocks(try_blocks, call)
        goto_finally = self._create_goto_finally(relevant_try_blocks, var)
        if goto_finally:
            uncaught_option = goto_finally
        else:
            if self.current_function.declared_exceptions:
                assignerror = self.viper.LocalVarAssign(err_var, var, position,
                                                        self.noinfo())
                gotoend = self.viper.Goto('__end', position,
                                          self.noinfo())
                uncaught_option = self.translate_block([assignerror, gotoend],
                                                       position,
                                                       self.noinfo())
            else:
                uncaught_option = self.viper.Exhale(
                    self.viper.FalseLit(position, self.noinfo()), position,
                    self.noinfo())

        for block in relevant_try_blocks:
            for handler in block.handlers:
                condition = self.type_factory.has_type(var, handler.exception)
                goto = self.viper.Goto(handler.name,
                                       self.to_position(handler.node),
                                       self.noinfo())
                cases.insert(0, (condition, goto))
            if block.finally_block:
                break

        result = None
        for cond, goto in cases:
            if result is None:
                result = self.viper.If(cond, goto,
                                       uncaught_option,
                                       self.to_position(handler.node),
                                       self.noinfo())
            else:
                result = self.viper.If(cond, goto, result,
                                       self.to_position(handler.node),
                                       self.noinfo())
        if result is None:
            error_case = uncaught_option
        else:
            error_case = result
        errnotnull = self.viper.NeCmp(var,
                                      self.viper.NullLit(self.noposition(),
                                                         self.noinfo()),
                                      position, self.noinfo())
        emptyblock = self.translate_block([], self.noposition(),
                                          self.noinfo())
        errcheck = self.viper.If(errnotnull, error_case, emptyblock,
                                 position,
                                 self.noinfo())
        return [errcheck]

    def contains_stmt(self, container: Any, contained: ast.AST) -> bool:
        """
        Checks if 'contained' is a part of the partial AST
        whose root is 'container'.
        """
        if container is contained:
            return True
        if isinstance(container, list):
            for stmt in container:
                if self.contains_stmt(stmt, contained):
                    return True
            return False
        elif isinstance(container, ast.AST):
            for field in container._fields:
                if self.contains_stmt(getattr(container, field), contained):
                    return True
            return False
        else:
            return False

    def translate_to_bool(self, node: ast.AST) -> StmtAndExpr:
        """
        Translates node as a normal expression, then applies Python's auto-
        conversion to a boolean value (using the __bool__ function)
        """
        stmt, res = self.translate_expr(node)
        type = self.get_type(node)
        if type is self.program.classes['bool']:
            return stmt, res
        args = [res]
        call = self._get_function_call(node, '__bool__', args, node)
        return stmt, call

    def translate_Expr(self, node: ast.Expr) -> StmtAndExpr:
        return self.translate_expr(node.value)

    def translate_Name(self, node: ast.Name) -> StmtAndExpr:
        if node.id in self.program.global_vars:
            var = self.program.global_vars[node.id]
            type = self.translate_type(var.type)
            func_app = self.viper.FuncApp(var.sil_name, [],
                                         self.to_position(node),
                                         self.noinfo(), type, [])
            return [], func_app
        else:
            if self.var_aliases and node.id in self.var_aliases:
                return [], self.var_aliases[node.id].ref
            else:
                return [], self.current_function.get_variable(node.id).ref

    def translate_Attribute(self, node: ast.Attribute) -> StmtAndExpr:
        stmt, receiver = self.translate_expr(node.value)
        rec_type = self.get_type(node.value)
        result = rec_type.get_field(node.attr)
        while result.inherited is not None:
            result = result.inherited
        if result.is_mangled():
            if result.cls is not self.current_class:
                raise InvalidProgramException(node, 'private.field.access')
        return (stmt, self.viper.FieldAccess(receiver, result.field,
                                             self.to_position(node),
                                             self.noinfo()))

    def get_type(self, node: ast.AST) -> PythonClass:
        """
        Returns the type of the expression represented by node as a PythonClass
        """
        if isinstance(node, ast.Attribute):
            receiver = self.get_type(node.value)
            return receiver.get_field(node.attr).type
        elif isinstance(node, ast.Name):
            if node.id in self.program.global_vars:
                return self.program.global_vars[node.id].type
            else:
                return self.current_function.get_variable(node.id).type
        elif isinstance(node, ast.Compare):
            return self.program.classes['bool']
        elif isinstance(node, ast.BoolOp):
            return self.program.classes['bool']
        elif isinstance(node, ast.List):
            return self.program.classes['list']
        elif isinstance(node, ast.Dict):
            return self.program.classes['dict']
        elif isinstance(node, ast.BinOp):
            return self.program.classes['int']
        elif isinstance(node, ast.UnaryOp):
            if isinstance(node.op, ast.Not):
                return self.program.classes['bool']
            elif isinstance(node.op, ast.USub):
                return self.program.classes['int']
            else:
                raise UnsupportedException(node)
        elif isinstance(node, ast.NameConstant):
            if (node.value is True) or (node.value is False):
                return self.program.classes['bool']
            elif node.value is None:
                return self.program.classes['object']
            else:
                raise UnsupportedException(node)
        elif isinstance(node, ast.Call):
            if get_func_name(node) == 'super':
                if len(node.args) == 2:
                    assert isinstance(node.args[0], ast.Name)
                    assert node.args[0].id in self.program.classes
                    assert isinstance(node.args[1], ast.Name)
                    assert (node.args[1].id ==
                            next(iter(self.current_function.args)))
                    return self.program.classes[node.args[0].id].superclass
                elif not node.args:
                    return self.current_class.superclass
                else:
                    raise InvalidProgramException(node, 'invalid.super.call')
            if isinstance(node.func, ast.Name):
                if node.func.id in CONTRACT_FUNCS:
                    if node.func.id == 'Result':
                        return self.current_function.type
                    elif node.func.id == 'Acc':
                        return self.program.classes['bool']
                    else:
                        raise UnsupportedException(node)
                elif node.func.id in BUILTINS:
                    if node.func.id == 'isinstance':
                        return self.program.classes['bool']
                    elif node.func.id == 'bool':
                        return self.program.classes['bool']
                if node.func.id in self.program.classes:
                    return self.program.classes[node.func.id]
                elif self.program.get_func_or_method(node.func.id) is not None:
                    return self.program.get_func_or_method(node.func.id).type
            elif isinstance(node.func, ast.Attribute):
                rectype = self.get_type(node.func.value)
                return rectype.get_func_or_method(node.func.attr).type
        else:
            raise UnsupportedException(node)

    def translate_UnaryOp(self, node: ast.UnaryOp) -> StmtAndExpr:
        if isinstance(node.op, ast.Not):
            stmt, expr = self.translate_to_bool(node.operand)
            return (stmt, self.viper.Not(expr, self.to_position(node),
                                         self.noinfo()))
        stmt, expr = self.translate_expr(node.operand)
        if isinstance(node.op, ast.USub):
            return (stmt, self.viper.Minus(expr, self.to_position(node),
                                           self.noinfo()))
        else:
            raise UnsupportedException(node)

    def translate_IfExp(self, node: ast.IfExp) -> StmtAndExpr:
        position = self.to_position(node)
        cond_stmt, cond = self.translate_to_bool(node.test)
        then_stmt, then = self.translate_expr(node.body)
        else_stmt, else_ = self.translate_expr(node.orelse)
        if then_stmt or else_stmt:
            then_block = self.translate_block(then_stmt, position,
                                              self.noinfo())
            else_block = self.translate_block(else_stmt, position,
                                              self.noinfo())
            if_stmt = self.viper.If(cond, then_block, else_block, position,
                                    self.noinfo())
            bodystmt = [if_stmt]
        else:
            bodystmt = []
        cond_exp = self.viper.CondExp(cond, then, else_,
                                      self.to_position(node),
                                      self.noinfo())
        return cond_stmt + bodystmt, cond_exp

    def translate_BinOp(self, node: ast.BinOp) -> StmtAndExpr:
        left_stmt, left = self.translate_expr(node.left)
        right_stmt, right = self.translate_expr(node.right)
        stmt = left_stmt + right_stmt
        if isinstance(node.op, ast.Add):
            return (stmt, self.viper.Add(left, right,
                                         self.to_position(node),
                                         self.noinfo()))
        elif isinstance(node.op, ast.Sub):
            return (stmt, self.viper.Sub(left, right,
                                         self.to_position(node),
                                         self.noinfo()))
        elif isinstance(node.op, ast.Mult):
            return (stmt, self.viper.Mul(left, right,
                                         self.to_position(node),
                                         self.noinfo()))
        elif isinstance(node.op, ast.FloorDiv):
            return (stmt, self.viper.Div(left, right,
                                         self.to_position(node),
                                         self.noinfo()))
        elif isinstance(node.op, ast.Mod):
            return (stmt, self.viper.Mod(left, right,
                                         self.to_position(node),
                                         self.noinfo()))
        else:
            raise UnsupportedException(node)

    def translate_Compare(self, node: ast.Compare) -> StmtAndExpr:
        if len(node.ops) != 1 or len(node.comparators) != 1:
            raise UnsupportedException(node)
        left_stmt, left = self.translate_expr(node.left)
        right_stmt, right = self.translate_expr(node.comparators[0])
        stmts = left_stmt + right_stmt
        if isinstance(node.ops[0], ast.Eq):
            return (stmts, self.viper.EqCmp(left, right,
                                            self.to_position(node),
                                            self.noinfo()))
        elif isinstance(node.ops[0], ast.Gt):
            return (stmts, self.viper.GtCmp(left, right,
                                            self.to_position(node),
                                            self.noinfo()))
        elif isinstance(node.ops[0], ast.GtE):
            return (stmts, self.viper.GeCmp(left, right,
                                            self.to_position(node),
                                            self.noinfo()))
        elif isinstance(node.ops[0], ast.Lt):
            return (stmts, self.viper.LtCmp(left, right,
                                            self.to_position(node),
                                            self.noinfo()))
        elif isinstance(node.ops[0], ast.LtE):
            return (stmts, self.viper.LeCmp(left, right,
                                            self.to_position(node),
                                            self.noinfo()))
        elif isinstance(node.ops[0], ast.NotEq):
            return (stmts, self.viper.NeCmp(left, right,
                                            self.to_position(node),
                                            self.noinfo()))
        elif isinstance(node.ops[0], ast.In):
            args = [right, left]
            app = self._get_function_call(node.comparators[0], '__contains__',
                                          args, node)
            return stmts, app
        else:
            raise UnsupportedException(node.ops[0])

    def translate_NameConstant(self,
                               node: ast.NameConstant) -> StmtAndExpr:
        if node.value is True:
            return ([], self.viper.TrueLit(self.to_position(node),
                                           self.noinfo()))
        elif node.value is False:
            return ([], self.viper.FalseLit(self.to_position(node),
                                            self.noinfo()))
        elif node.value is None:
            return ([],
                    self.viper.NullLit(self.to_position(node), self.noinfo()))
        else:
            raise UnsupportedException(node)

    def translate_BoolOp(self, node: ast.BoolOp) -> StmtAndExpr:
        if len(node.values) != 2:
            raise UnsupportedException(node)
        position = self.to_position(node)
        left_stmt, left = self.translate_expr(node.values[0])
        right_stmt, right = self.translate_expr(node.values[1])
        if left_stmt or right_stmt:
            # TODO: Something important breaks if we run this normally
            # with an acc() as left and a method call on the rhs. If this
            # happens in a test, all tests afterwards fail. Either catch all
            # such cases here, or fix it in Silver.
            if isinstance(left, self.jvm.viper.silver.ast.FieldAccessPredicate):
                return left_stmt + right_stmt, right
            cond = left
            if isinstance(node.op, ast.Or):
                cond = self.viper.Not(cond, position, self.noinfo())
            then_block = self.translate_block(right_stmt, position,
                                              self.noinfo())
            else_block = self.translate_block([], position, self.noinfo())
            if_stmt = self.viper.If(cond, then_block, else_block, position,
                                   self.noinfo())
            stmt = left_stmt + [if_stmt]
        else:
            stmt = []
        if isinstance(node.op, ast.And):
            return (stmt, self.viper.And(left,
                                         right,
                                         self.to_position(node),
                                         self.noinfo()))
        elif isinstance(node.op, ast.Or):
            return (stmt, self.viper.Or(left,
                                        right,
                                        self.to_position(node),
                                        self.noinfo()))
        else:
            raise UnsupportedException(node)

    def translate_stmt_AugAssign(self,
                                 node: ast.AugAssign) -> List[Stmt]:
        lhs_stmt, lhs = self.translate_expr(node.target)
        if lhs_stmt:
            raise InvalidProgramException(node, 'purity.violated')
        rhs_stmt, rhs = self.translate_expr(node.value)
        if isinstance(node.op, ast.Add):
            newval = self.viper.Add(lhs, rhs,
                                    self.to_position(node),
                                    self.noinfo())
        elif isinstance(node.op, ast.Sub):
            newval = self.viper.Sub(lhs, rhs,
                                    self.to_position(node),
                                    self.noinfo())
        elif isinstance(node.op, ast.Mult):
            newval = self.viper.Mul(lhs, rhs,
                                    self.to_position(node),
                                    self.noinfo())
        else:
            raise UnsupportedException(node)
        position = self.to_position(node)
        if isinstance(node.target, ast.Name):
            assign = self.viper.LocalVarAssign(lhs, newval, position,
                                               self.noinfo())
        elif isinstance(node.target, ast.Attribute):
            assign = self.viper.FieldAssign(lhs, newval, position,
                                            self.noinfo())
        return rhs_stmt + [assign]

    def translate_stmt_Try(self, node: ast.Try) -> List[Stmt]:
        try_block = None
        for block in self.current_function.try_blocks:
            if block.node is node:
                try_block = block
                break
        assert try_block
        body = flatten([self.translate_stmt(stmt) for stmt in node.body])
        if try_block.else_block:
            goto = self.viper.Goto(try_block.else_block.name,
                                   self.to_position(node), self.noinfo())
            body += [goto]
        elif try_block.finally_block:
            goto = self.viper.Goto(try_block.finally_name,
                                   self.to_position(node), self.noinfo())
            body += [goto]
        end_label = self.viper.Label('post_' + node.sil_name,
                                     self.to_position(node),
                                     self.noinfo())
        return body + [end_label]

    def translate_stmt_Raise(self, node: ast.Raise) -> List[Stmt]:
        var = self._get_error_var(node)
        stmt, exception = self.translate_expr(node.exc)
        assignment = self.viper.LocalVarAssign(var, exception,
                                               self.to_position(node),
                                               self.noinfo())
        catchers = self.create_exception_catchers(var,
            self.current_function.try_blocks, node)
        return stmt + [assignment] + catchers

    def translate_stmt_Call(self, node: ast.Call) -> List[Stmt]:
        if get_func_name(node) == 'Assert':
            assert len(node.args) == 1
            stmt, expr = self.translate_expr(node.args[0])
            assertion = self.viper.Assert(expr, self.to_position(node),
                                          self.noinfo())
            return stmt + [assertion]
        else:
            stmt, expr = self.translate_Call(node)
            if not stmt:
                raise InvalidProgramException(node, 'no.effect')
            return stmt

    def translate_stmt_Expr(self, node: ast.Expr) -> List[Stmt]:
        if isinstance(node.value, ast.Call):
            return self.translate_stmt(node.value)
        else:
            raise UnsupportedException(node)

    def translate_stmt_If(self, node: ast.If) -> List[Stmt]:
        cond_stmt, cond = self.translate_to_bool(node.test)
        then_body = flatten([self.translate_stmt(stmt) for stmt in node.body])
        then_block = self.translate_block(then_body, self.to_position(node),
                                          self.noinfo())
        else_body = flatten([self.translate_stmt(stmt) for stmt in node.orelse])
        else_block = self.translate_block(
            else_body,
            self.to_position(node), self.noinfo())
        position = self.to_position(node)
        return cond_stmt + [self.viper.If(cond, then_block, else_block,
                                          position, self.noinfo())]

    def translate_stmt_Assign(self, node: ast.Assign) -> List[Stmt]:
        if len(node.targets) != 1:
            raise UnsupportedException(node)
        if isinstance(node.targets[0], ast.Subscript):
            if not isinstance(node.targets[0].slice, ast.Index):
                raise UnsupportedException(node)
            target_cls = self.get_type(node.targets[0].value)
            lhs_stmt, target = self.translate_expr(node.targets[0].value)
            ind_stmt, index = self.translate_expr(node.targets[0].slice.value)
            func = target_cls.get_method('__setitem__')
            func_name = func.sil_name
            rhs_stmt, rhs = self.translate_expr(node.value)
            args = [target, index, rhs]
            targets = []
            call = self.viper.MethodCall(func_name, args, targets,
                                         self.to_position(node), self.noinfo())
            return lhs_stmt + ind_stmt + rhs_stmt + [call]
        target = node.targets[0]
        lhs_stmt, var = self.translate_expr(target)
        if isinstance(target, ast.Name):
            assignment = self.viper.LocalVarAssign
        else:
            assignment = self.viper.FieldAssign
        rhs_stmt, rhs = self.translate_expr(node.value)
        assign = assignment(var,
                            rhs, self.to_position(node),
                            self.noinfo())
        return lhs_stmt + rhs_stmt + [assign]

    def translate_stmt_While(self, node: ast.While) -> List[Stmt]:
        cond_stmt, cond = self.translate_to_bool(node.test)
        if cond_stmt:
            raise InvalidProgramException(node, 'purity.violated')
        invariants = []
        locals = []
        bodyindex = 0
        while self.is_invariant(node.body[bodyindex]):
            invariants.append(self.translate_contract(node.body[bodyindex]))
            bodyindex += 1
        body = flatten(
            [self.translate_stmt(stmt) for stmt in node.body[bodyindex:]])
        body = self.translate_block(body, self.to_position(node),
                                    self.noinfo())
        return [self.viper.While(cond, invariants, locals, body,
                                 self.to_position(node),
                                 self.noinfo())]

    def translate_stmt_Return(self,
                              node: ast.Return) -> List[Stmt]:
        type = self.current_function.type
        rhs_stmt, rhs = self.translate_expr(node.value)
        assign = self.viper.LocalVarAssign(
            self.viper.LocalVar('_res', self.translate_type(type),
                                self.noposition(), self.noinfo()),
            rhs, self.to_position(node),
            self.noinfo())
        tries = self._get_surrounding_try_blocks(
            self.current_function.try_blocks, node)
        for try_block in tries:
            if try_block.finally_block:
                lhs = try_block.get_finally_var(self).ref
                rhs = self.viper.IntLit(1, self.noposition(), self.noinfo())
                finally_assign = self.viper.LocalVarAssign(lhs, rhs,
                                                           self.noposition(),
                                                           self.noinfo())
                jmp = self.viper.Goto(try_block.finally_name,
                                      self.to_position(node),
                                      self.noinfo())
                return rhs_stmt + [assign, finally_assign, jmp]
        jmp_to_end = self.viper.Goto("__end", self.to_position(node),
                                     self.noinfo())
        return rhs_stmt + [assign, jmp_to_end]

    def is_pre(self, stmt: ast.AST) -> bool:
        return get_func_name(stmt) == 'Requires'

    def is_post(self, stmt: ast.AST) -> bool:
        return get_func_name(stmt) == 'Ensures'

    def is_exception_decl(self, stmt: ast.AST) -> bool:
        return get_func_name(stmt) == 'Exsures'

    def is_invariant(self, stmt: ast.AST) -> bool:
        return get_func_name(stmt) == 'Invariant'

    def is_pure(self, func) -> bool:
        return (len(func.decorator_list) == 1
                and func.decorator_list[0].id == 'Pure')

    def is_predicate(self, func) -> bool:
        return (len(func.decorator_list) == 1
                and func.decorator_list[0].id == 'Predicate')

    def translate_block(self, stmtlist: List['silver.ast.Stmt'],
                        position: 'silver.ast.Position',
                        info: 'silver.ast.Info') -> Stmt:
        """
        Wraps a (Python) list of (Viper) statements into a Viper block
        """
        body = []
        for stmt in stmtlist:
            body.append(stmt)
        return self.viper.Seqn(body, position, info)

    def var_has_type(self, name: str,
                     type: PythonClass) -> 'silver.ast.DomainFuncApp':
        """
        Creates an expression checking if the var with the given name
        is of the given type.
        """
        obj_var = self.viper.LocalVar(name, self.viper.Ref,
                                     self.noposition(),
                                     self.noinfo())
        return self.type_factory.has_type(obj_var, type)

    def var_has_concrete_type(self, name: str, type: PythonClass) \
            -> 'silver.ast.DomainFuncApp':
        """
        Creates an expression checking if the var with the given name
        is of exactly the given type.
        """
        obj_var = self.viper.LocalVar(name, self.viper.Ref,
                                     self.noposition(),
                                     self.noinfo())
        return self.type_factory.has_concrete_type(obj_var, type)

    def translate_pythonvar_decl(self,
                                 var: PythonVar) -> 'silver.ast.LocalVarDecl':
        """
        Creates a variable declaration for the given PythonVar.
        To be called during the processing phase by the Analyzer.
        """
        return self.viper.LocalVarDecl(var.sil_name,
                                       self.translate_type(var.type),
                                       self.noposition(), self.noinfo())

    def translate_pythonvar_ref(self, var: PythonVar) -> Expr:
        """
        Creates a variable reference for the given PythonVar.
        To be called during the processing phase by the Analyzer.
        """
        return self.viper.LocalVar(var.sil_name,
                                   self.translate_type(var.type),
                                   self.noposition(), self.noinfo())

    def translate_type(self, cls: PythonClass) -> 'silver.ast.Type':
        """
        Translates the given type to the corresponding Viper type (Int, Ref, ..)
        """
        if 'builtins.' + cls.name in self.builtins:
            return self.builtins['builtins.' + cls.name]
        else:
            return self.viper.Ref

    def get_parameter_typeof(self,
                             param: PythonVar) -> 'silver.ast.DomainFuncApp':
        return self.var_has_type(param.sil_name, param.type)

    def translate_field(self, field: PythonField) -> 'silver.ast.Field':
        return self.viper.Field(field.sil_name,
                                self.translate_type(field.type),
                                self.to_position(field.node),
                                self.noinfo())

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

    def translate_function(self, func: PythonMethod) -> 'silver.ast.Function':
        """
        Translates a pure Python function (may or not belong to a class) to a
        Viper function
        """
        old_function = self.current_function
        self.current_function = func
        type = self.translate_type(func.type)
        args = []
        for arg in func.args:
            args.append(func.args[arg].decl)
        if func.declared_exceptions:
            raise InvalidProgramException(func.node,
                                          'function.throws.exception')
        # create preconditions
        pres = []
        for pre in func.precondition:
            stmt, expr = self.translate_expr(pre)
            if stmt:
                raise InvalidProgramException(pre, 'purity.violated')
            pres.append(expr)
        # create postconditions
        posts = []
        for post in func.postcondition:
            stmt, expr = self.translate_expr(post)
            if stmt:
                raise InvalidProgramException(post, 'purity.violated')
            posts.append(expr)
        # create typeof preconditions
        for arg in func.args:
            if not func.args[arg].type.name in PRIMITIVES:
                pres.append(self.get_parameter_typeof(func.args[arg]))
        statements = func.node.body
        body_index = self.get_body_start_index(statements)
        # translate body
        body = self.translate_exprs(statements[body_index:], func)
        self.current_function = old_function
        name = func.sil_name
        return self.viper.Function(name, args, type, pres, posts, body,
                                   self.noposition(), self.noinfo())

    def _get_error_var(self, stmt: ast.AST) -> 'LocalVarRef':
        """
        Returns the error variable of the try-block protecting stmt, otherwise
        the error return variable of the surrounding function, otherwise
        creates a new local variable of type Exception.
        """
        tries = self._get_surrounding_try_blocks(self.current_function.try_blocks,
                                         stmt)
        if tries:
            return tries[0].get_error_var(self).ref
        else:
            if self.current_function.declared_exceptions:
                return self.current_function.error_var
            else:
                new_var = self.current_function.create_variable('error',
                    self.program.classes['Exception'], self)
                return new_var.ref

    def _create_goto_finally(self, tries: List[PythonTryBlock],
                             error_var: 'LocalVar') -> Optional[Stmt]:
        """
        If any of the blocks in tries has a finally-block, creates and
        returns the statements to jump there.
        """
        index = 0
        while index < len(tries):
            current = tries[index]
            if current.finally_block:
                # propagate return value
                var_next = current.get_finally_var(self)
                var_next_error = current.get_error_var(self)
                next_error_assign = self.viper.LocalVarAssign(var_next_error.ref,
                                                              error_var,
                                                              self.noposition(),
                                                              self.noinfo())
                number_two = self.viper.IntLit(2, self.noposition(),
                                               self.noinfo())
                next_assign = self.viper.LocalVarAssign(var_next.ref,
                                                        number_two,
                                                        self.noposition(),
                                                        self.noinfo())
                # goto finally block
                goto_next = self.viper.Goto(current.finally_name,
                                            self.noposition(),
                                            self.noinfo())
                return_block = [next_assign, goto_next]
                result = self.translate_block(return_block, self.noposition(),
                                              self.noinfo())
                return result
            index += 1
        return None

    def translate_finally(self, block: PythonTryBlock) \
            -> List[Stmt]:
        """
        Creates a code block representing the finally-block belonging to block,
        to be put at the end of a Viper method.
        """
        pos = self.to_position(block.node)
        info = self.noinfo()
        label = self.viper.Label(block.finally_name,
                                 self.to_position(block.node), self.noinfo())
        body = [label]
        for stmt in block.finally_block:
            body += self.translate_stmt(stmt)
        finally_var = block.get_finally_var(self)
        tries = self._get_surrounding_try_blocks(self.current_function.try_blocks,
                                         block.node)
        goto_post = self.viper.Goto('post_' + block.name, pos, info)
        goto_end = self.viper.Goto('__end', pos, info)
        empty_stmt = self.translate_block([], pos, info)
        # assert tries
        index = 0
        if block in tries:
            assert tries[0] == block
            index = 1
        except_block = []
        return_block = []
        while index < len(tries):
            current = tries[index]
            if not return_block:
                if current.finally_block:
                    # propagate return value
                    var_next = current.get_finally_var(self)
                    next_assign = self.viper.LocalVarAssign(var_next.ref,
                                                            finally_var.ref,
                                                            pos, info)
                    # goto finally block
                    goto_next = self.viper.Goto(current.finally_name, pos, info)
                    return_block = [next_assign, goto_next]
            for handler in current.handlers:
                # if handler applies
                # goto handler
                condition = self.var_has_type(block.get_error_var(self).sil_name,
                                              handler.exception)
                goto = self.viper.Goto(handler.name, pos, info)
                if_handler = self.viper.If(condition, goto, empty_stmt, pos,
                                           info)
                except_block.append(if_handler)
            if current.finally_block:
                # propagate return value
                # goto finally block
                except_block += return_block
                break
            index += 1
        if not return_block:
            return_block = [goto_end]
        if self.current_function.declared_exceptions:
            return_block.append(goto_end)
        else:
            false = self.viper.FalseLit(pos, info)
            assert_false = self.viper.Exhale(false, pos, info)
            return_block.append(assert_false)

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


    def translate_handler(self, handler: PythonExceptionHandler) -> List[Stmt]:
        """
        Creates a code block representing an exception handler, to be put at
        the end of a Viper method
        """
        label = self.viper.Label(handler.name,
                                 self.to_position(handler.node),
                                 self.noinfo())
        assert not self.var_aliases
        if handler.exception_name:
            self.var_aliases = {
                handler.exception_name: handler.try_block.get_error_var(self)
            }
        body = []
        for stmt in handler.body:
            body += self.translate_stmt(stmt)
        body_block = self.translate_block(body,
                                          self.to_position(handler.node),
                                          self.noinfo())
        if handler.try_block.finally_block:
            next = handler.try_block.finally_name
            lhs = handler.try_block.get_finally_var(self).ref
            rhs = self.viper.IntLit(0, self.noposition(), self.noinfo())
            var_set = self.viper.LocalVarAssign(lhs, rhs, self.noposition(),
                                                self.noinfo())
            next_var_set = [var_set]
        else:
            next = 'post_' + handler.try_block.name
            next_var_set = []
        goto_end = self.viper.Goto(next,
                                   self.to_position(handler.node),
                                   self.noinfo())
        self.var_aliases = None
        return [label, body_block] + next_var_set + [goto_end]


    def extract_contract(self, method: PythonMethod, errorvarname: str,
                         isconstructor: bool) -> Tuple[List[Expr], List[Expr]]:
        """
        Extracts the pre and postcondition from a given method
        """
        error_var_ref = self.viper.LocalVar(errorvarname, self.viper.Ref,
                                            self.noposition(),
                                            self.noinfo())
        # create preconditions
        pres = []
        for pre in method.precondition:
            stmt, expr = self.translate_expr(pre)
            if stmt:
                raise InvalidProgramException(pre, 'purity.violated')
            pres.append(expr)
        # create postconditions
        posts = []
        noerror = self.viper.EqCmp(error_var_ref,
                                   self.viper.NullLit(self.noposition(),
                                                      self.noinfo()),
                                   self.noposition(), self.noinfo())
        error = self.viper.NeCmp(error_var_ref,
                                 self.viper.NullLit(self.noposition(),
                                                    self.noinfo()),
                                 self.noposition(), self.noinfo())
        for post in method.postcondition:
            stmt, expr = self.translate_expr(post)
            if stmt:
                raise InvalidProgramException(post, 'purity.violated')
            if method.declared_exceptions:
                expr = self.viper.Implies(noerror, expr,
                                          self.to_position(post),
                                          self.noinfo())
            posts.append(expr)
        # create exceptional postconditions
        error_type_conds = []
        error_type_pos = self.to_position(method.node)
        for exception in method.declared_exceptions:
            oldpos = self.position
            if self.position is None:
                self.position = error_type_pos
            has_type = self.var_has_type('_err',
                                         self.program.classes[exception])
            error_type_conds.append(has_type)
            self.position = oldpos
            condition = self.viper.And(error, has_type, self.noposition(),
                                       self.noinfo())
            for post in method.declared_exceptions[exception]:
                stmt, expr = self.translate_expr(post)
                if stmt:
                    raise InvalidProgramException(post, 'purity.violated')
                expr = self.viper.Implies(condition, expr,
                                          self.to_position(post),
                                          self.noinfo())
                posts.append(expr)

        error_type_cond = None
        for type in error_type_conds:
            if error_type_cond is None:
                error_type_cond = type
            else:
                error_type_cond = self.viper.Or(error_type_cond, type,
                                                error_type_pos,
                                                self.noinfo())
        if error_type_cond is not None:
            posts.append(self.viper.Implies(error, error_type_cond,
                                            self.to_position(post),
                                            self.noinfo()))
        # create typeof preconditions
        for arg in method.args:
            if not (method.args[arg].type.name in PRIMITIVES
                    or (isconstructor and arg == next(iter(method.args)))):
                pres.append(self.get_parameter_typeof(method.args[arg]))
        return pres, posts

    def to_position(self, node):
        """
        Extracts the position from a node.
        If self.position is set to override the actual position, returns that.
        """
        if self.position is not None:
            return self.position
        else:
            return self.viper.to_position(node)

    def noposition(self):
        return self.to_position(None)

    def to_info(self, comments):
        """
        Wraps the given comments into an Info object.
        If self.info is set to override the given info, returns that.
        """
        if self.info is not None:
            return self.info
        if comments:
            return self.viper.SimpleInfo(comments)
        else:
            return self.viper.NoInfo

    def noinfo(self):
        return self.to_info([])

    def create_subtyping_check(self,
                               method: PythonMethod) -> 'silver.ast.Callable':
        """
        Creates a Viper function/method with the contract of the overridden
        function which calls the overriding function, to check behavioural
        subtyping.
        """
        old_function = self.current_function
        self.current_function = method.overrides
        assert self.position is None
        self.position = self.viper.to_position(method.node)
        self.info = self.viper.SimpleInfo(['behavioural.subtyping'])
        self._check_override_validity(method)
        params = []
        args = []

        mname = self.program.get_fresh_name(method.sil_name + '_subtyping')
        pres, posts = self.extract_contract(method.overrides, '_err', False)
        for arg in method.overrides.args:
            params.append(method.overrides.args[arg].decl)
            args.append(method.overrides.args[arg].ref)
        self_arg = method.overrides.args[next(iter(method.overrides.args))]
        has_subtype = self.var_has_type(self_arg.sil_name, method.cls)
        called_name = method.sil_name
        if method.pure:
            pres = pres + [has_subtype]
            formal_args = []
            for arg in method.args:
                formal_args.append(method.args[arg].decl)
            type = self.translate_type(method.type)
            func_app = self.viper.FuncApp(called_name, args, self.noposition(),
                                          self.noinfo(), type, formal_args)
            self.current_function = old_function
            result = self.viper.Function(mname, params, type, pres, posts,
                                         func_app, self.noposition(),
                                         self.noinfo())
            self.position = None
            self.info = None
            return result
        else:
            results, targets, body = self._create_subtyping_check_body_impure(
                method, has_subtype, called_name, args)
            self.current_function = old_function
            result = self.viper.Method(mname, params, results, pres, posts, [],
                                       body, self.noposition(),
                                       self.noinfo())
            self.position = None
            self.info = None
            return result

    def _check_override_validity(self, method: PythonMethod) -> None:
        """
        Checks if the given method overrides its equivalent in a superclass
        in a valid way, otherwise raises an InvalidProgramException.
        """
        if len(method.args) != len(method.overrides.args):
            raise InvalidProgramException(method.node, 'invalid.override')
        for exc in method.declared_exceptions:
            exc_class = self.program.classes[exc]
            allowed = False
            for superexc in method.overrides.declared_exceptions:
                superexcclass = self.program.classes[superexc]
                if exc_class.issubtype(superexcclass):
                    allowed = True
                    break
            if not allowed:
                raise InvalidProgramException(method.node, 'invalid.override')
                # TODO check if exceptional postconditions imply super postconds
        if method.pure:
            if not method.overrides.pure:
                raise InvalidProgramException(method.node, 'invalid.override')
        else:
            if method.overrides.pure:
                raise InvalidProgramException(method.node, 'invalid.override')

    def _create_subtyping_check_body_impure(self, method: PythonMethod,
            has_subtype: Expr, calledname: str, args: List[Expr]) -> \
            Tuple[List['ast.LocalVarDecl'], List['ast.LocalVar'], Stmt]:
        results = []
        targets = []
        if method.type:
            type = self.translate_type(method.type)
            result_var_decl = self.viper.LocalVarDecl('_res', type,
                                                      self.to_position(method.node),
                                                      self.noinfo())
            result_var_ref = self.viper.LocalVar('_res', type,
                                                 self.to_position(
                                                    method.node),
                                                 self.noinfo())
            results.append(result_var_decl)
            targets.append(result_var_ref)
        error_var_decl = self.viper.LocalVarDecl('_err', self.viper.Ref,
                                                 self.noposition(),
                                                 self.noinfo())
        error_var_ref = self.viper.LocalVar('_err', self.viper.Ref,
                                            self.noposition(),
                                            self.noinfo())
        if method.overrides.declared_exceptions:
            results.append(error_var_decl)
        if method.declared_exceptions:
            targets.append(error_var_ref)
        call = self.viper.MethodCall(calledname, args, targets,
                                     self.noposition(),
                                     self.noinfo())
        subtype_assume = self.viper.Inhale(has_subtype, self.noposition(),
                                           self.noinfo())
        body = [subtype_assume, call]
        body_block = self.translate_block(body, self.noposition(),
                                          self.noinfo())
        return results, targets, body_block

    def translate_predicate(self, pred: PythonMethod) -> 'ast.silver.Predicate':
        """
        Translates pred to a Silver predicate.
        """
        if pred.type.name != 'bool':
            raise InvalidProgramException(pred.node, 'invalid.predicate')
        assert self.current_function is None
        self.current_function = pred
        args = []
        for arg in pred.args:
            args.append(pred.args[arg].decl)
        body = self.translate_exprs(pred.node.body, pred)
        self.current_function = pred
        return self.viper.Predicate(pred.sil_name, args, body,
                                    self.to_position(pred.node), self.noinfo())

    def translate_predicate_family(self, root: PythonMethod,
            preds: List[PythonMethod]) -> 'ast.silver.Predicate':
        """
        Translates the methods in preds, whose root (which they all override)
        is root, to a family-predicate in Silver.
        """
        dependencies = {}
        for pred in preds:
            value = {pred.overrides} if pred.overrides else set()
            dependencies[pred] = value
        sorted = toposort_flatten(dependencies)

        name = root.sil_name
        args = []
        self_var_ref = root.args[next(iter(root.args))].ref
        for arg in root.args:
            args.append(root.args[arg].decl)
        body = None
        assert not self.var_aliases
        for instance in sorted:
            self.var_aliases = {}
            assert not self.current_function
            if instance.type.name != 'bool':
                raise InvalidProgramException(instance.node,
                                              'invalid.predicate')
            self.current_function = instance
            for i in range(len(root.args)):
                root_name = list(root.args.keys())[i]
                root_var = root.args[root_name]
                current_name = list(instance.args.keys())[i]
                self.var_aliases[current_name] = root_var
            if len(instance.node.body) != 1:
                raise InvalidProgramException(instance.node, 'invalid.predicate')
            stmt, current = self.translate_expr(instance.node.body[0])
            if stmt:
                raise InvalidProgramException(instance.node, 'invalid.predicate')
            has_type = self.type_factory.has_type(self_var_ref, instance.cls)
            implication = self.viper.Implies(has_type, current,
                self.to_position(instance.node), self.noinfo())
            self.current_function = None
            if body:
                body = self.viper.And(body, implication,
                    self.to_position(root.node), self.noinfo())
            else:
                body = implication
        self.var_aliases = None
        return self.viper.Predicate(name, args, body,
                                    self.to_position(root.node), self.noinfo())

    def translate_method(self, method: PythonMethod) -> 'silver.ast.Method':
        """
        Translates an impure Python function (may or not belong to a class) to
        a Viper method
        """
        old_function = self.current_function
        self.current_function = method
        results = []
        if method.type is not None:
            type = self.translate_type(method.type)
            results.append(self.viper.LocalVarDecl('_res', type,
                                                   self.to_position(
                                                       method.node),
                                                   self.noinfo()))
        error_var_decl = self.viper.LocalVarDecl('_err', self.viper.Ref,
                                                 self.noposition(),
                                                 self.noinfo())
        error_var_ref = self.viper.LocalVar('_err', self.viper.Ref,
                                            self.noposition(),
                                            self.noinfo())
        method.error_var = error_var_ref
        pres, posts = self.extract_contract(method, '_err', False)
        if method.cls and method.name == '__init__':
            self_var = method.args[next(iter(method.args))].ref
            _, accs = self._get_all_fields(method.cls, self_var,
                                           self.to_position(method.node))
            null = self.viper.NullLit(self.noposition(), self.noinfo())
            not_null = self.viper.NeCmp(self_var, null, self.noposition(),
                                        self.noinfo())
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
            false = self.viper.FalseLit(self.noposition(), self.noinfo())
            assume_false = self.viper.Inhale(false, self.noposition(),
                                             self.noinfo())
            body.append(assume_false)
            locals = []
        else:
            if method.declared_exceptions:
                body.append(self.viper.LocalVarAssign(error_var_ref,
                    self.viper.NullLit(self.noposition(), self.noinfo()),
                    self.noposition(), self.noinfo()))
            body += flatten(
                [self.translate_stmt(stmt) for stmt in
                 method.node.body[body_index:]])
            body.append(self.viper.Goto('__end', self.noposition(),
                                        self.noinfo()))
            for block in method.try_blocks:
                for handler in block.handlers:
                    body += self.translate_handler(handler)
                if block.else_block:
                    body += self.translate_handler(block.else_block)
                if block.finally_block:
                    body += self.translate_finally(block)
            locals = []
            for local in method.locals:
                locals.append(method.locals[local].decl)
            body += [self.viper.Label("__end", self.noposition(),
                                      self.noinfo())]
        body_block = self.translate_block(body,
                                         self.to_position(method.node),
                                         self.noinfo())
        self.current_function = old_function
        name = method.sil_name
        return self.viper.Method(name, args, results, pres, posts,
                                 locals, body_block,
                                 self.to_position(method.node),
                                 self.noinfo())

    def _get_all_fields(self, cls: PythonClass, selfvar: 'silver.ast.LocalVar',
            position: 'silver.ast.Position') \
            -> Tuple['silver.ast.Field', 'silver.ast.FieldAccessPredicate']:
        accs = []
        fields = []
        while cls is not None:
            for fieldname in cls.fields:
                field = cls.fields[fieldname]
                if field.inherited is None:
                    fields.append(field.field)
                    acc = self.viper.FieldAccess(selfvar, field.field,
                                                 position, self.noinfo())
                    perm = self.viper.FullPerm(position, self.noinfo())
                    pred = self.viper.FieldAccessPredicate(acc,
                                                           perm,
                                                           position,
                                                           self.noinfo())
                    accs.append(pred)
            cls = cls.superclass
        return fields, accs

    def create_global_var_function(self,
                                   var: PythonVar) -> 'silver.ast.Function':
        """
        Creates a Viper function representing the given global variable.
        """
        type = self.translate_type(var.type)
        if type == self.viper.Ref:
            raise UnsupportedException(var.node)
        position = self.to_position(var.node)
        posts = []
        result = self.viper.Result(type, position, self.noinfo())
        stmt, value = self.translate_expr(var.value)
        if stmt:
            raise InvalidProgramException('purity.violated', var.node)
        posts.append(
            self.viper.EqCmp(result, value, position, self.noinfo()))
        return self.viper.Function(var.sil_name, [], type, [], posts, None,
                                   self.to_position(var.node),
                                   self.noinfo())

    def translate_program(self, program: PythonProgram, sil_progs: List) \
            -> 'silver.ast.Program':
        """
        Translates a PythonProgram created by the analyzer to a Viper program.
        """
        self.current_class = None
        self.current_function = None
        self.program = program
        domains = []
        fields = []
        functions = []
        predicates = []
        methods = []

        for sil_prog in sil_progs:
            domains += self.viper.to_list(sil_prog.domains())
            fields += self.viper.to_list(sil_prog.fields())
            functions += self.viper.to_list(sil_prog.functions())
            predicates += self.viper.to_list(sil_prog.predicates())
            methods += self.viper.to_list(sil_prog.methods())

        type_funcs = self.type_factory.get_default_functions()
        type_axioms = self.type_factory.get_default_axioms()

        predicate_families = OrderedDict()

        for var in program.global_vars:
            functions.append(
                self.create_global_var_function(program.global_vars[var]))

        for class_name in program.classes:
            if class_name in PRIMITIVES:
                continue
            cls = program.classes[class_name]
            for fieldname in cls.fields:
                field = cls.fields[fieldname]
                if field.inherited is None:
                    silfield = self.translate_field(field)
                    field.field = silfield
                    fields.append(silfield)

        for function in program.functions:
            functions.append(
                self.translate_function(program.functions[function]))
        for method in program.methods:
            methods.append(self.translate_method(program.methods[method]))
        for pred in program.predicates:
            predicates.append(self.translate_predicate(program.predicates[pred]))
        for class_name in program.classes:
            if class_name in PRIMITIVES:
                continue
            cls = program.classes[class_name]
            old_class = self.current_class
            self.current_class = cls
            funcs, axioms = self.type_factory.create_type(cls)
            type_funcs.append(funcs)
            if axioms:
                type_axioms.append(axioms)
            for func_name in cls.functions:
                func = cls.functions[func_name]
                if func.interface:
                    continue
                functions.append(self.translate_function(func))
                if func.overrides:
                    functions.append(self.create_subtyping_check(func))
            for method_name in cls.methods:
                method = cls.methods[method_name]
                if method.interface:
                    continue
                methods.append(self.translate_method(method))
                if method_name != '__init__' and method.overrides:
                    methods.append(self.create_subtyping_check(method))
            for pred_name in cls.predicates:
                pred = cls.predicates[pred_name]
                cpred = pred
                while cpred.overrides:
                    cpred = cpred.overrides
                if cpred in predicate_families:
                    predicate_families[cpred].append(pred)
                else:
                    predicate_families[cpred] = [pred]
            # methods.append(self.create_constructor(cls))
            self.current_class = old_class

        for root in predicate_families:
            pf = self.translate_predicate_family(root, predicate_families[root])
            predicates.append(pf)

        domains += [self.viper.Domain(self.typedomain, type_funcs, type_axioms,
                                     [], self.noposition(), self.noinfo())]

        prog = self.viper.Program(domains, fields, functions, predicates,
                                  methods, self.noposition(),
                                  self.noinfo())
        return prog
