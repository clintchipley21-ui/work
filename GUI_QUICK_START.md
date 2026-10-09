# LNTP Schedule Updater — desktop interface

## Install for your Windows account — no administrator rights

1. Extract the whole ZIP into a folder. Keep the files together.
2. Double-click **Install for my account.bat** using your normal Windows account. Do not choose "Run as administrator."
3. The installer reuses a compatible Python installation if available. Otherwise it downloads the official Python 3.13.12 installer, verifies its SHA-256 hash and Windows publisher signature, and installs the runtime for your account. Internet access to `www.python.org` is needed for that download.
4. Open **LNTP Schedule Updater** from your Desktop or Start Menu shortcut. The installer also opens it when finished.

Application files live in `%LOCALAPPDATA%\LNTP Schedule Updater\App`. If a runtime is needed, it is installed in `%LOCALAPPDATA%\LNTP Schedule Updater\Python`. Shortcuts are created only for your account. Installation does not request elevation or change the machine-wide PATH. Each person can install independently under their own Windows account. Reinstalling updates the application while preserving your installed Activity ID corrections CSV.

You can also run directly from the extracted folder by double-clicking **Launch Schedule Updater.bat** when Python 3.10+ with Tkinter is already installed. No commands or additional Python packages are needed for normal use.

## Update your schedule

1. Click **Browse** beside **Current LNTP schedule** and select your current LNTP XER.
2. Click **Browse** beside **Engineering weekly update** and select the engineers' latest XER.
3. Choose the folder where you want the results saved.
4. Leave **Add new engineering activities and their logic** checked to include new work.
5. Click **Update Schedule**.

When complete, the window displays the counts and any important review notes. Click **Open Results Folder** to find the updated XER and a **Reports** folder. **Open Change Report** and **Open Warnings** open their CSVs using your computer's default application; Excel can read them.

Every run creates a separate result folder. Neither input is changed. If an update fails, the program removes its temporary outputs and displays the reason. It processes files locally; there is no upload or connection to P6.

The included Activity ID corrections CSV applies your confirmed mapping from engineering `EE.50.560.035.IFR` to LNTP `EE.50.560.035I.FR`. Leave it selected for these schedules. You can browse to another mapping CSV or click **Clear** for schedules that do not use this correction. A mapping that refers to an absent activity stops the update rather than guessing.

Physical, Duration and Units % Complete inputs and their method are copied from engineering. Existing LNTP relationships and LNTP-only work are preserved. Existing engineering activities' logic is not revised. The program retains the LNTP data date and planned dates. See **SCHEDULE_UPDATER.md** for the exact fields, limitations and P6 import instructions.

Review the reports, then import the XER into a **P6 test copy** first. Engineering's current file reopens 22 completed activities and clears 22 actual-date fields. P6 may recalculate dates and percentages; this application does not run P6 or validate your import settings.

## Optional: make a standalone Windows EXE

On a Windows computer with Python installed, double-click **Build Windows EXE.bat**. This downloads the pinned PyInstaller build tool into a local `.build-venv` folder and creates **dist/LNTP Schedule Updater.exe**. The EXE includes Python and the mapping CSV; computers running that EXE do not need Python installed.

The downloadable package contains the Python GUI, a per-user installer, and optional EXE build instructions. A standalone Windows EXE must be built and tested on Windows; it is not included or claimed as tested in this package. The installer is designed for Windows PowerShell 5.1+ and a normal user account. Installer execution on Windows still needs verification; the development machine is Linux.

## Mac or Linux

With Python 3.10+ and Tkinter installed, run `python3 schedule_gui.py` from the extracted folder. The same interface and outputs apply. On Linux, your distribution may package Tkinter separately. The Windows launcher/build scripts apply only to Windows.
