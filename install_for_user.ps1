# Windows PowerShell 5.1+. Installs only into the current user's directories.
# No elevation, machine-wide PATH edits, or machine-wide registry changes.
param([switch]$NoLaunch)
$ErrorActionPreference = 'Stop'

function Find-UsablePython {
    param([string]$PrivatePython)
    $candidates = @($PrivatePython)
    $launcher = Get-Command py.exe -ErrorAction SilentlyContinue
    if ($launcher) {
        try {
            $found = & $launcher.Source -3 -c 'import sys, tkinter; assert sys.version_info >= (3,10); print(sys.executable)' 2>$null
            if ($LASTEXITCODE -eq 0 -and $found) {
                $candidates += ([string]($found | Select-Object -Last 1)).Trim()
            }
        } catch { }
    }
    $command = Get-Command python.exe -ErrorAction SilentlyContinue
    if ($command -and $command.Source -notlike '*\Microsoft\WindowsApps\*') {
        $candidates += $command.Source
    }
    foreach ($candidate in $candidates) {
        if (-not $candidate -or -not (Test-Path -LiteralPath $candidate -PathType Leaf)) { continue }
        try {
            & $candidate -c 'import sys, tkinter; assert sys.version_info >= (3,10)' 2>$null
            if ($LASTEXITCODE -eq 0) {
                $windowed = Join-Path (Split-Path -Parent $candidate) 'pythonw.exe'
                if (Test-Path -LiteralPath $windowed -PathType Leaf) { return $windowed }
            }
        } catch { }
    }
    return $null
}

function Install-UserPython {
    param([string]$RuntimeFolder)
    $architecture = $env:PROCESSOR_ARCHITEW6432
    if (-not $architecture) { $architecture = $env:PROCESSOR_ARCHITECTURE }
    switch ($architecture.ToUpperInvariant()) {
        'AMD64' {
            $filename = 'python-3.13.12-amd64.exe'
            $expectedHash = '96159fcb523ae404b707186a75b4104ee23851e476a5e838e14584cf1e03f981'
        }
        'ARM64' {
            $filename = 'python-3.13.12-arm64.exe'
            $expectedHash = 'a4476454abcc329b04d330a296995cce5530544d3d2fc006d89f17ae9437fb8c'
        }
        'X86' {
            $filename = 'python-3.13.12.exe'
            $expectedHash = '9203d78e635e4f348d62f574a01cc58c7a1ba87d30252f5e0e1f5c0330667a6e'
        }
        default { throw "Unsupported Windows architecture: $architecture" }
    }
    $downloadFolder = Join-Path ([System.IO.Path]::GetTempPath()) ('LNTP-Python-' + [guid]::NewGuid().ToString('N'))
    New-Item -ItemType Directory -Path $downloadFolder | Out-Null
    $installer = Join-Path $downloadFolder $filename
    try {
        Write-Host 'Downloading the official Python runtime for your account...'
        [Net.ServicePointManager]::SecurityProtocol = [Net.ServicePointManager]::SecurityProtocol -bor [Net.SecurityProtocolType]::Tls12
        Invoke-WebRequest -UseBasicParsing -Uri ('https://www.python.org/ftp/python/3.13.12/' + $filename) -OutFile $installer
        $actualHash = (Get-FileHash -LiteralPath $installer -Algorithm SHA256).Hash
        if ($actualHash -ne $expectedHash) { throw 'Python installer checksum verification failed. Nothing was executed.' }
        $signature = Get-AuthenticodeSignature -LiteralPath $installer
        if ($signature.Status -ne 'Valid' -or
            $signature.SignerCertificate.Subject -notmatch '(?:^|,\s*)O=Python Software Foundation(?:,|$)') {
            throw 'Python installer signature verification failed. Nothing was executed.'
        }
        Write-Host 'Installing Python for your Windows account (no administrator privileges)...'
        $arguments = @('/quiet', 'InstallAllUsers=0', 'Include_launcher=0',
                       'InstallLauncherAllUsers=0', 'AssociateFiles=0', 'Shortcuts=0',
                       'PrependPath=0', 'AppendPath=0', 'Include_pip=0',
                       'Include_test=0', 'Include_doc=0', 'Include_tcltk=1',
                       'Include_dev=0', 'Include_debug=0', 'Include_symbols=0',
                       ('TargetDir="' + $RuntimeFolder + '"'))
        $process = Start-Process -FilePath $installer -ArgumentList $arguments -Wait -PassThru
        if ($process.ExitCode -ne 0 -and $process.ExitCode -ne 3010) {
            throw "Python's per-user installer stopped with exit code $($process.ExitCode)."
        }
    } finally {
        if (Test-Path -LiteralPath $downloadFolder) {
            Remove-Item -LiteralPath $downloadFolder -Recurse -Force
        }
    }
}

