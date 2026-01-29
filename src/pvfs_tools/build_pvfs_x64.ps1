<#
.SYNOPSIS
    Builds 64-bit pvfs.dll and pvfs_wrapper.dll for the PVFS virtual file system.

.DESCRIPTION
    Uses CMake and Visual Studio (MSVC) to compile the PVFS Core native libraries
    as 64-bit Release DLLs. Outputs are placed in src/pvfs_tools/Core/ so that
    pvfs_binding.py can load them.

.PARAMETER CopyToCore
    If set (default), copies the built DLLs into Core/. If not set, DLLs remain
    only in the build directory.

.PARAMETER BuildDir
    Subdirectory used for the 64-bit build (default: build_x64).

.EXAMPLE
    .\build_pvfs_x64.ps1
    Builds and copies pvfs.dll and pvfs_wrapper.dll into Core/.

.EXAMPLE
    .\build_pvfs_x64.ps1 -CopyToCore:$false
    Builds without copying; DLLs stay in build_x64/Release/.
#>

[CmdletBinding()]
param(
    [switch]$CopyToCore = $true,
    [string]$BuildDir = "build_x64"
)

$ErrorActionPreference = "Stop"

# Resolve paths: script may be run from repo root or from src/pvfs_tools.
# Use absolute paths so CMake/VS use full paths and avoid "Release\pvfs.lib" relative-path linker errors.
$ScriptDir = (Resolve-Path (Split-Path -Parent $MyInvocation.MyCommand.Path)).Path
$CoreDir   = [System.IO.Path]::GetFullPath((Join-Path $ScriptDir "Core"))
$BuildPath = [System.IO.Path]::GetFullPath((Join-Path $CoreDir $BuildDir))

# Force a clean build: remove existing build dir and CMake cache so changes to CMakeLists.txt take effect.
# Close Visual Studio / IDE if the folder is in use.
if (Test-Path $BuildPath) {
    Write-Host "Removing existing build directory: $BuildPath"
    try {
        Remove-Item -Recurse -Force $BuildPath -ErrorAction Stop
    } catch {
        Write-Error "Could not remove $BuildPath. Close any program using it (e.g. Visual Studio, Explorer) and try again."
    }
}

if (-not (Test-Path $CoreDir)) {
    New-Item -ItemType Directory -Path $CoreDir -Force | Out-Null
}

# Required source files
$pvfsCpp = Join-Path $CoreDir "pvfs.cpp"
$pvfsH   = Join-Path $CoreDir "pvfs.h"
$wrapCpp = Join-Path $CoreDir "pvfs_wrapper.cpp"
$cmake   = Join-Path $CoreDir "CMakeLists.txt"

foreach ($f in @($pvfsCpp, $pvfsH, $wrapCpp, $cmake)) {
    if (-not (Test-Path $f)) {
        Write-Error "Missing required file: $f"
    }
}

# Find CMake
$cmakeExe = $null
if (Get-Command cmake -ErrorAction SilentlyContinue) {
    $cmakeExe = "cmake"
}
if (-not $cmakeExe) {
    Write-Error "CMake not found. Install CMake and add it to PATH, or run from a Visual Studio Developer PowerShell."
}

# Prefer VS 2022, then VS 2019 (64-bit generator)
$vsGenerators = @(
    @{ Name = "Visual Studio 17 2022"; Arch = "x64" },
    @{ Name = "Visual Studio 16 2019"; Arch = "x64" }
)

$Generator = $null
foreach ($g in $vsGenerators) {
    Write-Host "Trying generator: $($g.Name) -A $($g.Arch)"
    if (Test-Path $BuildPath) {
        Remove-Item -Recurse -Force $BuildPath -ErrorAction SilentlyContinue
    }
    & $cmakeExe -G $g.Name -A $g.Arch -S $CoreDir -B $BuildPath 2>&1 | Out-Host
    if ($LASTEXITCODE -eq 0) {
        $Generator = $g
        Write-Host "Configured with $($g.Name) (x64)."
        break
    }
}

if (-not $Generator) {
    Write-Error "Could not configure CMake with a 64-bit Visual Studio generator. Install Visual Studio 2019 or 2022 with the 'Desktop development with C++' workload."
}

n# Build from build dir so linker cwd is build_x64 and "Release\pvfs.lib" resolves (with target_link_directories).
Write-Host "Building Release (64-bit)..."
Push-Location $BuildPath
try {
    & $cmakeExe --build . --config Release
    $buildExit = $LASTEXITCODE
} finally {
    Pop-Location
}
if ($buildExit -ne 0) {
    Write-Error "Build failed."
}

# Output locations with VS multi-config generator
$ReleaseDir = Join-Path $BuildPath "Release"
$pvfsDll    = Join-Path $ReleaseDir "pvfs.dll"
$wrapDll    = Join-Path $ReleaseDir "pvfs_wrapper.dll"

foreach ($dll in @($pvfsDll, $wrapDll)) {
    if (-not (Test-Path $dll)) {
        Write-Error "Build did not produce expected output: $dll"
    }
}

Write-Host "Build succeeded. 64-bit DLLs:"
Write-Host "  $pvfsDll"
Write-Host "  $wrapDll"

if ($CopyToCore) {
    Copy-Item -Path $pvfsDll -Destination (Join-Path $CoreDir "pvfs.dll") -Force
    Copy-Item -Path $wrapDll -Destination (Join-Path $CoreDir "pvfs_wrapper.dll") -Force
    Write-Host "Copied both DLLs to: $CoreDir"
}
