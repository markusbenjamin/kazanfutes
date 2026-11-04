"""Human visual resolutions, kept separate from measured PV recovery."""

from copy import deepcopy
from datetime import date, datetime
import hashlib
from zoneinfo import ZoneInfo


def inspection_details(state):
    resolution = state.get("visual_resolution")
    return {"inspection_status": "open" if state.get("incident") else
            "visually_resolved" if resolution else "no_open_inspection",
            "visual_resolution": resolution,
            "post_resolution_evidence_days": sum(row["day"] > state["evidence_after_day"]
                                                 for row in state.get("history", [])) if resolution else None}


def evidence_after_inspection(rows, state):
    """Delayed observations from before the inspection cannot reopen its alert."""
    cutoff = state.get("evidence_after_day")
    if cutoff is None:
        return rows
    date.fromisoformat(cutoff)
    return [{**row, "qualified": False, "excluded_by_visual_resolution": True}
            if row["day"] <= cutoff else row for row in rows]


def visually_resolve(state, targets, now, note, inspected_by="admin", timezone="Europe/Budapest"):
    """Mutate a loaded state atomically at its caller; do not claim electrical health."""
    if now.tzinfo is None:
        raise ValueError("Inspection time must include a timezone")
    note, inspected_by = note.strip(), inspected_by.strip()
    if not note or len(note) > 4000 or not inspected_by or len(inspected_by) > 200:
        raise ValueError("Provide an inspection note (up to 4000 characters) and inspector name")
    if not targets or len(set(targets)) != len(targets) or any(t not in state["targets"] for t in targets):
        raise ValueError("Select each available monitored target once")
    day = now.astimezone(ZoneInfo(timezone)).date().isoformat()
    for target in targets:
        item = state["targets"][target]
        if item.get("last_day") and item["last_day"] >= day:
            raise ValueError("Inspection must follow already processed days")
        if item.get("visual_resolution") and now < datetime.fromisoformat(item["visual_resolution"]["resolved_at"]):
            raise ValueError("Inspection time precedes the previous resolution")
    events = []
    for target in targets:
        item = state["targets"][target]
        incident = item.get("incident")
        if incident is None:
            continue  # Repeating a resolution cannot erase newly collected evidence.
        record = {"target": target, "incident_id": incident["id"], "resolved_at": now.isoformat(),
                  "inspected_day": day, "inspected_by": inspected_by, "note": note,
                  "outcome": "no_visible_fault_found", "performance_recovery_confirmed": False,
                  "previous_incident": deepcopy(incident), "previous_evidence": deepcopy(item.get("history", [])),
                  "last_evidence_day": item.get("last_evidence_day")}
        record["resolution_id"] = hashlib.sha256((state["model_id"] + target + incident["id"] + now.isoformat()).encode()).hexdigest()
        state.setdefault("visual_resolutions", []).append(record)
        item["visual_resolution"] = record
        item["evidence_after_day"] = day
        item["incident"] = None
        item["history"], item["recovery"] = [], []
        if item.get("latest"):
            item["latest"]["inspection_open"] = False
        events.append({**incident, "kind": "inspection_visually_resolved", "target": target,
                       "resolved_at": record["resolved_at"], "inspected_by": inspected_by, "note": note,
                       "resolution_id": record["resolution_id"], "performance_recovery_confirmed": False})
    if events:
        state["recent_events"] = (state.get("recent_events", []) + events)[-200:]
        state["last_admin_action_at"] = now.isoformat()
    return events
