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
"""Base plugin structure for playbook."""


import abc
import contextlib
import enum
import functools
import os
import shutil
import sys
import traceback

from decapod_common import config
from decapod_common import exceptions
from decapod_common import log
from decapod_common import networkutils
from decapod_common import pathutils
from decapod_common import playbook_plugin_hints
from decapod_common import process
from decapod_common.models import task


LOG = log.getLogger(__name__)
"""Logger."""

PATH_CEPH_ANSIBLE = pathutils.ROOT.joinpath("opt", "ceph-ansible")


@enum.unique
class ServerListPolicy(enum.IntEnum):
    any_server = 0
    in_this_cluster = 1
    not_in_this_cluster = 2
    in_other_cluster = 3
    not_in_other_cluster = 4
    in_any_cluster = 5
    not_in_any_cluster = 6

    @staticmethod
    def server_list_as_string(servers):
        return ", ".join(sorted(srv.model_id for srv in servers))

    def check(self, cluster_model, servers):
        cls = self.__class__

        if not servers:
            raise ValueError("Servers should not be empty.")

        if self == cls.any_server:
            return
        elif self == cls.in_this_cluster:
            return cls.check_in_this_cluster(cluster_model, servers)
        elif self == cls.not_in_this_cluster:
            return cls.check_not_in_this_cluster(cluster_model, servers)
        elif self == cls.in_other_cluster:
            return cls.check_in_other_cluster(cluster_model, servers)
        elif self == cls.not_in_other_cluster:
            return cls.check_not_in_other_cluster(cluster_model, servers)
        elif self == cls.in_any_cluster:
            return cls.check_in_any_cluster(cluster_model, servers)

        return cls.check_not_in_any_cluster(cluster_model, servers)

    @classmethod
    def check_in_this_cluster(cls, cluster_model, servers):
        negative_cond = [
            srv for srv in servers
            if srv.cluster_id != cluster_model.model_id
        ]
        if not negative_cond:
            return

        message = "Servers {0} do not belong to cluster {1}".format(
            cls.server_list_as_string(negative_cond),
            cluster_model.model_id
        )
        LOG.warning(message)
        raise ValueError(message)

    @classmethod
    def check_not_in_this_cluster(cls, cluster_model, servers):
        negative_cond = [
            srv for srv in servers
            if srv.cluster_id == cluster_model.model_id
        ]
        if not negative_cond:
            return

        message = "Servers {0} belong to cluster {1}".format(
            cls.server_list_as_string(negative_cond),
            cluster_model.model_id
        )
        LOG.warning(message)
        raise ValueError(message)

    @classmethod
    def check_in_other_cluster(cls, cluster_model, servers):
        negative_cond = [
            srv for srv in servers
            if srv.cluster_id in (cluster_model.model_id, None)
        ]
        if not negative_cond:
            return

        message = "Servers {0} not in other cluster than {1}".format(
            cls.server_list_as_string(negative_cond),
            cluster_model.model_id
        )
        LOG.warning(message)
        raise ValueError(message)

    @classmethod
    def check_not_in_other_cluster(cls, cluster_model, servers):
        negative_cond = [
            srv for srv in servers
            if srv.cluster_id not in (cluster_model.model_id, None)
        ]
        if not negative_cond:
            return

        message = "Servers {0} in other cluster than {1}".format(
            cls.server_list_as_string(negative_cond),
            cluster_model.model_id
        )
        LOG.warning(message)
        raise ValueError(message)

    @classmethod
    def check_in_any_cluster(cls, cluster_model, servers):
        negative_cond = [srv for srv in servers if not srv.cluster_id]
        if not negative_cond:
            return

        message = "Servers {0} are not in any cluster".format(
            cls.server_list_as_string(negative_cond)
        )
        LOG.warning(message)
        raise ValueError(message)

    @classmethod
    def check_not_in_any_cluster(cls, cluster_model, servers):
        negative_cond = [srv for srv in servers if srv.cluster_id]
        if not negative_cond:
            return

        message = "Servers {0} are in clusters".format(
            cls.server_list_as_string(negative_cond)
        )
        LOG.warning(message)
        raise ValueError(message)


