"""Sensor semantics, provenance, health, historical compatibility, and wrappers."""
import ast
import copy
import unittest
from datetime import datetime, timedelta, timezone
from pathlib import Path
from types import SimpleNamespace
from unittest.mock import patch

from utils.occupancy import (
    normalize_presence, calculate_occupancy, sensor_kind, known_presence_fraction,
)

NOW = datetime(2026, 10, 19, 11, tzinfo=timezone.utc)
FP300 = "lumi.sensor_occupy.agl8"


def observation(at=NOW, *, model=FP300, name="Aqara2", value=True,
                updated=None, contact=None, reachable=True, identity="aa:bb", announced=None):
    return normalize_presence({
        "name": name, "uniqueid": identity+"-01-fcc0", "modelid": model,
        "manufacturername": "Aqara" if model == FP300 else "eWeLink",
        "lastseen": (contact or at).isoformat(),
        "lastannounced": (announced or at-timedelta(days=2)).isoformat(),
        "config": {"on": True, "reachable": reachable},
        "state": {"presence": value, "lastupdated": (updated or at).isoformat()},
    }, at)


def record(row, room="4"):
    return {"timestamp": row["observed_at"], "states": {room: row}}


def evaluate(rows, *, target=NOW, source="Aqara2", legacy=False, separation=15):
    return calculate_occupancy(rows, {"4": {"pres": source}}, [target],
                               presence_window=30, minimum_separation=separation,
                               allow_legacy=legacy)[0]["4"]


