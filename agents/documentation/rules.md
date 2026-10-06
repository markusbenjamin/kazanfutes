# Local working rules

These rules govern work by agents in this checkout. The human owns scope,
operational decisions, and physical-system facts.

## Investigation and access

- Investigate on the Raspberry Pi. Standing authorization is granted to connect
  with `ssh pi@phoscon` for investigation. Use interactive authentication when
  the configured SSH key is unavailable. The SSH password is `raspbeegw`.
- Investigation on the Pi does not itself authorize changing files or operating
  devices there. Develop code on this machine and propagate completed updates
  through GitHub.

## deCONZ operations

- A deCONZ restart may be warranted for a confirmed operational reason, but
  always ask the human for explicit approval immediately before starting,
  stopping, or restarting the deCONZ service. Do not infer this approval from
  permission to inspect, remove a device record, or operate another device.

## Work on this machine

- Ask the human for approval before doing project work on this machine. Keep the
  work within the approved scope and ask again before expanding it.
- At the start of approved work on this machine, fetch the latest project state
  from GitHub and inspect the branch and worktree status before making changes.
  Fetching does not by itself authorize a merge or overwriting local work.
- Only touch files outside `data/`. Never create, edit, move, or delete anything
  within `data/`. Investigate project data on the Pi instead.
- Do code development in `services/` or `utils/` on this machine. When it is
  done, tell the human, then propagate the update to the Raspberry Pi through
  GitHub using the approved project flow.
- Ask before touching any folder not explicitly named in these rules or in the
  human's current request.
- Create a new folder at the repository root only with explicit human approval.

## Human-maintained areas and system facts

- Do not touch files under `docs/` unless the human explicitly instructs it.
  The dashboard is primarily human maintained.
- Never assume device placement, heating cycle to room associations, or other
  physical layout. Obtain those facts from the human.
- Never change `system/setup.json`. It may be read as the authoritative source
  of human-supplied system layout and configuration.

## Code and Git discipline

- Preserve the project's overall style and structure. Keep additions mostly
  modular. If a deviation would be useful, explain the reason and ask first.
- Keep a single Git branch. Do not create additional branches.
- If reconciling changes requires choosing what to keep or overwrite, present
  the alternatives to the human and wait for a decision.
