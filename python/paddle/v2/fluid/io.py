#   Copyright (c) 2018 PaddlePaddle Authors. All Rights Reserve.
#
# Licensed under the Apache License, Version 2.0 (the "License");
# you may not use this file except in compliance with the License.
# You may obtain a copy of the License at
#
#     http://www.apache.org/licenses/LICENSE-2.0
#
# Unless required by applicable law or agreed to in writing, software
# distributed under the License is distributed on an "AS IS" BASIS,
# WITHOUT WARRANTIES OR CONDITIONS OF ANY KIND, either express or implied.
# See the License for the specific language governing permissions and
# limitations under the License.

import os

from paddle.v2.fluid.evaluator import Evaluator
from paddle.v2.fluid.framework import Program, Parameter, default_main_program, Variable
from . import core

__all__ = [
    'save_vars',
    'save_params',
    'save_persistables',
    'load_vars',
    'load_params',
    'load_persistables',
    'save_inference_model',
    'load_inference_model',
    'get_inference_program',
]


def is_parameter(var):
    """Check whether the variable is a Parameter.

    This function checks whether the input variable is a Parameter.

    Args:
        var : The input variable.

    Returns:
        boolean result whether the variable is a Parameter.
    """
    return isinstance(var, Parameter)


def is_persistable(var):
    return var.persistable


def _clone_var_in_block_(block, var):
    assert isinstance(var, Variable)
    return block.create_var(
        name=var.name,
        shape=var.shape,
        dtype=var.dtype,
        type=var.type,
        lod_level=var.lod_level,
        persistable=True)


def save_vars(executor, dirname, main_program=None, vars=None, predicate=None):
    """
    Save variables to directory by executor.

    :param executor: executor that save variable
    :param dirname: directory path
    :param main_program: program. If vars is None, then filter all variables in this
    program which fit `predicate`. Default default_main_program.
    :param predicate: The Predicate describes a callable that returns a variable
    as a bool. If it returns true, the variables will be saved.
    :param vars: variables need to be saved. If specify vars, program & predicate
    will be ignored
    :return: None
    """
    if vars is None:
        if main_program is None:
            main_program = default_main_program()
        if not isinstance(main_program, Program):
            raise TypeError("program should be as Program type or None")

        save_vars(
            executor,
            dirname=dirname,
            vars=filter(predicate, main_program.list_vars()))
    else:
        save_program = Program()
        save_block = save_program.global_block()
        for each_var in vars:
            new_var = _clone_var_in_block_(save_block, each_var)
            save_block.append_op(
                type='save',
                inputs={'X': [new_var]},
                outputs={},
                attrs={'file_path': os.path.join(dirname, new_var.name)})
        executor.run(save_program)


def save_params(executor, dirname, main_program=None):
    """
    Save all parameters to directory with executor.
    """
    save_vars(
        executor,
        dirname=dirname,
        main_program=main_program,
        vars=None,
        predicate=is_parameter)


def save_persistables(executor, dirname, main_program=None):
    """
    Save all persistables to directory with executor.
    """
    save_vars(
        executor,
        dirname=dirname,
        main_program=main_program,
        vars=None,
        predicate=is_persistable)


def load_vars(executor, dirname, main_program=None, vars=None, predicate=None):
    """
    Load variables from directory by executor.

    :param executor: executor that save variable
    :param dirname: directory path
    :param main_program: program. If vars is None, then filter all variables in this
    program which fit `predicate`. Default default_main_program().
    :param predicate: The Predicate describes a callable that returns a variable
    as a bool. If it returns true, the variables will be loaded.
    :param vars: variables need to be loaded. If specify vars, program &
    predicate will be ignored
    :return: None
    """
    if vars is None:
        if main_program is None:
            main_program = default_main_program()
        if not isinstance(main_program, Program):
            raise TypeError("program's type should be Program")

        load_vars(
            executor,
            dirname=dirname,
            vars=filter(predicate, main_program.list_vars()))
    else:
        load_prog = Program()
        load_block = load_prog.global_block()
        for each_var in vars:
            assert isinstance(each_var, Variable)
            new_var = _clone_var_in_block_(load_block, each_var)
            load_block.append_op(
                type='load',
                inputs={},
                outputs={"Out": [new_var]},
                attrs={'file_path': os.path.join(dirname, new_var.name)})

        executor.run(load_prog)


def load_params(executor, dirname, main_program=None):
    """
    load all parameters from directory by executor.
    """
    load_vars(
        executor,
        dirname=dirname,
        main_program=main_program,
        predicate=is_parameter)


def load_persistables(executor, dirname, main_program=None):
    """
    load all persistables from directory by executor.
    """
    load_vars(
        executor,
        dirname=dirname,
        main_program=main_program,
        predicate=is_persistable)


def get_inference_program(target_vars, main_program=None):
    if main_program is None:
        main_program = default_main_program()
    if not isinstance(target_vars, list):
        target_vars = [target_vars]
    vars = []
    for var in target_vars:
        if isinstance(var, Evaluator):
            vars.extend(var.states)
            vars.extend(var.metrics)
        else:
            vars.append(var)
    pruned_program = main_program.prune(targets=vars)
    inference_program = pruned_program.inference_optimize()
    return inference_program


