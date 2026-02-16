from utils.project import *
from pathlib import Path

rooms_info = get_rooms_info()

rules = {}
for room,info in rooms_info.items():
    if isinstance(info['pres'],str):
        rules[info['pres']+"\":"] = room+"\":"

print(rules)

# ─── SETTINGS ────────────────────────────────────────────────────────────────
SOURCE_DIR = Path(f"{get_project_root()}\\data\\logs\\presence")               # where the original files live
EXPORT_DIR = Path(f"{get_project_root()}\\dev\\data\\presence")  # output folder (will be created)

# ─── IMPLEMENTATION ─────────────────────────────────────────────────────────
EXPORT_DIR.mkdir(parents=True, exist_ok=True)

for file_path in SOURCE_DIR.glob('presence_all*'):          # 1)
    if file_path.is_file():
        text = file_path.read_text(encoding='utf-8')

        # 2) apply all replacements
        for old, new in rules.items():
            text = text.replace(old, new)

        # 3) write to export dir
        out_path = EXPORT_DIR / file_path.name
        out_path.write_text(text, encoding='utf-8')
        print(f'✓ {file_path}  →  {out_path}')

print('Done.')
