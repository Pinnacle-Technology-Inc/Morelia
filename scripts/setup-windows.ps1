#Requires -Version 5.1
#Requires -RunAsAdministrator
[CmdletBinding()]
param(
    [string]$RepoUrl = 'https://github.com/Pinnacle-Technology/Morelia.git',
    [string]$Branch = 'watchdog',
    [string]$Distro = 'Ubuntu-24.04',
    [string]$LinuxPath = '~/Morelia',
    [ValidatePattern('^$|^[0-9]+-[0-9]+$')][string]$UsbBusId = '',
    [switch]$SkipUsb
)
$ErrorActionPreference = 'Stop'
[Net.ServicePointManager]::SecurityProtocol = [Net.SecurityProtocolType]::Tls12

function Assert-Exit([string]$Step) {
    if ($LASTEXITCODE -ne 0) { throw "$Step failed (exit $LASTEXITCODE). Fix the reported error and rerun setup." }
}

# No Windows Python, Git, Node or winget is required.
if (-not $SkipUsb) {
    $usbCommand = Get-Command usbipd.exe -ErrorAction SilentlyContinue
    $usbExe = if ($usbCommand) { $usbCommand.Source } else { "$env:ProgramFiles\usbipd-win\usbipd.exe" }
    if (-not (Test-Path -LiteralPath $usbExe)) {
        Write-Host 'Downloading the official usbipd-win installer...'
        $release = Invoke-RestMethod 'https://api.github.com/repos/dorssel/usbipd-win/releases/latest'
        $arch = if ($env:PROCESSOR_ARCHITECTURE -eq 'ARM64' -or $env:PROCESSOR_ARCHITEW6432 -eq 'ARM64') { 'arm64' } else { 'x64' }
        $asset = @($release.assets | Where-Object { $_.name -match "_$arch\.msi$" })
        if ($asset.Count -ne 1) { throw "Could not identify the official $arch usbipd MSI." }
        $installer = Join-Path $env:TEMP ("morelia-usbipd-" + [guid]::NewGuid() + '.msi')
        try {
            Invoke-WebRequest -UseBasicParsing $asset[0].browser_download_url -OutFile $installer
            if ((Get-AuthenticodeSignature -LiteralPath $installer).Status -ne 'Valid') {
                throw 'usbipd installer signature validation failed.'
            }
            $installProcess = Start-Process msiexec.exe -ArgumentList @('/i', "`"$installer`"", '/passive', '/norestart') -WindowStyle Hidden -Wait -PassThru
            if ($installProcess.ExitCode -eq 3010) {
                Write-Host 'USB driver installed. Restart Windows, then run this same command again.'
                exit 3010
            }
            if ($installProcess.ExitCode -ne 0) { throw "usbipd installation failed: $($installProcess.ExitCode)" }
        } finally {
            Remove-Item -LiteralPath $installer -Force -ErrorAction SilentlyContinue
        }
    }
}

# An uninitialized WSL installation can write to stderr in Windows PowerShell.
$previousPreference = $ErrorActionPreference
try {
    $ErrorActionPreference = 'Continue'
    $installed = (& wsl.exe --list --quiet 2>$null | Out-String) -replace "`0", ''
    $listExitCode = $LASTEXITCODE
} finally {
    $ErrorActionPreference = $previousPreference
}
if ($listExitCode -ne 0 -or ($installed -split '\r?\n').Trim() -notcontains $Distro) {
    & wsl.exe --install --distribution $Distro --no-launch
    if ($LASTEXITCODE -eq 3010) {
        Write-Host 'Restart Windows, open Ubuntu to create your Linux user, then rerun this command.'
        exit 3010
    }
    Assert-Exit 'WSL installation'
    Write-Host "Restart Windows if requested. Open $Distro from Start and create your Linux username/password. Then rerun this same setup command."
    exit 0
}
& wsl.exe --set-version $Distro 2
Assert-Exit 'Selecting WSL2'
& wsl.exe --distribution $Distro --exec true
Assert-Exit 'Starting WSL'

$helper = Join-Path $PSScriptRoot 'setup-wsl.sh'
if (-not (Test-Path -LiteralPath $helper)) { throw 'Keep setup-windows.ps1 and setup-wsl.sh together in the scripts folder.' }
# Normalize line endings even when these files came from a Windows ZIP/checkout.
$tempHelper = Join-Path $env:TEMP ("morelia-setup-" + [guid]::NewGuid() + '.sh')
try {
    [IO.File]::WriteAllText($tempHelper, ([IO.File]::ReadAllText($helper) -replace "`r`n", "`n"), (New-Object Text.UTF8Encoding($false)))
    $wslHelper = & wsl.exe --distribution $Distro --exec wslpath -u $tempHelper
    Assert-Exit 'Resolving installer path'
    & wsl.exe --distribution $Distro --exec bash $wslHelper $RepoUrl $Branch $LinuxPath
    Assert-Exit 'Linux repository setup'
} finally {
    Remove-Item -LiteralPath $tempHelper -Force -ErrorAction SilentlyContinue
}

if (-not $SkipUsb) {
    & $usbExe list
    Assert-Exit 'Listing USB devices'
    if ($UsbBusId) {
        & $usbExe bind --busid $UsbBusId
        Assert-Exit 'Sharing USB device'
        & $usbExe attach --wsl --busid $UsbBusId
        Assert-Exit 'Attaching USB device'
    } else {
        Write-Host 'To attach your POD, rerun with -UsbBusId <BUSID from the list above>.'
    }
}
Write-Host "Setup complete. Open $Distro and run: cd $LinuxPath && bash scripts/run-dashboard.sh"
Write-Host 'Then open http://localhost:5173 in your Windows browser.'