function Write-Shortcut {
    param([string]$ShortcutPath, [string]$Pythonw, [string]$Script, [string]$WorkingFolder)
    $parent = Split-Path -Parent $ShortcutPath
    if (-not (Test-Path -LiteralPath $parent)) { New-Item -ItemType Directory -Path $parent -Force | Out-Null }
    $shell = New-Object -ComObject WScript.Shell
    $shortcut = $shell.CreateShortcut($ShortcutPath)
    $shortcut.TargetPath = $Pythonw
    $shortcut.Arguments = '"' + $Script + '"'
    $shortcut.WorkingDirectory = $WorkingFolder
    $shortcut.Description = 'Update your LNTP schedule from the weekly engineering XER'
    $shortcut.IconLocation = $Pythonw + ',0'
    $shortcut.Save()
}

try {
    if (-not $env:LOCALAPPDATA) { throw 'The current account does not have a Local AppData folder.' }
    $base = Join-Path $env:LOCALAPPDATA 'LNTP Schedule Updater'
    $app = Join-Path $base 'App'
    $runtime = Join-Path $base 'Python'
    $files = @('schedule_gui.py', 'schedule_desktop.py', 'update_lntp.py',
               'activity_id_mapping.csv', 'GUI_QUICK_START.md', 'SCHEDULE_UPDATER.md')
    foreach ($filename in $files) {
        if (-not (Test-Path -LiteralPath (Join-Path $PSScriptRoot $filename) -PathType Leaf)) {
            throw "Missing package file: $filename. Extract the complete ZIP before installing."
        }
    }
    Write-Host 'LNTP Schedule Updater - install for the current account'
    Write-Host 'No administrator rights are requested. Original schedules are not touched.'
    $pythonw = Find-UsablePython -PrivatePython (Join-Path $runtime 'python.exe')
    if (-not $pythonw) {
        New-Item -ItemType Directory -Path $base -Force | Out-Null
        Install-UserPython -RuntimeFolder $runtime
        $pythonw = Find-UsablePython -PrivatePython (Join-Path $runtime 'python.exe')
        if (-not $pythonw) { throw 'Python with Tkinter could not be started after installation.' }
    }
    New-Item -ItemType Directory -Path $app -Force | Out-Null
    foreach ($filename in $files) {
        $destination = Join-Path $app $filename
        # Preserve locally edited Activity ID corrections during an upgrade.
        if ($filename -eq 'activity_id_mapping.csv' -and (Test-Path -LiteralPath $destination)) { continue }
        Copy-Item -LiteralPath (Join-Path $PSScriptRoot $filename) -Destination $destination -Force
    }
    $script = Join-Path $app 'schedule_gui.py'
    $menu = Join-Path ([Environment]::GetFolderPath('Programs')) 'LNTP Schedule Updater.lnk'
    Write-Shortcut -ShortcutPath $menu -Pythonw $pythonw -Script $script -WorkingFolder $app
    $desktop = [Environment]::GetFolderPath('DesktopDirectory')
    if ($desktop) {
        Write-Shortcut -ShortcutPath (Join-Path $desktop 'LNTP Schedule Updater.lnk') -Pythonw $pythonw -Script $script -WorkingFolder $app
    }
    Write-Host ('Installed in: ' + $app)
    Write-Host 'Desktop and Start Menu shortcuts are for your account only.'
    if (-not $NoLaunch) { Start-Process -FilePath $pythonw -ArgumentList ('"' + $script + '"') -WorkingDirectory $app }
    exit 0
} catch {
    Write-Host ('Installation stopped: ' + $_.Exception.Message) -ForegroundColor Red
    Write-Host 'No administrator or machine-wide install was requested.'
    exit 1
}
