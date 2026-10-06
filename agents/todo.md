# Agent TODO

## Low priority

- Decide the appropriate permanent location and structure for the current
  `config/shelly_devices.json`. Consider separating the human-maintained system
  topology from Shelly discovery settings, and account for loader paths and the
  repository synchronization policy before moving anything.
- Refresh `agents/services-catalog.md` against the current scripts in
  `services/` and `services/services_and_timers.list`. Add missing services,
  remove obsolete entries, and verify that lifecycle and output descriptions
  still match the implementation.
- Establish a principled backup policy covering what must be backed up, when a
  backup is warranted, where backups belong, retention and naming conventions,
  verification and restoration expectations, and when obsolete backups may be
  removed.
