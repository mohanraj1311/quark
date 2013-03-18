# Copyright (c) 2014 OpenStack Foundation
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

import contextlib
import mock
from oslo.config import cfg
from quantum import context
from quantum.common import exceptions
from quantum.db import api as quantum_db_api

from quark.db import models
import quark.ipam

import test_base


class QuarkIpamBaseTest(test_base.TestBase):
    def setUp(self):
        cfg.CONF.set_override('sql_connection', 'sqlite://', 'DATABASE')
        quantum_db_api.configure_db()
        models.BASEV2.metadata.create_all(quantum_db_api._ENGINE)
        self.ipam = quark.ipam.QuarkIpam()
        self.context = context.get_admin_context()

    def tearDown(self):
        quantum_db_api.clear_db()


class QuarkMacAddressAllocateDeallocated(QuarkIpamBaseTest):
    @contextlib.contextmanager
    def _stubs(self, mac_find=True):
        address = dict(id=1, address=0)
        mac_range = dict(id=1, first_address=0, last_address=255)
        db_mod = "quark.db.api"
        with contextlib.nested(
            mock.patch("%s.mac_address_find" % db_mod),
            mock.patch("%s.mac_address_range_find_allocation_counts" % db_mod),
            mock.patch("%s.mac_address_update" % db_mod),
            mock.patch("%s.mac_address_create" % db_mod)
        ) as (addr_find, mac_range_count, mac_update, mac_create):
            if mac_find:
                addr_find.return_value = address
            else:
                addr_find.side_effect = [None, None]
            mac_range_count.return_value = [(mac_range, 0)]
            mac_create.return_value = address
            yield mac_update, mac_create

    def test_allocate_mac_address_find_deallocated(self):
        with self._stubs(True) as (mac_update, mac_create):
            self.ipam.allocate_mac_address(self.context, 0, 0, 0)
            self.assertTrue(mac_update.called)
            self.assertFalse(mac_create.called)

    def test_allocate_mac_address_creates_new_mac(self):
        with self._stubs(False) as (mac_update, mac_create):
            self.ipam.allocate_mac_address(self.context, 0, 0, 0)
            self.assertFalse(mac_update.called)
            self.assertTrue(mac_create.called)


class QuarkNewMacAddressAllocation(QuarkIpamBaseTest):
    @contextlib.contextmanager
    def _stubs(self, addresses=None, ranges=None):
        if not addresses:
            addresses = [None]
        db_mod = "quark.db.api"
        with contextlib.nested(
            mock.patch("%s.mac_address_find" % db_mod),
            mock.patch("%s.mac_address_range_find_allocation_counts" % db_mod),
        ) as (mac_find, mac_range_count):
            mac_find.side_effect = addresses
            mac_range_count.return_value = ranges
            yield

    def test_allocate_new_mac_address_in_empty_range(self):
        mar = dict(id=1, first_address=0, last_address=255)
        with self._stubs(ranges=[(mar, 0)], addresses=[None, None]):
            address = self.ipam.allocate_mac_address(self.context, 0, 0, 0)
            self.assertEqual(address["address"], 0)

    def test_allocate_new_mac_in_partially_allocated_range(self):
        mac = dict(id=1, address=0)
        mar = dict(id=1, first_address=0, last_address=255)
        with self._stubs(ranges=[(mar, 0)], addresses=[None, mac]):
            address = self.ipam.allocate_mac_address(self.context, 0, 0, 0)
            self.assertEqual(address["address"], 1)

    def test_allocate_mac_one_full_one_open_range(self):
        mar1 = dict(id=1, first_address=0, last_address=1)
        mar2 = dict(id=2, first_address=2, last_address=255)
        ranges = [(mar1, 1), (mar2, 0)]
        with self._stubs(ranges=ranges, addresses=[None, None]):
            address = self.ipam.allocate_mac_address(self.context, 0, 0, 0)
            self.assertEqual(address["mac_address_range_id"], 2)
            self.assertEqual(address["address"], 2)

    def test_allocate_mac_no_ranges_fails(self):
        with self._stubs(ranges=[]):
            with self.assertRaises(exceptions.MacAddressGenerationFailure):
                self.ipam.allocate_mac_address(self.context, 0, 0, 0)

    def test_allocate_mac_no_available_range_fails(self):
        mar = dict(id=1, first_address=0, last_address=0)
        ranges = [(mar, 0)]
        with self._stubs(ranges=ranges):
            with self.assertRaises(exceptions.MacAddressGenerationFailure):
                self.ipam.allocate_mac_address(self.context, 0, 0, 0)

    def test_allocate_mac_two_open_ranges_chooses_first(self):
        mar1 = dict(id=1, first_address=0, last_address=255)
        mar2 = dict(id=2, first_address=256, last_address=510)
        ranges = [(mar1, 0), (mar2, 0)]
        with self._stubs(ranges=ranges, addresses=[None, None]):
            address = self.ipam.allocate_mac_address(self.context, 0, 0, 0)
            self.assertEqual(address["mac_address_range_id"], 1)
            self.assertEqual(address["address"], 0)


