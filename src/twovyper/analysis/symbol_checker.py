"""
Copyright (c) 2019 ETH Zurich
This Source Code Form is subject to the terms of the Mozilla Public
License, v. 2.0. If a copy of the MPL was not distributed with this
file, You can obtain one at http://mozilla.org/MPL/2.0/.
"""

import os

from twovyper.ast import names
from twovyper.ast.nodes import VyperProgram, VyperInterface
from twovyper.exceptions import InvalidProgramException
from twovyper.utils import first


def check_symbols(program: VyperProgram):
    _check_ghost_functions(program)
    _check_ghost_implements(program)
    _check_resources(program)


def _check_resources(program: VyperProgram):
    if not isinstance(program, VyperInterface):
        node = first(program.node.stmts) or program.node
        for interface in program.interfaces.values():
            for resource_name, resources_list in interface.resources.items():
                for resource in resources_list:
                    imported_resources = [r for r in program.resources.get(resource_name, [])
                                          if r.file == resource.file]
                    if not imported_resources:
                        prefix_length = len(os.path.commonprefix([resource.file, program.file]))
                        raise InvalidProgramException(node, 'missing.resource',
                                                      f'The interface "{interface.name}" '
                                                      f'needs a resource "{resource_name}" from '
                                                      f'".{os.path.sep}{resource.file[prefix_length:]}" but it '
                                                      f'was not imported for this contract.')
                    imported_resources = [r for r in program.resources.get(resource_name)
                                          if r.interface == resource.interface]
                    for imported_resource in imported_resources:
                        if resource.file != imported_resource.file:
                            prefix_length = len(os.path.commonprefix([resource.file, imported_resource.file]))
                            resource_file = resource.file[prefix_length:]
                            imported_resource_file = imported_resource.file[prefix_length:]
                            raise InvalidProgramException(node, 'duplicate.resource',
                                                          f'There are two versions of the resource '
                                                          f'"{resource_name}" defined in an interface '
                                                          f'"{imported_resource.interface}" one from '
                                                          f'[...]"{imported_resource_file}" the other from '
                                                          f'[...]"{resource_file}".')

        for interface_type in program.implements:
            interface = program.interfaces[interface_type.name]
            for resource_name, resource in program.own_resources.items():
                if resource_name == names.WEI:
                    continue
                if resource_name in interface.own_resources:
                    raise InvalidProgramException(resource.node, 'duplicate.resource',
                                                  f'A contract cannot redeclare a resource it already imports. '
                                                  f'The resource "{resource_name}" got already declared in the '
                                                  f'interface {interface.name}.')


def _check_ghost_functions(program: VyperProgram):
    if not isinstance(program, VyperInterface):
        node = first(program.node.stmts) or program.node
        for implemented_ghost in program.ghost_function_implementations.values():
            if program.ghost_functions.get(implemented_ghost.name) is None:
                raise InvalidProgramException(implemented_ghost.node, 'missing.ghost',
                                              f'This contract is implementing an unknown ghost function. '
                                              f'None of the interfaces, this contract implements, declares a ghost '
                                              f'function "{implemented_ghost.name}".')

        for interface in program.interfaces.values():
            for ghost_function_list in interface.ghost_functions.values():
                for ghost_function in ghost_function_list:
                    imported_ghost_functions = [ghost_func
                                                for ghost_func in program.ghost_functions.get(ghost_function.name, [])
                                                if ghost_func.file == ghost_function.file]
                    if not imported_ghost_functions:
                        prefix_length = len(os.path.commonprefix([ghost_function.file, program.file]))
                        raise InvalidProgramException(node, 'missing.ghost',
                                                      f'The interface "{interface.name}" '
                                                      f'needs a ghost function "{ghost_function.name}" from '
                                                      f'".{os.path.sep}{ghost_function.file[prefix_length:]}" but it '
                                                      f'was not imported for this contract.')
                    imported_ghost_functions = [ghost_func
                                                for ghost_func in program.ghost_functions.get(ghost_function.name)
                                                if ghost_func.interface == ghost_function.interface]
                    for imported_ghost_function in imported_ghost_functions:
                        if ghost_function.file != imported_ghost_function.file:
                            prefix_length = len(os.path.commonprefix(
                                [ghost_function.file, imported_ghost_function.file]))
                            ghost_function_file = ghost_function.file[prefix_length:]
                            imported_ghost_function_file = imported_ghost_function.file[prefix_length:]
                            raise InvalidProgramException(node, 'duplicate.ghost',
                                                          f'There are two versions of the ghost function '
                                                          f'"{ghost_function.name}" defined in an interface '
                                                          f'"{ghost_function.interface}" one from '
                                                          f'[...]"{imported_ghost_function_file}" the other from '
                                                          f'[...]"{ghost_function_file}".')


def _check_ghost_implements(program: VyperProgram):
    def check(cond, node):
        if not cond:
            msg = "A ghost function has not been implemented correctly."
            raise InvalidProgramException(node, 'ghost.not.implemented', msg)

    for itype in program.implements:
        interface = program.interfaces[itype.name]
        for ghost in interface.own_ghost_functions.values():
            implementation = program.ghost_function_implementations.get(ghost.name)
            check(implementation, program.node)
            check(implementation.name == ghost.name, implementation.node)
            check(len(implementation.args) == len(ghost.args), implementation.node)
            check(implementation.type == ghost.type, implementation.node)