class Base(metaclass=abc.ABCMeta):

    NAME = None
    PLAYBOOK_FILENAME = None
    CONFIG_FILENAME = None
    DESCRIPTION = ""
    PUBLIC = True
    REQUIRED_SERVER_LIST = True
    SERVER_LIST_POLICY = ServerListPolicy.any_server

    @property
    def env_task_id(self):
        return os.getenv(process.ENV_TASK_ID)

    @property
    def env_entry_point(self):
        return os.getenv(process.ENV_ENTRY_POINT)

    @property
    def task(self):
        if not self.env_task_id:
            return None

        return self.get_task(self.env_task_id)

    def __init__(self, entry_point, module_name):
        self.name = self.NAME or entry_point
        self.playbook_filename = self.PLAYBOOK_FILENAME or "playbook.yaml"
        self.config_filename = self.CONFIG_FILENAME or "config.yaml"

        self.module_name = module_name
        self.entry_point = entry_point
        self.config = self.load_config(self.config_filename)
        self.proc = None

    def get_filename(self, filename):
        return pathutils.resource(self.module_name, filename)

    def load_config(self, cnf):
        return load_config(self.get_filename(cnf or self.config_filename))

    @functools.lru_cache()
    def get_task(self, task_id):
        return task.Task.find_by_id(task_id)

    def get_extra_vars(self, task):
        return {}

    def on_pre_execute(self, task):
        pass

    def on_post_execute(self, task, *exc_info):
        pass

    @abc.abstractmethod
    def compose_command(self, task):
        raise NotImplementedError()

    @abc.abstractmethod
    def get_dynamic_inventory(self):
        raise NotImplementedError()

    @contextlib.contextmanager
    def execute(self, task):
        try:
            LOG.info("Execute pre-run step for %s", self.entry_point)
            try:
                self.on_pre_execute(task)
            finally:
                self.compose_command(task)
                LOG.info("Finish execution of pre-run step for %s",
                         self.entry_point)

            LOG.info("Execute %s for %s",
                     self.proc.commandline, self.entry_point)
            LOG.debug("Commandline: \"%s\"", self.proc.printable_commandline)
            yield self.proc.run()
        finally:
            LOG.info("Execute post-run step for %s", self.entry_point)
            self.on_post_execute(task, *sys.exc_info())
            LOG.info("Finish execution of post-run step for %s",
                     self.entry_point)

        LOG.info("Finish execute %s for %s",
                 self.proc.commandline, self.entry_point)

    def prepare_plugin(self):
        pass


class Ansible(Base, metaclass=abc.ABCMeta):

    MODULE = None
    BECOME = True
    ONE_LINE = True
    HINTS = []

    @abc.abstractmethod
    def compose_command(self, task):
        self.proc = process.Ansible(self.entry_point, task, self.MODULE)

        if self.ONE_LINE:
            self.proc.options["--one-line"] = process.NO_VALUE
        if self.BECOME:
            self.proc.options["--become"] = process.NO_VALUE

        extra = self.get_extra_vars(task)
        if extra:
            self.proc.options["--extra-vars"] = process.jsonify(extra)


class Playbook(Base, metaclass=abc.ABCMeta):

    BECOME = False
    HINTS = None
    CLUSTER_MUST_BE_DEPLOYED = True

    @property
    def playbook_config(self):
        if not self.task:
            return None

        return self.get_playbook_configuration(self.task)

    @functools.lru_cache()
    def get_playbook_configuration(self, task):
        from decapod_common.models import playbook_configuration

        if not task:
            return None

        return playbook_configuration.PlaybookConfigurationModel.find_by_id(
            task.data["playbook_configuration_id"]
        )

    def compose_command(self, task):
        self.proc = process.AnsiblePlaybook(self.entry_point, task)
        self.proc.args.append(str(self.get_filename(self.playbook_filename)))
        self.proc.options["-vvv"] = process.NO_VALUE

        if self.BECOME:
            self.proc.options["--become"] = process.NO_VALUE

        extra = self.get_extra_vars(task)
        if extra:
            self.proc.options["--extra-vars"] = process.jsonify(extra)

    def get_dynamic_inventory(self):
        if self.playbook_config:
            return self.playbook_config.configuration["inventory"]

    def get_extra_vars(self, task):
        config = self.get_playbook_configuration(task)
        config = config.configuration["global_vars"]

        return config

    def build_playbook_configuration(self, cluster, servers, hints):
        if isinstance(self.HINTS, playbook_plugin_hints.Hints):
            hints = self.HINTS.consume(hints)
        else:
            hints = {}

        if self.CLUSTER_MUST_BE_DEPLOYED and not cluster.configuration.state:
            raise exceptions.ClusterMustBeDeployedError()

        extra, inventory = self.make_playbook_configuration(
            cluster, servers, hints)

        return {
            "global_vars": extra,
            "inventory": inventory
        }

    def on_post_execute(self, task, *exc_info):
        from decapod_common.models import execution

        try:
            if exc_info[0] is None:
                self.write_header()
            else:
                self.write_error(*exc_info)

            execution_model = execution.ExecutionModel.find_by_model_id(
                task.execution_id)
            self.proc.stdout_file.seek(0)
            with execution_model.new_logfile as logfp:
                shutil.copyfileobj(self.proc.stdout_file, logfp)
        except Exception as exc:
            LOG.exception("Cannot save execution log of %s: %s",
                          task.execution_id, exc)
        finally:
            self.proc.stdout_file.close()

        super().on_post_execute(task, *exc_info)

    def write_header(self):
        header = self.proc.printable_commandline
        header_length = min(len(header), 80)
        header_top = " Ansible commandline ".center(header_length, "=")
        header = "\n\n{0}\n{1}\n{2}\n".format(
            header_top, header, "=" * header_length)
        header = header.encode("utf-8")
        self.proc.fileio.write(header)

    def write_error(self, exc_type, exc_value, exc_tb):
        data = traceback.format_exception(exc_type, exc_value, exc_tb)
        data = "".join(data)
        data = "\nInternal error\n\n{0}\n".format(data)
        data = data.encode("utf-8")
        self.proc.fileio.write(data)

    @abc.abstractmethod
    def make_playbook_configuration(self, servers, hints):
        raise NotImplementedError()


