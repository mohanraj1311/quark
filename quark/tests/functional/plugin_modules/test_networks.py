# Copyright 2013 Openstack Foundation
# All Rights Reserved.
#
# Licensed under the Apache License, Version 2.0 (the "License"); you may
# not use this file except in compliance with the License. You may obtain
# a copy of the License at
#
#     http://www.apache.org/licenses/LICENSE-2.0
#
# Unless required by applicable law or agreed to in writing, software
# distributed under the License is distributed on an "AS IS" BASIS, WITHOUT
# WARRANTIES OR CONDITIONS OF ANY KIND, either express or implied. See the
# License for# the specific language governing permissions and limitations
#  under the License.

import contextlib

import netaddr
from neutron.common import exceptions
from neutron import context
from neutron.db import api as neutron_db_api
from oslo.config import cfg
import unittest2

from quark.db import api as db_api
from quark.db import models
import quark.ipam
import quark.plugin


class QuarkNetworkFunctionalTest(unittest2.TestCase):
    def setUp(self):
        self.context = context.Context('fake', 'fake', is_admin=False)
        super(QuarkNetworkFunctionalTest, self).setUp()

        cfg.CONF.set_override('connection', 'sqlite://', 'database')
        neutron_db_api.configure_db()
        neutron_db_api.register_models(models.BASEV2)

    def tearDown(self):
        neutron_db_api.unregister_models(models.BASEV2)
        neutron_db_api.clear_db()


class QuarkDeleteNetworKDeallocatedIPs(QuarkNetworkFunctionalTest):
    @contextlib.contextmanager
    def _stubs(self, network, subnet, dealloc=True):
        self.plugin = quark.plugin.Plugin()
        self.ipam = quark.ipam.QuarkIpamANY()
        with self.context.session.begin():
            net_mod = db_api.network_create(self.context, **network)
            subnet["network"] = net_mod
            next_auto = subnet.pop("next_auto_assign_ip", 0)
            sub_mod = db_api.subnet_create(self.context, **subnet)
            db_api.subnet_update(self.context,
                                 sub_mod,
                                 next_auto_assign_ip=next_auto)

        ip_addr = []
        self.ipam.allocate_ip_address(self.context, ip_addr,
                                      net_mod["id"], 0, 0)
        if dealloc:
            self.ipam.deallocate_ip_address(self.context, ip_addr[0])
        yield net_mod

    def test_delete_network_with_allocated_ips_fails(self):
        ipnet = netaddr.IPNetwork("0.0.0.0/24")
        next_ip = ipnet.ipv6().first + 2

        network = dict(name="public", tenant_id="fake", network_plugin="BASE")
        subnet = dict(id=1, ip_version=4, next_auto_assign_ip=next_ip,
                      cidr="0.0.0.0/24",
                      ip_policy=None, tenant_id="fake")
        with self._stubs(network, subnet, dealloc=False) as net_mod:
            with self.assertRaises(exceptions.SubnetInUse):
                self.plugin.delete_network(self.context, net_mod["id"])

    def test_delete_network_with_deallocated_ips(self):
        network = dict(name="public", tenant_id="fake", network_plugin="BASE")
        ipnet = netaddr.IPNetwork("0.0.0.0/24")
        next_ip = ipnet.ipv6().first + 2
        subnet = dict(id=1, ip_version=4, next_auto_assign_ip=next_ip,
                      cidr="0.0.0.0/24",
                      ip_policy=None, tenant_id="fake")
        with self._stubs(network, subnet) as net_mod:
            try:
                self.plugin.delete_network(self.context, net_mod["id"])
            except Exception:
                self.fail("delete network raised")
