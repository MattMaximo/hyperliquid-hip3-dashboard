from __future__ import annotations

import json
from pathlib import Path

from build_data import DATA_DIR, OUTPUT_PATH, write_static_site


def main() -> None:
    payload = json.loads(Path(OUTPUT_PATH).read_text(encoding="utf-8"))
    write_static_site(payload)
    print(f"Rendered static site from {DATA_DIR / 'dashboard-data.json'}")


if __name__ == "__main__":
    main()