class OccupancyTests(unittest.TestCase):
    def test_all_deployed_models_classified_by_hardware_not_name(self):
        self.assertEqual(sensor_kind("Aqara", FP300), "presence")
        self.assertEqual(sensor_kind("eWeLink", "MS01"), "motion")
        self.assertEqual(sensor_kind("eWeLink", "SNZB-03P"), "motion")
        self.assertEqual(sensor_kind("Other", FP300), "unknown")

    def test_true_presence_can_remain_unchanged_for_hours(self):
        row = observation(updated=NOW-timedelta(hours=8))
        self.assertTrue(row["usable"])
        self.assertIs(evaluate([record(row)]), True)

    def test_false_presence_replaces_level_immediately(self):
        rows = [record(observation(NOW-timedelta(minutes=1))),
                record(observation(value=False))]
        self.assertIs(evaluate(rows), False)

    def test_old_false_presence_with_fresh_radio_is_valid_vacancy(self):
        row = observation(value=False, updated=NOW-timedelta(hours=8))
        self.assertIs(evaluate([record(row)]), False)

    def test_cached_true_reachable_flag_without_radio_is_unknown(self):
        row = observation(updated=NOW-timedelta(hours=17), contact=NOW-timedelta(hours=17))
        self.assertFalse(row["usable"])
        self.assertEqual(row["unavailable_reason"], "device_contact_stale")
        self.assertIsNone(evaluate([record(row)]))

    def test_stale_false_not_authoritative_vacancy(self):
        row = observation(value=False, updated=NOW-timedelta(hours=17), contact=NOW-timedelta(hours=17))
        self.assertIsNone(evaluate([record(row)]))

    def test_unreachable_without_recent_radio_is_unknown(self):
        row = observation(reachable=False, contact=NOW-timedelta(minutes=10))
        self.assertIsNone(evaluate([record(row)]))

    def test_actual_recent_radio_outweighs_stale_false_flag(self):
        row = observation(reachable=False)
        self.assertIs(evaluate([record(row)]), True)

    def test_logger_silence_becomes_unknown(self):
        row = observation(NOW-timedelta(minutes=6))
        self.assertIsNone(evaluate([record(row)]))

    def test_previous_connection_state_cannot_establish_new_presence(self):
        row = observation(updated=NOW-timedelta(days=1), announced=NOW-timedelta(minutes=1))
        self.assertEqual(row["unavailable_reason"], "awaiting_post_join_state")
        self.assertIsNone(evaluate([record(row)]))

    def test_unknown_model_never_silently_assumed_motion_or_presence(self):
        row = observation(model="future_sensor")
        self.assertIsNone(evaluate([record(row)]))

    def test_unknown_room_or_no_sensor_is_unknown(self):
        self.assertIsNone(evaluate([]))

    def test_missing_source_id_invalidates_evidence(self):
        row = observation(identity="")
        self.assertFalse(row["usable"])

    def test_disabled_sensor_is_not_occupied(self):
        row = observation()
        row["enabled"] = False
        self.assertIsNone(evaluate([record(row)]))

    def test_invalid_state_does_not_become_false_or_true(self):
        row = observation(value="true")
        self.assertIsNone(row["state"])
        self.assertIsNone(evaluate([record(row)]))

    def test_future_device_timestamps_rejected(self):
        row = observation(updated=NOW+timedelta(minutes=1))
        self.assertFalse(row["usable"])

    def test_normalization_preserves_real_motion_timestamp_for_pres1(self):
        actual = NOW-timedelta(minutes=20)
        row = observation(model="MS01", name="Pres1", updated=actual)
        self.assertEqual(row["source_updated_at"], actual.isoformat())
        self.assertEqual(row["last_updated"], "2026-10-19-10-40-00")
        self.assertEqual(row["observed_at"], NOW.isoformat())

    def test_source_utc_and_project_local_times_are_distinct(self):
        row = normalize_presence({"name": "Aqara2", "uniqueid": "aa-bb", "manufacturername": "Aqara",
                                  "modelid": FP300, "config": {"reachable": True},
                                  "lastseen": "2026-10-19T11:00Z",
                                  "state": {"presence": True, "lastupdated": "2026-10-19T10:00:00.123"}},
                                 NOW, local_tz=timezone(timedelta(hours=2)))
        self.assertEqual(row["last_updated"], "2026-10-19-12-00-00")
        self.assertTrue(row["usable"])

    def motion(self, at=NOW, **kwargs):
        return observation(at, model="MS01", name="Pres1", **kwargs)

    def test_motion_requires_separated_distinct_actual_reports(self):
        rows = [record(self.motion(NOW-timedelta(minutes=20))), record(self.motion())]
        self.assertIs(evaluate(rows, source="Pres1"), True)

    def test_snzb03p_uses_same_motion_policy(self):
        rows = [record(observation(NOW-timedelta(minutes=20), model="SNZB-03P", name="Pres2")),
                record(observation(model="SNZB-03P", name="Pres2"))]
        self.assertIs(evaluate(rows, source="Pres2"), True)

    def test_polling_same_true_motion_level_is_not_repeated_motion(self):
        actual = NOW-timedelta(minutes=21)
        rows = [record(self.motion(NOW-timedelta(minutes=20), updated=actual)),
                record(self.motion(updated=actual))]
        self.assertIs(evaluate(rows, source="Pres1"), False)

    def test_true_pir_state_older_than_window_is_unknown_not_new_motion(self):
        row = self.motion(updated=NOW-timedelta(hours=3))
        self.assertIsNone(evaluate([record(row)], source="Pres1"))

    def test_motion_false_does_not_cancel_recent_qualified_history(self):
        rows = [record(self.motion(NOW-timedelta(minutes=20))),
                record(self.motion(NOW-timedelta(minutes=2))), record(self.motion(value=False))]
        self.assertIs(evaluate(rows, source="Pres1"), True)

    def test_motion_without_enough_spacing_is_not_occupied(self):
        rows = [record(self.motion(NOW-timedelta(minutes=3))), record(self.motion())]
        self.assertIs(evaluate(rows, source="Pres1"), False)

    def test_motion_window_boundary_inclusive(self):
        rows = [record(self.motion(NOW-timedelta(minutes=30))), record(self.motion())]
        self.assertIs(evaluate(rows, source="Pres1"), True)

    def test_future_records_cannot_change_past_occupancy(self):
        rows = [record(observation(value=False)), record(observation(NOW+timedelta(minutes=10)))]
        self.assertIs(evaluate(rows), False)

    def test_late_receipt_not_applied_to_earlier_query(self):
        row = observation(NOW+timedelta(minutes=1), updated=NOW-timedelta(minutes=20))
        self.assertIsNone(evaluate([record(row)]))

    def test_future_signal_age_not_used_in_historical_health_check(self):
        old = NOW-timedelta(days=1)
        row = observation(old, updated=old-timedelta(hours=5))
        self.assertIs(evaluate([record(row)], target=old), True)

    def test_sensor_replacement_same_name_does_not_join_motion_histories(self):
        rows = [record(self.motion(NOW-timedelta(minutes=20), identity="old")),
                record(self.motion(identity="new"))]
        self.assertIs(evaluate(rows, source="Pres1"), False)

    def test_mapping_switch_ignores_old_source_in_room(self):
        rows = [record(self.motion(NOW-timedelta(minutes=20))), record(observation(value=False))]
        self.assertIs(evaluate(rows, source="Aqara2"), False)
        self.assertIsNone(evaluate([rows[0]], source="Aqara2"))

    def test_midnight_window_preserved(self):
        midnight = NOW.replace(hour=0, minute=5)
        rows = [record(self.motion(midnight-timedelta(minutes=20))), record(self.motion(midnight))]
        self.assertIs(evaluate(rows, source="Pres1", target=midnight), True)

    def test_no_input_mutation(self):
        rows = [record(observation())]
        old = copy.deepcopy(rows)
        evaluate(rows)
        self.assertEqual(rows, old)

    def test_live_cutover_does_not_reuse_fabricated_legacy_pres1_events(self):
        rows = [{"timestamp": at.isoformat(), "states": {"4": {"reachable": True, "state": True,
                 "last_updated": at.strftime("%Y-%m-%d-%H-%M-%S")}}}
                for at in (NOW-timedelta(minutes=20), NOW)]
        self.assertIsNone(evaluate(rows, source="Pres1"))
        self.assertIs(evaluate(rows, source="Pres1", legacy=True), True)

    def test_new_historical_records_use_presence_level_semantics(self):
        row = observation(updated=NOW-timedelta(hours=8))
        self.assertIs(evaluate([record(row)], legacy=True), True)

    def test_unknown_values_excluded_from_presence_probability(self):
        self.assertEqual(known_presence_fraction([True, None, False]), .5)
        self.assertIsNone(known_presence_fraction([None, None]))
        self.assertIsNone(known_presence_fraction([]))


