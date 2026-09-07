import json
import os
import tempfile
import unittest
from unittest.mock import patch

from utils.shelly_discovery import (
    ShellyResolver,
    normalize_mac,
    normalize_sensor_address,
)


def record(ip, mac, *, name=None, sensors=None):
    return {
        "ip": ip,
        "mac": normalize_mac(mac),
        "id": f"shelly-test-{normalize_mac(mac).replace(':', '')}",
        "name": name,
        "model": "test",
        "app": "test",
        "gen": 2,
        "sensor_addon_supported": sensors is not None,
        "sensor_addresses": sensors or [],
        "seen_at": "2026-09-07T00:00:00+00:00",
    }


class ShellyResolverTests(unittest.TestCase):
    def setUp(self):
        self.tempdir = tempfile.TemporaryDirectory()
        self.cache_path = os.path.join(self.tempdir.name, "shelly.json")
        self.resolver = ShellyResolver(
            networks=["10.10.120.0/30"],
            cache_path=self.cache_path,
            probe_timeout=0.01,
            rpc_timeout=0.01,
            scan_workers=2,
        )

    def tearDown(self):
        self.tempdir.cleanup()

    def test_identity_normalization(self):
        self.assertEqual(normalize_mac("841FE8F9B408"), "84:1f:e8:f9:b4:08")
        self.assertEqual(
            normalize_sensor_address("40:010:74:120:0:0:0:49"),
            "40:10:74:120:0:0:0:49",
        )

    def test_resolves_explicit_mac_from_scan_and_persists_alias(self):
        found = record("10.10.120.2", "84:1f:e8:f9:b4:08", name="almero1")
        with patch.object(self.resolver, "_scan_networks", return_value=[found]), patch.object(
            self.resolver, "_probe_ip", return_value=None
        ):
            resolved, errors = self.resolver.resolve_many(
                {"almero1": {"mac": "841FE8F9B408"}}
            )

        self.assertFalse(errors)
        self.assertEqual(resolved["almero1"]["ip"], "10.10.120.2")
        with open(self.cache_path, encoding="utf-8") as handle:
            cache = json.load(handle)
        self.assertEqual(cache["aliases"]["almero1"], "84:1f:e8:f9:b4:08")

    def test_matches_radiator_by_sensor_address(self):
        found = record(
            "10.10.120.1",
            "a0:85:e3:c8:0f:e0",
            sensors=["40:10:74:120:0:0:0:49"],
        )
        with patch.object(self.resolver, "_scan_networks", return_value=[found]), patch.object(
            self.resolver, "_probe_ip", return_value=None
        ):
            resolved, errors = self.resolver.resolve_many(
                {
                    "szgk_radiator_shelly": {
                        "sensor_addresses": ["40:10:74:120:0:0:0:49"]
                    }
                }
            )

        self.assertFalse(errors)
        self.assertEqual(
            resolved["szgk_radiator_shelly"]["mac"],
            "a0:85:e3:c8:0f:e0",
        )

    def test_rejects_reassigned_cached_ip_and_rescans(self):
        old = record("10.10.120.1", "84:1f:e8:f9:b4:08")
        self.resolver._persist_cache(records=[old], aliases={"almero1": old["mac"]})
        new = record("10.10.120.2", "84:1f:e8:f9:b4:08")
        wrong = record("10.10.120.1", "80:f3:da:e4:23:80")

        with patch.object(self.resolver, "_probe_ip", return_value=wrong), patch.object(
            self.resolver, "_scan_networks", return_value=[new]
        ):
            resolved, errors = self.resolver.resolve_many(
                {"almero1": {"mac": old["mac"]}}
            )

        self.assertFalse(errors)
        self.assertEqual(resolved["almero1"]["ip"], "10.10.120.2")

    def test_cached_validation_preserves_sensor_identity(self):
        cached = record(
            "10.10.120.1",
            "a0:85:e3:c8:0f:e0",
            sensors=["40:10:74:120:0:0:0:49"],
        )
        self.resolver._persist_cache(records=[cached])
        identity_only = record("10.10.120.1", "a0:85:e3:c8:0f:e0")

        with patch.object(self.resolver, "_probe_ip", return_value=identity_only), patch.object(
            self.resolver, "_scan_networks"
        ) as scan:
            resolved, errors = self.resolver.resolve_many(
                {
                    "szgk_radiator_shelly": {
                        "sensor_addresses": ["40:10:74:120:0:0:0:49"]
                    }
                }
            )

        self.assertFalse(errors)
        scan.assert_not_called()
        self.assertEqual(
            resolved["szgk_radiator_shelly"]["sensor_addresses"],
            ["40:10:74:120:0:0:0:49"],
        )

    def test_reports_unidentifiable_device(self):
        with patch.object(self.resolver, "_scan_networks", return_value=[]):
            resolved, errors = self.resolver.resolve_many(
                {"unknown": {"device_names": ["unknown"]}}
            )
        self.assertFalse(resolved)
        self.assertIn("unknown", errors)


if __name__ == "__main__":
    unittest.main()
