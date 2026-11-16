# PhoneDeck

Turn your phone into a wireless control panel for your PC over Bluetooth Low Energy (BLE):
widgets with PC info, buttons that control it, and secure communication between the devices.

Work in progress.

## Development setup (Windows)

```powershell
py -3.12 -m venv .venv
.venv\Scripts\Activate.ps1
pip install -e ".[dev]"
pytest
```
