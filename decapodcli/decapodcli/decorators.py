# -*- coding: utf-8 -*-
# Copyright (c) 2016 Mirantis Inc.
#
# Licensed under the Apache License, Version 2.0 (the "License");
# you may not use this file except in compliance with the License.
# You may obtain a copy of the License at
#
#    http://www.apache.org/licenses/LICENSE-2.0
#
# Unless required by applicable law or agreed to in writing, software
# distributed under the License is distributed on an "AS IS" BASIS,
# WITHOUT WARRANTIES OR CONDITIONS OF ANY KIND, either express or
# implied.
# See the License for the specific language governing permissions and
# limitations under the License.
"""A list of decorators which are used in CLI."""


from __future__ import absolute_import
from __future__ import unicode_literals

import os

import click
import six

from decapodcli import param_types
from decapodcli import utils

from decapodlib import exceptions

try:
    import pygments
except ImportError:
    pygments = None


def catch_errors(func):
    """Decorator which catches all errors and tries to print them."""

    @six.wraps(func)
    @click.pass_context
    def decorator(ctx, *args, **kwargs):
        try:
            return func(*args, **kwargs)
        except exceptions.DecapodAPIError as exc:
            utils.format_output_json(ctx, exc.json, True)
        except exceptions.DecapodError as exc:
            click.echo(six.text_type(exc), err=True)
        finally:
            ctx.close()

        ctx.exit(os.EX_SOFTWARE)

    return decorator


def with_client(func):
    """Decorator which pass both client and model client to method."""

    @six.wraps(func)
    @click.pass_context
    def decorator(ctx, *args, **kwargs):
        kwargs["client"] = ctx.obj["client"]
        return func(*args, **kwargs)

    return decorator


def format_output(func):
    """Decorator which formats output."""

    @six.wraps(func)
    @click.pass_context
    def decorator(ctx, *args, **kwargs):
        response = func(*args, **kwargs)
        if not response:
            return

        if ctx.obj["format"] == "json":
            utils.format_output_json(ctx, response)

    return decorator


def with_color(func):
    """Decorator which adds --color option if available."""

    if pygments is None:
        def decorator(*args, **kwargs):
            kwargs["color"] = None
            return func(*args, **kwargs)
    else:
        decorator = click.option(
            "--color",
            default=None,
            type=click.Choice(["light", "dark"]),
            help=(
                "Colorize output. By default no color is used. "
                "Parameter means colorscheme of the terminal")
        )(func)

    decorator = six.wraps(func)(decorator)

    return decorator


def with_pagination(func):
    """Add pagination-related commandline options."""

    @six.wraps(func)
    @click.option(
        "--page", "-p",
        type=int,
        default=None,
        help="Page to request."
    )
    @click.option(
        "--per_page", "-r",
        type=int,
        default=None,
        help="How many items should be displayed per page."
    )
    @click.option(
        "--all", "-a",
        is_flag=True,
        help=(
            "Show all items, without pagination. "
            "Default behavior, 'page' and 'per_page' options disable this "
            "option."
        )
    )
    @click.option(
        "--list", "-l",
        type=click.Choice(["active", "archived", "all"]),
        show_default=True,
        default="active",
        help="List only certain class of elements. 'active' is default."
    )
    @click.option(
        "--sort-by", "-s",
        default="",
        type=param_types.SORT_BY,
        help=(
            "Comma-separated list of fieldnames for sorting. To define "
            "direction, please put '-' or '+' before name ('+' explicitly "
            "means). For example: 'time_deleted,-name,+version' means "
            "that sorting will be done by tuple (time_deleted ASC, "
            "name DESC, version ASC)"
        )
    )
    @click.option(
        "--no-envelope", "-n",
        is_flag=True,
        help=(
            "Remove pagination envelope, just list items. If all items "
            "requested, this implicitly meant."
        )
    )
    @click.pass_context
    def decorator(ctx, *args, **kwargs):
        all_items = kwargs.pop("all", None)
        page = kwargs.pop("page", None)
        per_page = kwargs.pop("per_page", None)
        no_envelope = kwargs.pop("no_envelope", None)
        list_elements = kwargs.pop("list", "active")
        sort_by = kwargs.pop("sort_by", {})

        all_items = all_items or not (page or per_page)
        no_envelope = all_items or no_envelope

        if all_items:
            query_params = {"all_items": True}
        else:
            query_params = {
                "page": page,
                "per_page": per_page
            }

        query_params["filter"] = {}
        if list_elements == "all":
            query_params["filter"]["time_deleted"] = {
                "ne": "unreal_value"
            }
        elif list_elements == "archived":
            query_params["filter"]["time_deleted"] = {
                "ne": 0
            }
        else:
            del query_params["filter"]

        if sort_by:
            query_params["sort_by"] = sort_by

        kwargs["query_params"] = query_params

        response = func(*args, **kwargs)
        if no_envelope and response:
            response = response["items"]

        return response

    return decorator