class CephAnsiblePlaybook(Playbook, metaclass=abc.ABCMeta):

    def __init__(self, *args, **kwargs):
        super().__init__(*args, **kwargs)
        self.fetchdir = None

    def on_pre_execute(self, task):
        self.fetchdir = pathutils.tempdir()
        super().on_pre_execute(task)

    def on_post_execute(self, task, exc_value, exc_type, exc_tb):
        pathutils.remove(self.fetchdir)
        super().on_post_execute(task, exc_value, exc_type, exc_tb)

    def get_extra_vars(self, task):
        config = super().get_extra_vars(task)
        config["fetch_directory"] = str(self.fetchdir)

        return config

    def make_global_vars(self, cluster, servers, hints):
        result = {
            "ceph_{0}".format(self.config["install"]["source"]): True,
            "fsid": cluster.model_id,
            "cluster": cluster.name,
            "copy_admin_key": bool(self.config.get("copy_admin_key", False)),
            "public_network": str(networkutils.get_public_network(servers)),
            "os_tuning_params": [],
            "nfs_file_gw": False,
            "nfs_obj_gw": False
        }
        if self.config["install"]["source"] == "stable":
            result["ceph_stable_release"] = self.config["install"]["release"]
        if self.config["install"].get("repo"):
            result["ceph_stable_repo"] = self.config["install"]["repo"]
        if self.config["install"].get("distro_source"):
            result["ceph_stable_distro_source"] = \
                self.config["install"]["distro_source"]
            # This is required to prevent Ansible for installation
            # from default repo
            result["ceph_stable_release_uca"] = \
                result["ceph_stable_distro_source"]
        if self.config["install"].get("keyserver"):
            result["ceph_stable_repo_keyserver"] = \
                self.config["install"]["keyserver"]
        if self.config["install"].get("repo_key"):
            result["ceph_stable_repo_key"] = self.config["install"]["repo_key"]

        # FIXME(Sergey Arkhipov): For some reason, Ceph cannot converge
        # if I set another network.
        result["cluster_network"] = result["public_network"]

        result["radosgw_civetweb_port"] = self.config["radosgw"]["port"]
        result["radosgw_civetweb_num_threads"] = \
            self.config["radosgw"]["num_threads"]
        result["radosgw_usage_log"] = self.config["radosgw"]["usage"]["log"]
        result["radosgw_usage_log_tick_interval"] = \
            self.config["radosgw"]["usage"]["log_tick_interval"]
        result["radosgw_usage_log_flush_threshold"] = \
            self.config["radosgw"]["usage"]["log_flush_threshold"]
        result["radosgw_usage_max_shards"] = \
            self.config["radosgw"]["usage"]["max_shards"]
        result["radosgw_usage_max_user_shards"] = \
            self.config["radosgw"]["usage"]["user_shards"]
        result["radosgw_static_website"] = \
            self.config["radosgw"]["static_website"]
        result["radosgw_dns_s3website_name"] = \
            self.config["radosgw"]["dns_s3website_name"]
        result["ceph_facts_template"] = pathutils.resource(
            "decapod_common", "facts", "ceph_facts_module.py.j2")
        result["ceph_facts_template"] = str(result["ceph_facts_template"])

        for family, values in self.config.get("os", {}).items():
            for param, value in values.items():
                parameter = {
                    "name": ".".join([family, param]),
                    "value": value
                }
                result["os_tuning_params"].append(parameter)

        if "max_open_files" in self.config:
            result["max_open_files"] = self.config["max_open_files"]

        return result

    def get_dynamic_inventory(self):
        if not self.playbook_config:
            raise exceptions.UnknownPlaybookConfiguration()

        return self.playbook_config.configuration["inventory"]


@functools.lru_cache()
def load_config(filename):
    return config.yaml_load(filename)
