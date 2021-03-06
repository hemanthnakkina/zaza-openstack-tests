# Copyright 2020 Canonical Ltd.
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

"""Collection of functions to support upgrade testing."""

import itertools
import logging
import re

import zaza.model


SERVICE_GROUPS = (
    ('Database Services', ['percona-cluster', 'mysql-innodb-cluster']),
    ('Stateful Services', ['rabbitmq-server', 'ceph-mon']),
    ('Core Identity', ['keystone']),
    ('Control Plane', [
        'aodh', 'barbican', 'ceilometer', 'ceph-fs',
        'ceph-radosgw', 'cinder', 'designate',
        'designate-bind', 'glance', 'gnocchi', 'heat', 'manila',
        'manila-generic', 'neutron-api', 'neutron-gateway', 'placement',
        'nova-cloud-controller', 'openstack-dashboard']),
    ('Data Plane', [
        'nova-compute', 'ceph-osd',
        'swift-proxy', 'swift-storage']))

UPGRADE_EXCLUDE_LIST = ['rabbitmq-server', 'percona-cluster']


def get_upgrade_candidates(model_name=None, filters=None):
    """Extract list of apps from model that can be upgraded.

    :param model_name: Name of model to query.
    :type model_name: str
    :param filters: List of filter functions to apply
    :type filters: List[fn]
    :returns: List of application that can have their payload upgraded.
    :rtype: []
    """
    if filters is None:
        filters = []
    status = zaza.model.get_status(model_name=model_name)
    candidates = {}
    for app, app_config in status.applications.items():
        if _include_app(app, app_config, filters, model_name=model_name):
            candidates[app] = app_config
    return candidates


def _include_app(app, app_config, filters, model_name=None):
    for filt in filters:
        if filt(app, app_config, model_name=model_name):
            return False
    return True


def _filter_subordinates(app, app_config, model_name=None):
    if app_config.get("subordinate-to"):
        logging.warning(
            "Excluding {} from upgrade, it is a subordinate".format(app))
        return True
    return False


def _filter_openstack_upgrade_list(app, app_config, model_name=None):
    charm_name = extract_charm_name_from_url(app_config['charm'])
    if app in UPGRADE_EXCLUDE_LIST or charm_name in UPGRADE_EXCLUDE_LIST:
        print("Excluding {} from upgrade, on the exclude list".format(app))
        logging.warning(
            "Excluding {} from upgrade, on the exclude list".format(app))
        return True
    return False


def _filter_non_openstack_services(app, app_config, model_name=None):
    charm_options = zaza.model.get_application_config(
        app, model_name=model_name).keys()
    src_options = ['openstack-origin', 'source']
    if not [x for x in src_options if x in charm_options]:
        logging.warning(
            "Excluding {} from upgrade, no src option".format(app))
        return True
    return False


def _apply_extra_filters(filters, extra_filters):
    if extra_filters:
        if isinstance(extra_filters, list):
            filters.extend(extra_filters)
        elif callable(extra_filters):
            filters.append(extra_filters)
        else:
            raise RuntimeError(
                "extra_filters should be a list of "
                "callables")
    return filters


def _filter_easyrsa(app, app_config, model_name=None):
    charm_name = extract_charm_name_from_url(app_config['charm'])
    if "easyrsa" in charm_name:
        logging.warn("Skipping upgrade of easyrsa Bug #1850121")
        return True
    return False


def _filter_etcd(app, app_config, model_name=None):
    charm_name = extract_charm_name_from_url(app_config['charm'])
    if "etcd" in charm_name:
        logging.warn("Skipping upgrade of easyrsa Bug #1850124")
        return True
    return False


def _filter_memcached(app, app_config, model_name=None):
    charm_name = extract_charm_name_from_url(app_config['charm'])
    if "memcached" in charm_name:
        logging.warn("Skipping upgrade of memcached charm")
        return True
    return False


def get_upgrade_groups(model_name=None, extra_filters=None):
    """Place apps in the model into their upgrade groups.

    Place apps in the model into their upgrade groups. If an app is deployed
    but is not in SERVICE_GROUPS then it is placed in a sweep_up group.

    :param model_name: Name of model to query.
    :type model_name: str
    :returns: Dict of group lists keyed on group name.
    :rtype: collections.OrderedDict
    """
    filters = [
        _filter_subordinates,
        _filter_openstack_upgrade_list,
        _filter_non_openstack_services,
    ]
    filters = _apply_extra_filters(filters, extra_filters)
    apps_in_model = get_upgrade_candidates(
        model_name=model_name,
        filters=filters)

    return _build_service_groups(apps_in_model)


def get_series_upgrade_groups(model_name=None, extra_filters=None):
    """Place apps in the model into their upgrade groups.

    Place apps in the model into their upgrade groups. If an app is deployed
    but is not in SERVICE_GROUPS then it is placed in a sweep_up group.

    :param model_name: Name of model to query.
    :type model_name: str
    :returns: Dict of group lists keyed on group name.
    :rtype: collections.OrderedDict
    """
    filters = [_filter_subordinates]
    filters = _apply_extra_filters(filters, extra_filters)
    apps_in_model = get_upgrade_candidates(
        model_name=model_name,
        filters=filters)

    return _build_service_groups(apps_in_model)


def get_charm_upgrade_groups(model_name=None, extra_filters=None):
    """Place apps in the model into their upgrade groups for a charm upgrade.

    Place apps in the model into their upgrade groups. If an app is deployed
    but is not in SERVICE_GROUPS then it is placed in a sweep_up group.

    :param model_name: Name of model to query.
    :type model_name: str
    :returns: Dict of group lists keyed on group name.
    :rtype: collections.OrderedDict
    """
    filters = _apply_extra_filters([], extra_filters)
    apps_in_model = get_upgrade_candidates(
        model_name=model_name,
        filters=filters)

    return _build_service_groups(apps_in_model)


def _build_service_groups(applications):
    groups = []
    for phase_name, charms in SERVICE_GROUPS:
        group = []
        for app, app_config in applications.items():
            charm_name = extract_charm_name_from_url(app_config['charm'])
            if charm_name in charms:
                group.append(app)
        groups.append((phase_name, group))

    # collect all the values into a list, and then a lookup hash
    values = list(itertools.chain(*(ls for _, ls in groups)))
    vhash = {v: 1 for v in values}
    sweep_up = [app for app in applications if app not in vhash]
    groups.append(('sweep_up', sweep_up))
    for name, group in groups:
        group.sort()
    return groups


def extract_charm_name_from_url(charm_url):
    """Extract the charm name from the charm url.

    E.g. Extract 'heat' from local:bionic/heat-12

    :param charm_url: Name of model to query.
    :type charm_url: str
    :returns: Charm name
    :rtype: str
    """
    charm_name = re.sub(r'-[0-9]+$', '', charm_url.split('/')[-1])
    return charm_name.split(':')[-1]