def prepend_feed_ops(inference_program,
                     feed_target_names,
                     feed_holder_name='feed'):
    global_block = inference_program.global_block()
    feed_var = global_block.create_var(
        name=feed_holder_name,
        type=core.VarDesc.VarType.FEED_MINIBATCH,
        persistable=True)

    for i, name in enumerate(feed_target_names):
        out = global_block.var(name)
        global_block.prepend_op(
            type='feed',
            inputs={'X': [feed_var]},
            outputs={'Out': [out]},
            attrs={'col': i})


def append_fetch_ops(inference_program,
                     fetch_target_names,
                     fetch_holder_name='fetch'):
    global_block = inference_program.global_block()
    fetch_var = global_block.create_var(
        name=fetch_holder_name,
        type=core.VarDesc.VarType.FETCH_LIST,
        persistable=True)

    for i, name in enumerate(fetch_target_names):
        global_block.append_op(
            type='fetch',
            inputs={'X': [name]},
            outputs={'Out': [fetch_var]},
            attrs={'col': i})


def save_inference_model(dirname,
                         feeded_var_names,
                         target_vars,
                         executor,
                         main_program=None):
    """
    Build a model especially for inference,
    and save it to directory by the executor.

    :param dirname: directory path
    :param feeded_var_names: Names of variables that need to be feeded data during inference
    :param target_vars: Variables from which we can get inference results.
    :param executor: executor that save inference model
    :param main_program: original program, which will be pruned to build the inference model.
            Default default_main_program().

    :return: None
    """
    if isinstance(feeded_var_names, basestring):
        feeded_var_names = [feeded_var_names]
    else:
        if not (bool(feeded_var_names) and all(
                isinstance(name, basestring) for name in feeded_var_names)):
            raise ValueError("'feed_var_names' should be a list of str.")

    if isinstance(target_vars, Variable):
        target_vars = [target_vars]
    else:
        if not (bool(target_vars) and all(
                isinstance(var, Variable) for var in target_vars)):
            raise ValueError("'target_vars' should be a list of Variable.")

    if main_program is None:
        main_program = default_main_program()

    if not os.path.isdir(dirname):
        os.makedirs(dirname)

    pruned_program = main_program.prune(targets=target_vars)
    inference_program = pruned_program.inference_optimize()
    fetch_var_names = [v.name for v in target_vars]

    prepend_feed_ops(inference_program, feeded_var_names)
    append_fetch_ops(inference_program, fetch_var_names)

    model_file_name = dirname + "/__model__"
    with open(model_file_name, "wb") as f:
        f.write(inference_program.desc.serialize_to_string())

    save_params(executor, dirname, main_program)


def load_persistables_if_exist(executor, dirname, main_program=None):
    filenames = next(os.walk(dirname))[2]
    filenames = set(filenames)

    def _is_presistable_and_exist_(var):
        if not is_persistable(var):
            return False
        else:
            return var.name in filenames

    load_vars(
        executor,
        dirname,
        main_program=main_program,
        vars=None,
        predicate=_is_presistable_and_exist_)


def get_feed_targets_names(program):
    feed_targets_names = []
    global_block = program.global_block()
    for op in global_block.ops:
        if op.desc.type() == 'feed':
            feed_targets_names.insert(0, op.desc.output('Out')[0])
    return feed_targets_names


def get_fetch_targets_names(program):
    fetch_targets_names = []
    global_block = program.global_block()
    for op in global_block.ops:
        if op.desc.type() == 'fetch':
            fetch_targets_names.append(op.desc.input('X')[0])
    return fetch_targets_names


def load_inference_model(dirname, executor):
    """
    Load inference model from a directory

    :param dirname: directory path
    :param executor: executor that load inference model

    :return: [program, feed_target_names, fetch_targets]
             program: program especially for inference.
             feed_target_names: Names of variables that need to feed data
             fetch_targets: Variables from which we can get inference results.
    """
    if not os.path.isdir(dirname):
        raise ValueError("There is no directory named '%s'", dirname)

    model_file_name = dirname + "/__model__"
    with open(model_file_name, "rb") as f:
        program_desc_str = f.read()

    program = Program.parse_from_string(program_desc_str)
    load_persistables_if_exist(executor, dirname, program)

    feed_target_names = get_feed_targets_names(program)
    fetch_target_names = get_fetch_targets_names(program)
    fetch_targets = [
        program.global_block().var(name) for name in fetch_target_names
    ]

    return [program, feed_target_names, fetch_targets]


def get_parameter_value(para, executor):
    """
    Get the LoDTensor for the parameter

    :param executor: executor for retrieving the value
    :param para: the given parameter
    :return: the LoDTensor for the parameter
    """
    assert is_parameter(para)

    get_program = Program()
    block = get_program.global_block()
    new_var = _clone_var_in_block_(block, para)
    return executor.run(get_program, feed={}, fetch_list=[new_var])[0]


def get_parameter_value_by_name(name, executor, program=None):
    """
    Get the LoDTensor for paramter with the given name

    :param executor: executor for retrieving the value
    :param name: the name of the parameter
    :param program: the program where the variable is found
            Default default_main_program().
    :return: the LoDTensor for the variable
    """
    if program is None:
        program = default_main_program()
    var = program.global_block().var(name)
    return get_parameter_value(var, executor)
