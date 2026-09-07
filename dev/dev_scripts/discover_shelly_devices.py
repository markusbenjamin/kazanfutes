#!/usr/bin/env python3
"""Run on the Raspberry Pi to refresh and display the Shelly identity cache."""

import json

from utils.project import get_project_root
from utils.shelly_discovery import build_shelly_resolver, load_shelly_config


project_root = get_project_root()
config = load_shelly_config(project_root)
resolver = build_shelly_resolver(project_root, config)

print(json.dumps(resolver.discover(force_scan=True), indent=2, ensure_ascii=False))