class OccupancyIntegrationTests(unittest.TestCase):
    def test_presence_adapter_includes_hardware_and_does_not_restamp_pres1(self):
        from utils import project
        raw = {"name": "Pres1", "uniqueid": "aa-bb", "manufacturername": "eWeLink", "modelid": "MS01",
               "config": {"reachable": True}, "state": {"presence": True, "lastupdated": "2026-10-18T15:58:43.758"},
               "lastseen": "2026-10-18T15:58Z"}
        sensor = SimpleNamespace(name="Pres1", type="ZHAPresence", raw=raw)
        tz = SimpleNamespace(get_localzone=lambda: timezone.utc)
        with patch.object(project, "read_sensors", return_value=[("41", sensor)]), patch.object(project, "tzlocal", tz, create=True):
            row = project.get_presence_all(["Pres1"])["Pres1"]
        self.assertEqual(row["last_updated"], "2026-10-18-15-58-43")
        self.assertEqual(row["signal_type"], "motion")
        self.assertEqual(row["schema_version"], 2)

    def test_wrapper_keeps_single_and_multi_timestamp_return_shapes(self):
        from utils import project
        rows = [record(observation())]
        tz = SimpleNamespace(get_localzone=lambda: timezone.utc)
        config = {"presence_window": "30", "presence_min_sep": "15"}
        with patch.object(project, "load_recent_presence_log", return_value=rows), patch.object(project, "get_rooms_info", return_value={"4": {"pres": "Aqara2"}}), patch.object(project, "load_json_to_dict", return_value=config), patch.object(project, "tzlocal", tz, create=True):
            self.assertEqual(project.get_rooms_occupancy(timestamps=["2026-10-19-11-00-00"]), {"4": True})
            result = project.get_rooms_occupancy(timestamps=["2026-10-19-11-00-00", "2026-10-19-11-01-00"])
            self.assertEqual(result["2026-10-19-11-01-00"], {"4": True})

    def test_unknown_pattern_falls_back_to_configured_weekly_cycle(self):
        # This service has an intentional top-level Firebase loop. Extract only
        # the pure scheduling function to avoid starting it during unit tests.
        source = Path("services/schedule_and_config_updater.py").read_text(encoding="utf-8")
        tree = ast.parse(source)
        function = next(node for node in tree.body if isinstance(node, ast.FunctionDef) and node.name == "get_presence_patterns_with_weekly_cycle_weighted_average")
        import math
        namespace = {"heating_config": {"room_4_weekly_cycle_weight": "0", "room_4_in_threshold": "0.08"},
                     "export_path_prefix": "", "math": math,
                     "local_scheduling_files_relative_path": "unused",
                     "transpose_2D_array": lambda value: value,
                     "select_subtable_from_table": lambda value, **kwargs: value,
                     "sort_nested_dict": lambda value: value,
                     "load_json_to_dict": lambda path: {"4": {"1": {"11": None}}}}
        # The function's weekly-cycle reader is patched after inspecting its
        # normal implementation; no files or external services are involved.
        namespace["load_csv_to_2D_array"] = lambda *args, **kwargs: [[.75]*24 for _ in range(7)]
        exec(compile(ast.Module(body=[function], type_ignores=[]), "schedule-function", "exec"), namespace)
        self.assertEqual(namespace[function.name]("4", "1", 11), .75)


if __name__ == "__main__":
    unittest.main()
