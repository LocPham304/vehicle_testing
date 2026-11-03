# Run on Windows while wifi_websocket_receiver.py is running on the Pi.
# Scan LAN: powershell -NoProfile -ExecutionPolicy Bypass -File .\test_wifi_websocket.ps1
# One Pi:   powershell -NoProfile -ExecutionPolicy Bypass -File .\test_wifi_websocket.ps1 -Ip 192.168.1.40
# Only sends {"action":"identify"}; never uploads or executes robot code.

[CmdletBinding(DefaultParameterSetName = 'Scan')]
param(
    [Parameter(ParameterSetName = 'Scan')]
    [string]$Subnet = '192.168.1',

    [Parameter(Mandatory = $true, ParameterSetName = 'Single')]
    [string]$Ip,

    [ValidateRange(1, 65535)]
    [int]$Port = 50000,

    [ValidateRange(100, 30000)]
    [int]$TimeoutMs = 3000
)

$ErrorActionPreference = 'Stop'
$targets = @()
if ($PSCmdlet.ParameterSetName -eq 'Single') {
    $targets = @($Ip)
} else {
    if ($Subnet -notmatch '^\d{1,3}\.\d{1,3}\.\d{1,3}$') {
        throw 'Subnet must be three IPv4 octets, for example: -Subnet 192.168.1'
    }
    $targets = @(1..254 | ForEach-Object { "$Subnet.$_" })
}
foreach ($targetIp in $targets) {
    $parsedIp = $null
    if (-not [Net.IPAddress]::TryParse($targetIp, [ref]$parsedIp) -or
        $parsedIp.AddressFamily -ne [Net.Sockets.AddressFamily]::InterNetwork) {
        throw "Invalid IPv4 address: $targetIp"
    }
}

$pending = @()
$found = @()
$timer = [Diagnostics.Stopwatch]::StartNew()
Write-Host "Testing $($targets.Count) IP(s), ws://<IP>:$Port/stem, timeout ${TimeoutMs}ms"
try {
    # Start handshakes together so unreachable hosts don't each cost a timeout.
    foreach ($targetIp in $targets) {
        $socket = [Net.WebSockets.ClientWebSocket]::new()
        $socket.Options.Proxy = $null
        $connectTimeout = [Threading.CancellationTokenSource]::new($TimeoutMs)
        $probe = [pscustomobject]@{
            Ip = $targetIp
            Socket = $socket
            Timeout = $connectTimeout
            Task = $null
        }
        $pending += $probe
        $probe.Task = $socket.ConnectAsync(
            [Uri]"ws://${targetIp}:$Port/stem", $connectTimeout.Token)
    }

    foreach ($probe in $pending) {
        $identifyTimeout = $null
        $body = $null
        $stage = 'WebSocket handshake'
        try {
            $probe.Task.GetAwaiter().GetResult() | Out-Null
            $probe.Timeout.Dispose()
            $stage = 'identify request/response'
            $identifyTimeout = [Threading.CancellationTokenSource]::new($TimeoutMs)
            $payload = [Text.Encoding]::UTF8.GetBytes('{"action":"identify"}')
            $probe.Socket.SendAsync(
                [ArraySegment[byte]]::new($payload),
                [Net.WebSockets.WebSocketMessageType]::Text,
                $true, $identifyTimeout.Token).GetAwaiter().GetResult() | Out-Null

            $buffer = [byte[]]::new(4096)
            $body = [IO.MemoryStream]::new()
            do {
                $frame = $probe.Socket.ReceiveAsync(
                    [ArraySegment[byte]]::new($buffer),
                    $identifyTimeout.Token).GetAwaiter().GetResult()
                if ($frame.MessageType -ne [Net.WebSockets.WebSocketMessageType]::Text) {
                    throw 'Expected a JSON text response; received binary or close frame.'
                }
                $body.Write($buffer, 0, $frame.Count)
                if ($body.Length -gt 65536) {
                    throw 'Identify response exceeds 64 KiB.'
                }
            } until ($frame.EndOfMessage)

            $reply = [Text.Encoding]::UTF8.GetString($body.ToArray()) | ConvertFrom-Json
            if ($reply.action -ne 'identify_response' -or
                $reply.uuid -isnot [string] -or [string]::IsNullOrWhiteSpace($reply.uuid) -or
                $reply.deviceName -isnot [string] -or [string]::IsNullOrWhiteSpace($reply.deviceName)) {
                throw 'Response does not match identify_response / uuid / deviceName.'
            }
            $found += [pscustomobject]@{
                IP = $probe.Ip
                Port = $Port
                UUID = $reply.uuid
                DeviceName = $reply.deviceName
            }
            Write-Host "[FOUND] $($probe.Ip):$Port | $($reply.uuid) | $($reply.deviceName)" -ForegroundColor Green

            # A normal close avoids an abnormal-disconnect warning on the Pi.
            try {
                $probe.Socket.CloseOutputAsync(
                    [Net.WebSockets.WebSocketCloseStatus]::NormalClosure,
                    'Identify test complete', $identifyTimeout.Token).GetAwaiter().GetResult() | Out-Null
            } catch {
                Write-Verbose "Identify succeeded; close failed: $($_.Exception.GetBaseException().Message)"
            }
        } catch {
            $detail = "$($probe.Ip):$Port | $stage | $($_.Exception.GetBaseException().Message)"
            if ($targets.Count -eq 1) {
                Write-Host "[FAILED] $detail" -ForegroundColor Yellow
            } else {
                Write-Verbose $detail
            }
        } finally {
            if ($null -ne $body) { $body.Dispose() }
            if ($null -ne $identifyTimeout) { $identifyTimeout.Dispose() }
            $probe.Socket.Dispose()
            $probe.Timeout.Dispose()
        }
    }
} finally {
    foreach ($probe in $pending) {
        $probe.Socket.Dispose()
        $probe.Timeout.Dispose()
    }
}

Write-Host "Finished: $($targets.Count) IP(s), $($found.Count) robot(s), $($timer.Elapsed.TotalSeconds.ToString('F1'))s"
if ($found.Count -eq 0) {
    Write-Host 'No robot found. Keep the Pi receiver running; try -Ip <PI_IP> for details.'
    exit 1
}
$found | Format-Table -AutoSize
exit 0
