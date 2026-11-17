"""This installation's identity: the BLE service UUID, made once and then kept.

Every PC running PhoneDeck advertises its own random service UUID, so that nobody can spot
"a PhoneDeck PC" by scanning, and two PCs in one room never get mixed up. The UUID is made
the first time and saved in a small local file (never in the repository).
"""

import uuid
from pathlib import Path


def load_or_create_service_uuid(path: Path) -> str:
    """Return this installation's service UUID. Make and save one if there is none yet.

    The UUID is a random (version 4) UUID, written as lowercase text, like
    "7d2a0001-8c1e-4b6f-9a3d-5e1f0c2b4a10". It is saved as that text in the file at path.

      * First call, no file: make a UUID, save it (make missing folders too), return it.
      * Later calls: return the same UUID.
      * Surrounding spaces and newlines in the file are fine, and so are capital letters:
        the answer is always the lowercase form.
      * If the file is empty or does not hold a UUID, make a new one and save it over it.
      * Different paths are different installations and get different UUIDs.

    """
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
