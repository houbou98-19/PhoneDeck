"""This installation's identity: a random BLE service UUID, made once and then kept.

Every PC advertises its own UUID, so nobody can spot "a PhoneDeck PC" by scanning.
"""

import uuid
from pathlib import Path


def load_or_create_service_uuid(path: Path) -> str:
    """Read the UUID in the file, or make a random one and save it there (lowercase text)."""
    try:
        content = path.read_text().strip()
        service_uuid = str(uuid.UUID(content))
    except (FileNotFoundError, ValueError):
        pass

    else:
        return service_uuid

    service_uuid = str(uuid.uuid4())
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(service_uuid)
    return service_uuid