class QuarkMacAddressDeallocation(QuarkIpamBaseTest):
    @contextlib.contextmanager
    def _stubs(self, mac):
        with contextlib.nested(
            mock.patch("quark.db.api.mac_address_find"),
            mock.patch("quark.db.api.mac_address_update")
        ) as (mac_find,
              mac_update):
            mac_update.return_value = mac
            mac_find.return_value = mac
            yield mac_update

    def test_deallocate_mac(self):
        mac = dict(id=1, address=1)
        with self._stubs(mac=mac) as mac_update:
            self.ipam.deallocate_mac_address(self.context, mac["address"])
            self.assertTrue(mac_update.called)

    def test_deallocate_mac_mac_not_found_fails(self):
        with self._stubs(mac=None) as mac_update:
            self.assertRaises(exceptions.NotFound,
                              self.ipam.deallocate_mac_address, self.context,
                              0)
            self.assertFalse(mac_update.called)


class QuarkIPAddressDeallocation(QuarkIpamBaseTest):
    def test_deallocate_ip_address(self):
        port = dict(ip_addresses=[])
        addr = dict(ports=[port])
        port["ip_addresses"].append(addr)
        self.ipam.deallocate_ip_address(self.context, port)
        self.assertEqual(len(addr["ports"]), 0)
        self.assertEqual(addr["deallocated"], True)

    def test_deallocate_ip_address_multiple_ports_no_deallocation(self):
        port = dict(ip_addresses=[])
        addr = dict(ports=[port, 2], deallocated=False)
        port["ip_addresses"].append(addr)

        self.ipam.deallocate_ip_address(self.context, port)
        self.assertEqual(len(addr["ports"]), 1)
        self.assertEqual(addr["deallocated"], False)