def model_edit(item_id, fetch_method_name, parse_json=True):
    """Adds '--edit-model' and 'model' flags.

    If '--edit-model' is set, user text editor will be launched. If no
    changes will be done, execution will be stopped. Edited text will be
    passed into decorated function as 'model' parameter.

    If 'model' is set, it will be considered as model itself.

    If 'parse_json' is True, text will be considered as JSON and parsed
    for you.
    """

    def outer_decorator(func):
        @six.wraps(func)
        @click.option(
            "--model-editor",
            is_flag=True,
            help=(
                "Fetch model and launch editor to fix stuff. Please pay "
                "attention that only 'data' field will be available for "
                "editing."
            )
        )
        @click.option(
            "--model",
            default=None,
            type=param_types.JSON,
            help=(
                "Full model data. If this parameter is set, other options "
                "won't be used. This parameter is JSON dump of the model."
            )
        )
        @click.option(
            "--model-stdin",
            is_flag=True,
            help="Slurp model from stdin."
        )
        @click.pass_context
        def inner_decorator(ctx, model_stdin, model_editor, model,
                            *args, **kwargs):
            if not model:
                if model_stdin:
                    stream = click.get_text_stream("stdin")
                    model = "".join(stream)

                elif model_editor:
                    fetch_function = getattr(
                        ctx.obj["client"], fetch_method_name)
                    model = fetch_function(kwargs[item_id])
                    if "data" in model:
                        updated_data = utils.json_dumps(model["data"])
                        updated_data = click.edit(updated_data)
                        if not updated_data:
                            return
                        updated_data = utils.json_loads(updated_data)
                        model = fetch_function(kwargs[item_id])
                        model["data"] = updated_data
                        model = utils.json_dumps(model)
                    else:
                        model = utils.json_dumps(model)
                        model = click.edit(model)

                if (model_stdin or model_editor) and not model:
                    return

            if model and parse_json and not isinstance(model, dict):
                if isinstance(model, bytes):
                    model = model.decode("utf-8")
                model = utils.json_loads(model)

            kwargs["model"] = model

            return func(*args, **kwargs)

        return inner_decorator
    return outer_decorator


def command(command_class, paginate=False, filtered=False):
    """Decorator to group generic parameters used everywhere."""

    def decorator(func):
        func = with_client(func)
        if paginate:
            func = with_pagination(func)
        if filtered:
            func = filtered_output(func)
        func = format_output(func)
        func = catch_errors(func)

        name = utils.parameter_name(func.__name__)
        func = command_class.command(name=name)(func)

        return func

    return decorator


def filtered_output(func):
    """Decorator to support filtered output."""

    if not utils.JSON_FILTERS:
        return func

    func = click.option(
        "--filtered",
        type=param_types.FILTERED_OUTPUT,
        default="",
        help=(
            "Filter output using expression engines. Valid options are {0}."
            "To setup, you first need to put engine type upfront semicolon "
            "and expression after. Example: 'jq:.[]|.id'. Please use "
            "correspond documentation on engines."
        ).format(sorted(utils.JSON_FILTERS)))(func)

    @six.wraps(func)
    def decorator(filtered, *args, **kwargs):
        response = func(*args, **kwargs)
        if not filtered:
            return response
        expression, converter = filtered

        return converter(expression, response)

    return decorator
