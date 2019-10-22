# Copyright 2018 Canonical Ltd.
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

import mock
import unit_tests.utils as ut_utils
from zaza.openstack.utilities import generic as generic_utils
import zaza.openstack.utilities.exceptions as zaza_exceptions

FAKE_STATUS = {
    'can-upgrade-to': '',
    'charm': 'local:trusty/app-136',
    'subordinate-to': [],
    'units': {'app/0': {'leader': True,
                        'machine': '0',
                        'subordinates': {
                            'app-hacluster/0': {
                                   'charm': 'local:trusty/hacluster-0',
                                   'leader': True}}},
              'app/1': {'machine': '1',
                        'subordinates': {
                            'app-hacluster/1': {
                                   'charm': 'local:trusty/hacluster-0'}}},
              'app/2': {'machine': '2',
                        'subordinates': {
                            'app-hacluster/2': {
                                   'charm': 'local:trusty/hacluster-0'}}}}}


class TestGenericUtils(ut_utils.BaseTestCase):

    def setUp(self):
        super(TestGenericUtils, self).setUp()
        # Patch all subprocess calls
        self.patch(
            'zaza.openstack.utilities.generic.subprocess',
            new_callable=mock.MagicMock(),
            name='subprocess'
        )

        # Juju Status Object and data
        self.juju_status = mock.MagicMock()
        self.juju_status.applications.__getitem__.return_value = FAKE_STATUS
        self.patch_object(generic_utils, "model")
        self.model.get_status.return_value = self.juju_status

    def test_dict_to_yaml(self):
        _dict_data = {"key": "value"}
        _str_data = "key: value\n"
        self.assertEqual(generic_utils.dict_to_yaml(_dict_data),
                         _str_data)

    def test_get_network_config(self):
        self.patch_object(generic_utils.os.path, "exists")
        self.patch_object(generic_utils, "get_yaml_config")
        self.patch_object(generic_utils, "get_undercloud_env_vars")
        net_topology = "topo"
        _data = {net_topology: {"network": "DATA"}}
        self.get_yaml_config.return_value = _data

        # YAML file does not exist
        self.exists.return_value = False
        with self.assertRaises(Exception):
            generic_utils.get_network_config(net_topology)

        # No environmental variables
        self.exists.return_value = True
        self.assertEqual(
            generic_utils.get_network_config(net_topology,
                                             ignore_env_vars=True),
            _data[net_topology])
        self.get_yaml_config.assert_called_once_with("network.yaml")
        self.get_undercloud_env_vars.assert_not_called()

        # Update with environmental variables
        _more_data = {"network": "NEW",
                      "other": "DATA"}
        self.get_undercloud_env_vars.return_value = _more_data
        _data[net_topology].update(_more_data)
        self.assertEqual(
            generic_utils.get_network_config(net_topology),
            _data[net_topology])
        self.get_undercloud_env_vars.assert_called_once_with()

    def test_get_pkg_version(self):
        self.patch_object(generic_utils.model, "get_units")
        self.patch_object(generic_utils.juju_utils, "remote_run")
        _pkg = "os-thingy"
        _version = "2:27.0.0-0ubuntu1~cloud0"
        _dpkg_output = ("ii {} {} all OpenStack thingy\n"
                        .format(_pkg, _version))
        self.remote_run.return_value = _dpkg_output
        _unit1 = mock.MagicMock()
        _unit1.entity_id = "os-thingy/7"
        _unit2 = mock.MagicMock()
        _unit2.entity_id = "os-thingy/12"
        _units = [_unit1, _unit2]
        self.get_units.return_value = _units

        # Matching
        self.assertEqual(generic_utils.get_pkg_version(_pkg, _pkg),
                         _version)

        # Mismatched
        _different_dpkg_output = ("ii {} {} all OpenStack thingy\n"
                                  .format(_pkg, "DIFFERENT"))
        self.remote_run.side_effect = [_dpkg_output, _different_dpkg_output]
        with self.assertRaises(Exception):
            generic_utils.get_pkg_version(_pkg, _pkg)

    def test_get_undercloud_env_vars(self):
        self.patch_object(generic_utils.os.environ, "get")

        def _get_env(key):
            return _env.get(key)
        self.get.side_effect = _get_env

        # Prefered OSCI TEST_ env vars
        _env = {"NET_ID": "netid",
                "NAME_SERVER": "10.0.0.10",
                "GATEWAY": "10.0.0.1",
                "CIDR_EXT": "10.0.0.0/24",
                "FIP_RANGE": "10.0.200.0:10.0.200.254",
                "TEST_NET_ID": "test_netid",
                "TEST_NAME_SERVER": "10.9.0.10",
                "TEST_GATEWAY": "10.9.0.1",
                "TEST_CIDR_EXT": "10.9.0.0/24",
                "TEST_FIP_RANGE": "10.9.200.0:10.0.200.254"}
        _expected_result = {}
        _expected_result["net_id"] = _env["TEST_NET_ID"]
        _expected_result["external_dns"] = _env["TEST_NAME_SERVER"]
        _expected_result["default_gateway"] = _env["TEST_GATEWAY"]
        _expected_result["external_net_cidr"] = _env["TEST_CIDR_EXT"]
        _expected_result["start_floating_ip"] = _env[
            "TEST_FIP_RANGE"].split(":")[0]
        _expected_result["end_floating_ip"] = _env[
            "TEST_FIP_RANGE"].split(":")[1]
        self.assertEqual(generic_utils.get_undercloud_env_vars(),
                         _expected_result)

        # Overriding local configure.network named variables
        _override = {"start_floating_ip": "10.100.50.0",
                     "end_floating_ip": "10.100.50.254",
                     "default_gateway": "10.100.0.1",
                     "external_net_cidr": "10.100.0.0/16"}
        _env.update(_override)
        _expected_result.update(_override)
        self.assertEqual(generic_utils.get_undercloud_env_vars(),
                         _expected_result)

    def test_get_yaml_config(self):
        self.patch("builtins.open",
                   new_callable=mock.mock_open(),
                   name="_open")
        _yaml = "data: somedata"
        _yaml_dict = {"data": "somedata"}
        _filename = "filename"
        _fileobj = mock.MagicMock()
        _fileobj.read.return_value = _yaml
        self._open.return_value = _fileobj

        self.assertEqual(generic_utils.get_yaml_config(_filename),
                         _yaml_dict)
        self._open.assert_called_once_with(_filename, "r")

    def test_dist_upgrade(self):
        _unit = "app/2"
        generic_utils.dist_upgrade(_unit)
        dist_upgrade_cmd = (
            """sudo DEBIAN_FRONTEND=noninteractive apt --assume-yes """
            """-o "Dpkg::Options::=--force-confdef" """
            """-o "Dpkg::Options::=--force-confold" dist-upgrade""")
        self.model.run_on_unit.assert_has_calls([
            mock.call(_unit, 'sudo apt update'),
            mock.call(_unit, dist_upgrade_cmd)])

    def test_do_release_upgrade(self):
        _unit = "app/2"
        generic_utils.do_release_upgrade(_unit)
        self.subprocess.check_call.assert_called_once_with(
            ['juju', 'ssh', _unit, 'sudo', 'DEBIAN_FRONTEND=noninteractive',
             'do-release-upgrade', '-f', 'DistUpgradeViewNonInteractive'])

    def test_wrap_do_release_upgrade(self):
        self.patch_object(generic_utils, "do_release_upgrade")
        self.patch_object(generic_utils, "run_via_ssh")
        self.patch_object(generic_utils.model, "scp_to_unit")
        _unit = "app/2"
        _from_series = "xenial"
        _to_series = "bionic"
        _workaround_script = "scriptname"
        _files = ["filename", _workaround_script]
        _scp_calls = []
        _run_calls = [
            mock.call(_unit, _workaround_script)]
        for filename in _files:
            _scp_calls.append(mock.call(_unit, filename, filename))
        generic_utils.wrap_do_release_upgrade(
            _unit, to_series=_to_series, from_series=_from_series,
            workaround_script=_workaround_script, files=_files)
        self.scp_to_unit.assert_has_calls(_scp_calls)
        self.run_via_ssh.assert_has_calls(_run_calls)
        self.do_release_upgrade.assert_called_once_with(_unit)

    def test_reboot(self):
        _unit = "app/2"
        generic_utils.reboot(_unit)
        self.subprocess.check_call.assert_called_once_with(
            ['juju', 'ssh', _unit,
             'sudo', 'reboot', '&&', 'exit'])

    def test_run_via_ssh(self):
        _unit = "app/2"
        _cmd = "hostname"
        generic_utils.run_via_ssh(_unit, _cmd)
        self.subprocess.check_call.assert_called_once_with(
            ['juju', 'ssh', _unit,
             'sudo ' + _cmd])

    def test_set_origin(self):
        "application, origin='openstack-origin', pocket='distro'):"
        self.patch_object(generic_utils.model, "set_application_config")
        _application = "application"
        _origin = "source"
        _pocket = "cloud:fake-cloud"
        generic_utils.set_origin(_application, origin=_origin, pocket=_pocket)
        self.set_application_config.assert_called_once_with(
            _application, {_origin: _pocket})

    def test_series_upgrade(self):
        self.patch_object(generic_utils.model, "block_until_all_units_idle")
        self.patch_object(generic_utils.model, "block_until_unit_wl_status")
        self.patch_object(generic_utils.model, "prepare_series_upgrade")
        self.patch_object(generic_utils.model, "complete_series_upgrade")
        self.patch_object(generic_utils.model, "set_series")
        self.patch_object(generic_utils, "set_origin")
        self.patch_object(generic_utils, "wrap_do_release_upgrade")
        self.patch_object(generic_utils, "reboot")
        _unit = "app/2"
        _application = "app"
        _machine_num = "4"
        _from_series = "xenial"
        _to_series = "bionic"
        _origin = "source"
        _files = ["filename", "scriptname"]
        _workaround_script = "scriptname"
        generic_utils.series_upgrade(
            _unit, _machine_num, origin=_origin,
            to_series=_to_series, from_series=_from_series,
            workaround_script=_workaround_script, files=_files)
        self.block_until_all_units_idle.called_with()
        self.prepare_series_upgrade.assert_called_once_with(
            _machine_num, to_series=_to_series)
        self.wrap_do_release_upgrade.assert_called_once_with(
            _unit, to_series=_to_series, from_series=_from_series,
            workaround_script=_workaround_script, files=_files)
        self.complete_series_upgrade.assert_called_once_with(_machine_num)
        self.set_series.assert_called_once_with(_application, _to_series)
        self.set_origin.assert_called_once_with(_application, _origin)
        self.reboot.assert_called_once_with(_unit)

    def test_series_upgrade_application_pause_peers_and_subordinates(self):
        self.patch_object(generic_utils.model, "run_action")
        self.patch_object(generic_utils, "series_upgrade")
        _application = "app"
        _from_series = "xenial"
        _to_series = "bionic"
        _origin = "source"
        _files = ["filename", "scriptname"]
        _workaround_script = "scriptname"
        _completed_machines = []
        # Peers and Subordinates
        _run_action_calls = [
            mock.call("{}-hacluster/1".format(_application),
                      "pause", action_params={}),
            mock.call("{}/1".format(_application), "pause", action_params={}),
            mock.call("{}-hacluster/2".format(_application),
                      "pause", action_params={}),
            mock.call("{}/2".format(_application), "pause", action_params={}),
        ]
        _series_upgrade_calls = []
        for machine_num in ("0", "1", "2"):
            _series_upgrade_calls.append(
                mock.call("{}/{}".format(_application, machine_num),
                          machine_num, origin=_origin,
                          from_series=_from_series, to_series=_to_series,
                          workaround_script=_workaround_script, files=_files,
                          post_upgrade_functions=None),
            )

        # Pause primary peers and subordinates
        generic_utils.series_upgrade_application(
            _application, origin=_origin,
            to_series=_to_series, from_series=_from_series,
            pause_non_leader_primary=True,
            pause_non_leader_subordinate=True,
            completed_machines=_completed_machines,
            workaround_script=_workaround_script, files=_files),
        self.run_action.assert_has_calls(_run_action_calls)
        self.series_upgrade.assert_has_calls(_series_upgrade_calls)

    def test_series_upgrade_application_pause_subordinates(self):
        self.patch_object(generic_utils.model, "run_action")
        self.patch_object(generic_utils, "series_upgrade")
        _application = "app"
        _from_series = "xenial"
        _to_series = "bionic"
        _origin = "source"
        _files = ["filename", "scriptname"]
        _workaround_script = "scriptname"
        _completed_machines = []
        # Subordinates only
        _run_action_calls = [
            mock.call("{}-hacluster/1".format(_application),
                      "pause", action_params={}),
            mock.call("{}-hacluster/2".format(_application),
                      "pause", action_params={}),
        ]
        _series_upgrade_calls = []

        for machine_num in ("0", "1", "2"):
            _series_upgrade_calls.append(
                mock.call("{}/{}".format(_application, machine_num),
                          machine_num, origin=_origin,
                          from_series=_from_series, to_series=_to_series,
                          workaround_script=_workaround_script, files=_files,
                          post_upgrade_functions=None),
            )

        # Pause subordinates
        generic_utils.series_upgrade_application(
            _application, origin=_origin,
            to_series=_to_series, from_series=_from_series,
            pause_non_leader_primary=False,
            pause_non_leader_subordinate=True,
            completed_machines=_completed_machines,
            workaround_script=_workaround_script, files=_files),
        self.run_action.assert_has_calls(_run_action_calls)
        self.series_upgrade.assert_has_calls(_series_upgrade_calls)

    def test_series_upgrade_application_no_pause(self):
        self.patch_object(generic_utils.model, "run_action")
        self.patch_object(generic_utils, "series_upgrade")
        _application = "app"
        _from_series = "xenial"
        _to_series = "bionic"
        _origin = "source"
        _series_upgrade_calls = []
        _files = ["filename", "scriptname"]
        _workaround_script = "scriptname"
        _completed_machines = []

        for machine_num in ("0", "1", "2"):
            _series_upgrade_calls.append(
                mock.call("{}/{}".format(_application, machine_num),
                          machine_num, origin=_origin,
                          from_series=_from_series, to_series=_to_series,
                          workaround_script=_workaround_script, files=_files,
                          post_upgrade_functions=None),
            )

        # No Pausiing
        generic_utils.series_upgrade_application(
            _application, origin=_origin,
            to_series=_to_series, from_series=_from_series,
            pause_non_leader_primary=False,
            pause_non_leader_subordinate=False,
            completed_machines=_completed_machines,
            workaround_script=_workaround_script, files=_files)
        self.run_action.assert_not_called()
        self.series_upgrade.assert_has_calls(_series_upgrade_calls)

    def test_set_dpkg_non_interactive_on_unit(self):
        self.patch_object(generic_utils, "model")
        _unit_name = "app/1"
        generic_utils.set_dpkg_non_interactive_on_unit(_unit_name)
        self.model.run_on_unit.assert_called_with(
            "app/1",
            'grep \'DPkg::options { "--force-confdef"; };\' '
            '/etc/apt/apt.conf.d/50unattended-upgrades || '
            'echo \'DPkg::options { "--force-confdef"; };\' >> '
            '/etc/apt/apt.conf.d/50unattended-upgrades')

    def test_get_process_id_list(self):
        self.patch(
            "zaza.openstack.utilities.generic.model.run_on_unit",
            new_callable=mock.MagicMock(),
            name="_run"
        )

        # Return code is OK and STDOUT contains output
        returns_ok = {
            "Code": 0,
            "Stdout": "1 2",
            "Stderr": ""
        }
        self._run.return_value = returns_ok
        p_id_list = generic_utils.get_process_id_list(
            "ceph-osd/0",
            "ceph-osd",
            False
        )
        expected = ["1", "2"]
        cmd = 'pidof -x "ceph-osd" || exit 0 && exit 1'
        self.assertEqual(p_id_list, expected)
        self._run.assert_called_once_with(unit_name="ceph-osd/0",
                                          command=cmd)

        # Return code is not OK
        returns_nok = {
            "Code": 1,
            "Stdout": "",
            "Stderr": "Something went wrong"
        }
        self._run.return_value = returns_nok
        with self.assertRaises(zaza_exceptions.ProcessIdsFailed):
            generic_utils.get_process_id_list("ceph-osd/0", "ceph")
            cmd = 'pidof -x "ceph"'
            self._run.assert_called_once_with(unit_name="ceph-osd/0",
                                              command=cmd)

    def test_get_unit_process_ids(self):
        self.patch(
            "zaza.openstack.utilities.generic.get_process_id_list",
            new_callable=mock.MagicMock(),
            name="_get_pids"
        )

        pids = ["1", "2"]
        self._get_pids.return_value = pids
        unit_processes = {
            "ceph-osd/0": {
                "ceph-osd": 2
            },
            "unit/0": {
                "pr1": 2,
                "pr2": 2
            }
        }
        expected = {
            "ceph-osd/0": {
                "ceph-osd": ["1", "2"]
            },
            "unit/0": {
                "pr1": ["1", "2"],
                "pr2": ["1", "2"]
            }
        }
        result = generic_utils.get_unit_process_ids(unit_processes)
        self.assertEqual(result, expected)

    def test_validate_unit_process_ids(self):
        expected = {
            "ceph-osd/0": {
                "ceph-osd": 2
            },
            "unit/0": {
                "pr1": 2,
                "pr2": [1, 2]
            }
        }

        # Unit count mismatch
        actual = {}
        with self.assertRaises(zaza_exceptions.UnitCountMismatch):
            generic_utils.validate_unit_process_ids(expected, actual)

        # Unit not found in actual dict
        actual = {
            "ceph-osd/0": {
                "ceph-osd": ["1", "2"]
            },
            # unit/0 not in the dict
            "unit/1": {
                "pr1": ["1", "2"],
                "pr2": ["1", "2"]
            }
        }
        with self.assertRaises(zaza_exceptions.UnitNotFound):
            generic_utils.validate_unit_process_ids(expected, actual)

        # Process names count doesn't match
        actual = {
            "ceph-osd/0": {
                "ceph-osd": ["1", "2"]
            },
            "unit/0": {
                # Only one process name instead of 2 expected
                "pr1": ["1", "2"]
            }
        }
        with self.assertRaises(zaza_exceptions.ProcessNameCountMismatch):
            generic_utils.validate_unit_process_ids(expected, actual)

        # Process name doesn't match
        actual = {
            "ceph-osd/0": {
                "ceph-osd": ["1", "2"]
            },
            "unit/0": {
                # Bad process name
                "bad_name": ["1", "2"],
                "pr2": ["1", "2"]
            }
        }
        with self.assertRaises(zaza_exceptions.ProcessNameMismatch):
            generic_utils.validate_unit_process_ids(expected, actual)

        # PID count doesn't match
        actual = {
            "ceph-osd/0": {
                "ceph-osd": ["1", "2"]
            },
            "unit/0": {
                # Only one PID instead of 2 expected
                "pr1": ["2"],
                "pr2": ["1", "2"]
            }
        }
        with self.assertRaises(zaza_exceptions.PIDCountMismatch):
            generic_utils.validate_unit_process_ids(expected, actual)

        actual = {
            "ceph-osd/0": {
                "ceph-osd": ["1", "2"]
            },
            "unit/0": {
                "pr1": ["1", "2"],
                # 3 PID instead of [1, 2] expected
                "pr2": ["1", "2", "3"]
            }
        }
        with self.assertRaises(zaza_exceptions.PIDCountMismatch):
            generic_utils.validate_unit_process_ids(expected, actual)

        # It should work now...
        actual = {
            "ceph-osd/0": {
                "ceph-osd": ["1", "2"]
            },
            "unit/0": {
                "pr1": ["1", "2"],
                "pr2": ["1", "2"]
            }
        }
        ret = generic_utils.validate_unit_process_ids(expected, actual)
        self.assertTrue(ret)

    def test_get_ubuntu_release(self):
        # Normal case
        expected = 0
        actual = generic_utils.get_ubuntu_release('oneiric')
        self.assertEqual(expected, actual)

        # Ubuntu release doesn't exist
        bad_name = 'bad_name'
        with self.assertRaises(zaza_exceptions.UbuntuReleaseNotFound):
            generic_utils.get_ubuntu_release(bad_name)

    def test_is_port_open(self):
        self.patch(
            'zaza.openstack.utilities.generic.telnetlib.Telnet',
            new_callable=mock.MagicMock(),
            name='telnet'
        )

        _port = "80"
        _addr = "10.5.254.20"

        self.assertTrue(generic_utils.is_port_open(_port, _addr))
        self.telnet.assert_called_with(_addr, _port)

        self.telnet.side_effect = generic_utils.socket.error
        self.assertFalse(generic_utils.is_port_open(_port, _addr))

    def test_get_unit_hostnames(self):
        self.patch(
            "zaza.openstack.utilities.generic.model.run_on_unit",
            new_callable=mock.MagicMock(),
            name="_run"
        )

        _unit1 = mock.MagicMock()
        _unit1.entity_id = "testunit/1"
        _unit2 = mock.MagicMock()
        _unit2.entity_id = "testunit/2"

        _hostname1 = "host1.domain"
        _hostname2 = "host2.domain"

        expected = {
            _unit1.entity_id: _hostname1,
            _unit2.entity_id: _hostname2,
        }

        _units = [_unit1, _unit2]

        self._run.side_effect = [{"Stdout": _hostname1},
                                 {"Stdout": _hostname2}]

        actual = generic_utils.get_unit_hostnames(_units)

        self.assertEqual(actual, expected)

    def test_port_knock_units(self):
        self.patch(
            "zaza.openstack.utilities.generic.is_port_open",
            new_callable=mock.MagicMock(),
            name="_is_port_open"
        )

        _units = [
            mock.MagicMock(),
            mock.MagicMock(),
        ]

        self._is_port_open.side_effect = [True, True]
        self.assertIsNone(generic_utils.port_knock_units(_units))
        self.assertEqual(self._is_port_open.call_count, len(_units))

        self._is_port_open.side_effect = [True, False]
        self.assertIsNotNone(generic_utils.port_knock_units(_units))

        # check when func is expecting failure, i.e. should succeed
        self._is_port_open.reset_mock()
        self._is_port_open.side_effect = [False, False]
        self.assertIsNone(generic_utils.port_knock_units(_units,
                                                         expect_success=False))
        self.assertEqual(self._is_port_open.call_count, len(_units))

    def test_check_commands_on_units(self):
        self.patch(
            "zaza.openstack.utilities.generic.model.run_on_unit",
            new_callable=mock.MagicMock(),
            name="_run"
        )

        num_units = 2
        _units = [mock.MagicMock() for i in range(num_units)]

        num_cmds = 3
        cmds = ["/usr/bin/fakecmd"] * num_cmds

        # Test success, all calls return 0
        # zero is a string to replicate run_on_unit return data type
        _cmd_results = [{"Code": "0"}] * len(_units) * len(cmds)
        self._run.side_effect = _cmd_results

        result = generic_utils.check_commands_on_units(cmds, _units)
        self.assertIsNone(result)
        self.assertEqual(self._run.call_count, len(_units) * len(cmds))

        # Test failure, some call returns 1
        _cmd_results[2] = {"Code": "1"}
        self._run.side_effect = _cmd_results

        result = generic_utils.check_commands_on_units(cmds, _units)
        self.assertIsNotNone(result)