class QuarkNewIPAddressAllocation(QuarkIpamBaseTest):
    @contextlib.contextmanager
    def _stubs(self, addresses=None, subnets=None):
        if not addresses:
            addresses = [None]
        db_mod = "quark.db.api"
        with contextlib.nested(
            mock.patch("%s.ip_address_find" % db_mod),
            mock.patch("%s.subnet_find_allocation_counts" % db_mod)
        ) as (addr_find, subnet_find):
            addr_find.side_effect = addresses
            subnet_find.return_value = subnets
            yield

    def test_allocate_new_ip_address_in_empty_range(self):
        subnet = dict(id=1, first_ip=0, last_ip=255,
                      cidr="0.0.0.0/24", ip_version=4)
        with self._stubs(subnets=[(subnet, 0)], addresses=[None, None]):
            address = self.ipam.allocate_ip_address(self.context, 0, 0, 0)
            self.assertEqual(address["address"], 0)

    def test_allocate_new_ip_in_partially_allocated_range(self):
        addr = dict(id=1, address=0)
        subnet = dict(id=1, first_ip=0, last_ip=255,
                      cidr="0.0.0.0/24", ip_version=4)
        with self._stubs(subnets=[(subnet, 0)], addresses=[None, addr]):
            address = self.ipam.allocate_ip_address(self.context, 0, 0, 0)
            self.assertEqual(address["address"], 1)

    def test_allocate_ip_one_full_one_open_subnet(self):
        subnet1 = dict(id=1, first_ip=0, last_ip=0,
                       cidr="0.0.0.0/32", ip_version=4)
        subnet2 = dict(id=2, first_ip=2, last_ip=255,
                       cidr="0.0.0.0/24", ip_version=4)
        subnets = [(subnet1, 1), (subnet2, 0)]
        with self._stubs(subnets=subnets, addresses=[None, None]):
            address = self.ipam.allocate_ip_address(self.context, 0, 0, 0)
            self.assertEqual(address["address"], 2)
            self.assertEqual(address["subnet_id"], 2)

    def test_allocate_ip_no_subnet_fails(self):
        with self._stubs(subnets=[]):
            with self.assertRaises(exceptions.IpAddressGenerationFailure):
                self.ipam.allocate_ip_address(self.context, 0, 0, 0)

    def test_allocate_ip_no_available_subnet_fails(self):
        subnet1 = dict(id=1, first_ip=0, last_ip=0,
                       cidr="0.0.0.0/32", ip_version=4)
        with self._stubs(subnets=[(subnet1, 1)]):
            with self.assertRaises(exceptions.IpAddressGenerationFailure):
                self.ipam.allocate_ip_address(self.context, 0, 0, 0)

    def test_allocate_ip_two_open_subnets_choses_first(self):
        subnet1 = dict(id=1, first_ip=0, last_ip=255,
                       cidr="0.0.0.0/24", ip_version=4)
        subnet2 = dict(id=2, first_ip=256, last_ip=510,
                       cidr="0.0.1.0/24", ip_version=4)
        subnets = [(subnet1, 1), (subnet2, 1)]
        with self._stubs(subnets=subnets, addresses=[None, None]):
            address = self.ipam.allocate_ip_address(self.context, 0, 0, 0)
            self.assertEqual(address["address"], 0)
            self.assertEqual(address["subnet_id"], 1)

    def test_find_requested_ip_subnet(self):
        subnet1 = dict(id=1, first_ip=0, last_ip=255,
                       cidr="0.0.0.0/24", ip_version=4)
        subnets = [(subnet1, 1)]
        with self._stubs(subnets=subnets, addresses=[None, None]):
            address = self.ipam.allocate_ip_address(
                self.context, 0, 0, 0, ip_address="0.0.0.240")
            self.assertEqual(address["address"], 240)
            self.assertEqual(address["subnet_id"], 1)

    def test_no_valid_subnet_for_requested_ip_fails(self):
        subnet1 = dict(id=1, first_ip=0, last_ip=255,
                       cidr="0.0.1.0/24", ip_version=4)
        subnets = [(subnet1, 1)]
        with self._stubs(subnets=subnets, addresses=[None, None]):
            with self.assertRaises(exceptions.IpAddressGenerationFailure):
                self.ipam.allocate_ip_address(
                    self.context, 0, 0, 0, ip_address="0.0.0.240")


class QuarkIPAddressAllocateDeallocated(QuarkIpamBaseTest):
    @contextlib.contextmanager
    def _stubs(self, ip_find=True):
        subnet = dict(id=1, ip_version=4)
        address = dict(id=1, address=0)
        updated_address = address.copy()

        db_mod = "quark.db.api"
        with contextlib.nested(
            mock.patch("%s.ip_address_find" % db_mod),
            mock.patch("%s.ip_address_update" % db_mod),
            mock.patch("quark.ipam.QuarkIpam._choose_available_subnet")
        ) as (addr_find, addr_update, choose_subnet):
            if ip_find:
                addr_find.return_value = address
            else:
                updated_address["id"] = None
                addr_find.side_effect = [None, updated_address]
                addr_update.return_value = updated_address
            choose_subnet.return_value = subnet
            yield

    def test_allocate_finds_deallocated_ip_succeeds(self):
        with self._stubs():
            ipaddress = self.ipam.allocate_ip_address(self.context, 0, 0, 0)
            self.assertIsNotNone(ipaddress['id'])
            self.assertFalse(
                quark.ipam.QuarkIpam._choose_available_subnet.called)

    def test_allocate_finds_no_deallocated_creates_new_ip(self):
        '''Fails based on the choice of reuse_after argument. Allocates new ip
        address instead of previously deallocated mac address.'''
        with self._stubs(ip_find=False):
            ipaddress = self.ipam.allocate_ip_address(self.context, 0, 0, 0)
            self.assertIsNone(ipaddress['id'])
            self.assertTrue(
                quark.ipam.QuarkIpam._choose_available_subnet.called)
