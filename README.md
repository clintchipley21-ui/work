# LNTP Schedule Updater

A Windows desktop program that updates an LNTP P6 XER from a weekly engineering XER and generates a separate updated XER plus Excel-readable review reports. Original input files remain unchanged.

## Download and install — no administrator rights

1. On this GitHub page, click **Code → Download ZIP**.
2. Extract the entire ZIP. Do not run the installer from inside the ZIP.
3. Double-click **Install for my account.bat** using your normal Windows account.
4. Open **LNTP Schedule Updater** from the Desktop or Start Menu shortcut.

The installer uses `%LOCALAPPDATA%\LNTP Schedule Updater` and creates shortcuts only for your account. It reuses compatible Python if available; otherwise it downloads the official Python runtime, verifies its checksum and publisher signature, and installs it for your account. No machine-wide PATH change or elevation is requested.

## Use the program

Select the current **LNTP XER**, the latest **engineering XER**, and an **output folder**. Click **Update Schedule**. Each run creates a new result folder containing the updated XER and CSV reports. The included Activity ID corrections CSV applies the confirmed ID mapping.

The updater copies dates, labor units, status and the inputs for Physical, Duration and Units % Complete. It preserves LNTP-only activities and all existing relationships, and adds new engineering activities with their connected logic. Existing activities' logic, planned dates and the LNTP data date remain unchanged.

Read [GUI quick start](GUI_QUICK_START.md) for installation details and [field mappings and P6 import guidance](SCHEDULE_UPDATER.md) for exact behavior and limitations. Review the reports and import into a **P6 test copy** first.

## Validation and limitations

29 regression tests passed, and the GUI workflow was exercised with the supplied schedule files on Linux. Windows installer execution and P6 import/recalculation have not been tested in the development environment. This repository contains program files and tests, not the original schedule exports or generated reports.

The application uses Python's standard library only. Normal installation does not require building an EXE. The optional **Build Windows EXE.bat** creates a standalone EXE on Windows using PyInstaller.

```sh
python -m unittest discover -s tests -v
```
