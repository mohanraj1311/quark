# Copyright 2013 Openstack Foundation
# All Rights Reserved.
#
#    Licensed under the Apache License, Version 2.0 (the "License"); you may
#    not use this file except in compliance with the License. You may obtain
#    a copy of the License at
#
#         http://www.apache.org/licenses/LICENSE-2.0
#
#    Unless required by applicable law or agreed to in writing, software
#    distributed under the License is distributed on an "AS IS" BASIS, WITHOUT
#    WARRANTIES OR CONDITIONS OF ANY KIND, either express or implied. See the
#    License for the specific language governing permissions and limitations
#    under the License.

import netaddr
from neutron.common import exceptions
from neutron.openstack.common import importutils
from neutron.openstack.common import log as logging
from oslo.config import cfg

from quark.db import api as db_api
from quark import exceptions as quark_exceptions
from quark import plugin_views as v

CONF = cfg.CONF
DEFAULT_ROUTE = netaddr.IPNetwork("0.0.0.0/0")
LOG = logging.getLogger(__name__)

ipam_driver = (importutils.import_class(CONF.QUARK.ipam_driver))()


def get_route(context, id):
    LOG.info("get_route %s for tenant %s" % (id, context.tenant_id))
    route = db_api.route_find(context, id=id, scope=db_api.ONE)
    if not route:
        raise quark_exceptions.RouteNotFound(route_id=id)
    return v._make_route_dict(route)


def get_routes(context):
    LOG.info("get_routes for tenant %s" % context.tenant_id)
    routes = db_api.route_find(context)
    return [v._make_route_dict(r) for r in routes]


def create_route(context, route):
    LOG.info("create_route for tenant %s" % context.tenant_id)
    route = route["route"]
    subnet_id = route["subnet_id"]
    with context.session.begin():
        subnet = db_api.subnet_find(context, id=subnet_id, scope=db_api.ONE)
        if not subnet:
            raise exceptions.SubnetNotFound(subnet_id=subnet_id)

        # TODO(anyone): May want to denormalize the cidr values into columns
        #               to achieve single db lookup on conflict check
        route_cidr = netaddr.IPNetwork(route["cidr"])
        subnet_routes = db_api.route_find(context, subnet_id=subnet_id,
                                          scope=db_api.ALL)
        for sub_route in subnet_routes:
            sub_route_cidr = netaddr.IPNetwork(sub_route["cidr"])
            if sub_route_cidr.value == DEFAULT_ROUTE.value:
                continue
            if route_cidr in sub_route_cidr or sub_route_cidr in route_cidr:
                raise quark_exceptions.RouteConflict(
                    route_id=sub_route["id"], cidr=str(route_cidr))
        new_route = db_api.route_create(context, **route)
    return v._make_route_dict(new_route)


def delete_route(context, id):
    # TODO(mdietz): This is probably where we check to see that someone is
    #              admin and only filter on tenant if they aren't. Correct
    #              for all the above later
    LOG.info("delete_route %s for tenant %s" % (id, context.tenant_id))
    with context.session.begin():
        route = db_api.route_find(context, id=id, scope=db_api.ONE)
        if not route:
            raise quark_exceptions.RouteNotFound(route_id=id)
        db_api.route_delete(context, route)
