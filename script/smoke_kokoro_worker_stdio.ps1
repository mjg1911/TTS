param([Parameter(Mandatory=$true)][string]$WorkerExe)
$ErrorActionPreference = "Stop"

function Read-Exact($stream, [int]$count) {
    [byte[]]$buffer = New-Object byte[] $count
    $offset = 0
    while ($offset -lt $count) {
        $read = $stream.Read($buffer, $offset, $count - $offset)
        if ($read -le 0) { throw "Kokoro protocol stream closed" }
        $offset += $read
    }
    return $buffer
}

function Read-Frame($stream) {
    [byte[]]$header = Read-Exact $stream 4
    if ([BitConverter]::IsLittleEndian) { [Array]::Reverse($header) }
    $length = [BitConverter]::ToUInt32($header, 0)
    if ($length -gt 4194304) { throw "Kokoro frame exceeded 4 MiB" }
    [byte[]]$body = Read-Exact $stream ([int]$length)
    return ([Text.Encoding]::UTF8.GetString($body) | ConvertFrom-Json)
}

function Write-Frame($stream, $message) {
    [byte[]]$body = [Text.Encoding]::UTF8.GetBytes(
        ($message | ConvertTo-Json -Compress -Depth 4)
    )
    [byte[]]$header = [BitConverter]::GetBytes([uint32]$body.Length)
    if ([BitConverter]::IsLittleEndian) { [Array]::Reverse($header) }
    $stream.Write($header, 0, 4)
    $stream.Write($body, 0, $body.Length)
    $stream.Flush()
}

$start = New-Object Diagnostics.ProcessStartInfo
$start.FileName = (Resolve-Path $WorkerExe).Path
$start.UseShellExecute = $false
$start.CreateNoWindow = $true
$start.RedirectStandardInput = $true
$start.RedirectStandardOutput = $true
$start.RedirectStandardError = $true
$process = New-Object Diagnostics.Process
$process.StartInfo = $start
if (-not $process.Start()) { throw "KokoroWorker did not start" }
try {
    $hello = Read-Frame $process.StandardOutput.BaseStream
    if ($hello.type -ne "hello" -or $hello.protocol_version -ne 1) {
        throw "KokoroWorker stdio handshake mismatch"
    }
    Write-Frame $process.StandardInput.BaseStream @{type="shutdown"}
    $process.StandardInput.Close()
    if (-not $process.WaitForExit(10000)) {
        $process.Kill()
        throw "KokoroWorker did not exit after stdio smoke"
    }
    if ($process.ExitCode -ne 0) { throw "KokoroWorker exited with $($process.ExitCode)" }
} finally {
    if (-not $process.HasExited) { $process.Kill() }
    $process.Dispose()
}
