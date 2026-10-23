# Run alongside 8401_two_devices_watchdog.py in a separate PowerShell window.
# Reads Windows PnP metadata only; never opens, resets, or disables a COM port.
# Start with both devices connected. Restart this monitor after changing cabling.

$Ports = @('COM4', 'COM5')
$PollIntervalSeconds = 1
$DurationSeconds = 0 # 0 = until Ctrl+C
$AncestorLevels = 3 # serial device, USB converter, hub, root hub
$LogPath = Join-Path $PSScriptRoot ('usb-connections-' + (Get-Date -Format 'yyyyMMdd-HHmmss-fff') + '.jsonl')

# These APIs query names and devnodes; neither obtains a serial I/O handle.
if (-not ('MoreliaSerialNative' -as [type])) {
    Add-Type -TypeDefinition @'
using System;
using System.Runtime.InteropServices;
using System.Text;
public static class MoreliaSerialNative {
    [DllImport("kernel32.dll", CharSet = CharSet.Unicode, ExactSpelling = true, SetLastError = true)]
    public static extern uint QueryDosDeviceW(string name, StringBuilder target, uint size);
    [DllImport("cfgmgr32.dll", CharSet = CharSet.Unicode, ExactSpelling = true)]
    public static extern uint CM_Locate_DevNodeW(out uint devInst, string instanceId, uint flags);
}
'@
}

function Get-NativeConnectionIdentity {
    param([string]$InstanceId, [string]$Port)
    [uint32]$devInst = 0
    # NORMAL = 0: never use CANCELREMOVE, which would alter a removal in progress.
    $result = [MoreliaSerialNative]::CM_Locate_DevNodeW([ref]$devInst, $InstanceId, 0)
    $target = $null
    $dosError = $null
    if ($Port) {
        $buffer = New-Object System.Text.StringBuilder 32768
        if ([MoreliaSerialNative]::QueryDosDeviceW($Port, $buffer, 32768) -eq 0) {
            $dosError = [Runtime.InteropServices.Marshal]::GetLastWin32Error()
        }
        else {
            # QueryDosDevice's first string is the current mapping.
            $target = $buffer.ToString().Split([char]0)[0]
        }
    }
    [pscustomobject]@{
        DevInst = $(if ($result -eq 0) { $devInst } else { $null })
        DevInstHex = $(if ($result -eq 0) { '0x{0:X}' -f $devInst } else { $null })
        LocateDevNodeResult = ('0x{0:X}' -f $result)
        DosDeviceTarget = $target
        DosDeviceQueryError = $dosError
    }
}

function Get-ConnectionSnapshot {
    param([string]$InstanceId, [string]$Port)

    $native = Get-NativeConnectionIdentity -InstanceId $InstanceId -Port $Port
    try {
        # Reading all available properties avoids errors for unsupported keys.
        $properties = @(Get-PnpDeviceProperty -InstanceId $InstanceId -ErrorAction Stop)
        if ($properties.Count -eq 0) { throw 'No device properties returned' }
        $values = @{}
        foreach ($property in $properties) {
            $value = $property.Data
            if ($value -is [datetime]) { $value = $value.ToUniversalTime().ToString('o') }
            $values[$property.KeyName] = $value
        }
        [pscustomobject][ordered]@{
            InstanceId = $InstanceId
            Native = $native
            Present = $values['DEVPKEY_Device_IsPresent']
            PDO = $values['DEVPKEY_Device_PDOName']
            LastArrivalUtc = $values['DEVPKEY_Device_LastArrivalDate']
            LastRemovalUtc = $values['DEVPKEY_Device_LastRemovalDate']
            Parent = $values['DEVPKEY_Device_Parent']
            LocationPaths = $values['DEVPKEY_Device_LocationPaths']
            ContainerId = $values['DEVPKEY_Device_ContainerId']
            Service = $values['DEVPKEY_Device_Service']
            DriverVersion = $values['DEVPKEY_Device_DriverVersion']
            ProblemCode = $values['DEVPKEY_Device_ProblemCode']
            QueryError = $null
        }
    }
    catch {
        # A query failure is unknown state, not proof of device removal.
        [pscustomobject][ordered]@{
            InstanceId = $InstanceId
            Native = $native
            Present = $null
            PDO = $null
            LastArrivalUtc = $null
            LastRemovalUtc = $null
            Parent = $null
            QueryError = $_.Exception.Message
        }
    }
}

function Start-SerialConnectionMonitor {
    $ErrorActionPreference = 'Stop'
    $tracked = [ordered]@{}
    $portForNode = @{}
    $devices = @(Get-PnpDevice -Class Ports -PresentOnly -ErrorAction Stop)
    foreach ($port in $Ports) {
        $matchesForPort = @($devices | Where-Object {
            $_.FriendlyName -match ('\(' + [regex]::Escape($port) + '\)$')
        })
        if ($matchesForPort.Count -ne 1) {
            throw "Expected one connected device for $port; found $($matchesForPort.Count). Connect both devices first."
        }
        $nodeId = $matchesForPort[0].InstanceId
        $portForNode[$nodeId] = $port
        for ($level = 0; $level -le $AncestorLevels -and $nodeId; $level++) {
            $label = if ($level -eq 0) { "$port serial" } else { "$port parent $level" }
            if ($tracked.Contains($nodeId)) { $tracked[$nodeId] += ", $label" }
            else { $tracked[$nodeId] = $label }
            $snapshot = Get-ConnectionSnapshot $nodeId
            if ($snapshot.QueryError) { throw $snapshot.QueryError }
            $nodeId = $snapshot.Parent
        }
    }

    Write-Host "Read-only PnP monitor. Log: $LogPath"
    Write-Host 'Baseline and changes only. Times are UTC. Ctrl+C stops monitoring.'
    Write-Host 'Polls are sequential; brief changes may be missed. Unchanged PDO/times do not rule out a USB reset.'
    foreach ($entry in $tracked.GetEnumerator()) {
        Write-Host "$($entry.Value): $($entry.Key)"
    }

    $previous = @{}
    $started = [datetime]::UtcNow
    do {
        foreach ($entry in $tracked.GetEnumerator()) {
            $snapshot = Get-ConnectionSnapshot -InstanceId $entry.Key -Port $portForNode[$entry.Key]
            $fingerprint = $snapshot | ConvertTo-Json -Depth 6 -Compress
            if ($previous[$entry.Key] -ne $fingerprint) {
                $kind = if ($previous.ContainsKey($entry.Key)) { 'CHANGE' } else { 'BASELINE' }
                $observed = [datetime]::UtcNow.ToString('o')
                [ordered]@{
                    ObservedUtc = $observed
                    Kind = $kind
                    Node = $entry.Value
                    Snapshot = $snapshot
                } | ConvertTo-Json -Depth 8 -Compress | Add-Content -LiteralPath $LogPath -Encoding UTF8
                Write-Host "`n[$observed] $kind $($entry.Value)"
                $snapshot | Select-Object Present, PDO, LastArrivalUtc, LastRemovalUtc, QueryError | Format-List
                $snapshot.Native | Format-List
                $previous[$entry.Key] = $fingerprint
            }
        }
        if ($DurationSeconds -gt 0 -and ([datetime]::UtcNow - $started).TotalSeconds -ge $DurationSeconds) { break }
        Start-Sleep -Seconds $PollIntervalSeconds
    } while ($true)
}

# Dot-sourcing loads helpers without starting the loop, useful for inspection.
if ($MyInvocation.InvocationName -ne '.') {
    Start-SerialConnectionMonitor
}
