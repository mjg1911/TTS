param([string]$PayloadRoot = "build/kokoro-payload")
$ErrorActionPreference = "Stop"
$payload = (Resolve-Path $PayloadRoot).Path
$worker = Join-Path $payload "worker/KokoroWorker.exe"
$smokeText = "Kokoro smoke test."

function Write-Frame($stream, $message) {
    $json = $message | ConvertTo-Json -Compress -Depth 8
    [byte[]]$body = [Text.Encoding]::UTF8.GetBytes($json)
    [byte[]]$header = [BitConverter]::GetBytes([uint32]$body.Length)
    if ([BitConverter]::IsLittleEndian) { [Array]::Reverse($header) }
    $stream.Write($header, 0, $header.Length)
    $stream.Write($body, 0, $body.Length)
    $stream.Flush()
}

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

$start = New-Object Diagnostics.ProcessStartInfo
$start.FileName = $worker
$start.WorkingDirectory = Join-Path $payload "worker"
$start.UseShellExecute = $false
$start.CreateNoWindow = $true
$start.RedirectStandardInput = $true
$start.RedirectStandardOutput = $true
$start.RedirectStandardError = $true
$process = New-Object Diagnostics.Process
$process.StartInfo = $start
if (-not $process.Start()) { throw "KokoroWorker did not start" }
try {
    $input = $process.StandardInput.BaseStream
    $output = $process.StandardOutput.BaseStream
    $hello = Read-Frame $output
    if ($hello.type -ne "hello" -or $hello.protocol_version -ne 1) {
        throw "KokoroWorker handshake mismatch"
    }
    $manifestHash = (Get-FileHash (Join-Path $payload "manifest.json") -Algorithm SHA256).Hash.ToLowerInvariant()
    Write-Frame $input @{ type = "initialize"; manifest_sha256 = $manifestHash }
    $ready = Read-Frame $output
    if ($ready.type -ne "ready") { throw "KokoroWorker did not become ready" }
    Write-Frame $input @{ type = "synthesize"; request_id = 1; text = $smokeText; voice_id = "af_heart" }
    $audioFrames = 0
    while ($true) {
        $message = Read-Frame $output
        if ($message.type -eq "audio") {
            [byte[]]$pcm = [Convert]::FromBase64String($message.audio)
            if ($pcm.Length -eq 0 -or ($pcm.Length % 2) -ne 0) { throw "invalid PCM frame" }
            $audioFrames += 1
        } elseif ($message.type -eq "response_end") {
            break
        } elseif ($message.type -eq "response_error") {
            throw "Kokoro smoke synthesis failed: $($message.category)"
        }
    }
    if ($audioFrames -lt 1) { throw "Kokoro smoke produced no audio" }
    Write-Frame $input @{ type = "shutdown" }
    $process.StandardInput.Close()
    if (-not $process.WaitForExit(30000)) {
        $process.Kill()
        throw "KokoroWorker did not exit after shutdown"
    }
    $diagnostics = $process.StandardError.ReadToEnd()
    if ($diagnostics.Contains($smokeText)) { throw "Kokoro diagnostics leaked source text" }
    if ($process.ExitCode -ne 0) { throw "KokoroWorker exited with $($process.ExitCode)" }
} finally {
    if (-not $process.HasExited) { $process.Kill() }
    $process.Dispose()
}
