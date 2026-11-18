$ErrorActionPreference = 'Stop'
$repository = Split-Path (Split-Path $PSScriptRoot -Parent) -Parent
$runRoot = Join-Path $repository '.local-run/rag-long-run'
$budget = Get-Content -LiteralPath (Join-Path $repository 'docs/development/long-run/BUDGET.json') -Raw | ConvertFrom-Json
if ($budget.provider_requests_reserved -ne 0) { throw 'Do not retire runtimes during provider calls' }
$processes = @(Get-CimInstance Win32_Process)
$records = @()
$keep = @('runtime-20261116-23', 'runtime-20261116-25', 'runtime-20261116-26')
foreach ($directory in Get-ChildItem -LiteralPath $runRoot -Directory) {
    if ($directory.Name -notmatch '^runtime-202611(15|16)-\d+$' -or $directory.Name -in $keep) { continue }
    $registration = Join-Path $directory.FullName 'processes.json'
    if (-not (Test-Path -LiteralPath $registration)) { continue }
    $entries = Get-Content -LiteralPath $registration -Raw | ConvertFrom-Json
    foreach ($component in @('backend', 'worker')) {
        $entry = $entries.$component
        if (-not $entry) { continue }
        $owner = @($processes | Where-Object ProcessId -eq $entry.pid)
        if ($owner.Count -ne 1) { continue }
        $command = $owner[0].CommandLine
        $expectedCwd = [string]$entry.cwd
        if (-not $command.Contains($expectedCwd)) { continue }
        if ($component -eq 'backend') {
            $portIndex = [Array]::IndexOf($entry.command, '--port')
            if ($portIndex -lt 0 -or -not $command.Contains('--port ' + $entry.command[$portIndex + 1])) { continue }
        } else {
            $hostname = @($entry.command | Where-Object { $_ -like '--hostname=rag-p0@review-*' })
            if ($hostname.Count -ne 1 -or -not $command.Contains($hostname[0])) { continue }
        }
        $owned = @([int]$entry.pid)
        $frontier = @([int]$entry.pid)
        while ($frontier.Count) {
            $children = @($processes | Where-Object { $_.ParentProcessId -in $frontier } | ForEach-Object { [int]$_.ProcessId })
            $owned += $children
            $frontier = $children
        }
        [Array]::Reverse($owned)
        foreach ($processId in $owned) { Stop-Process -Id $processId -ErrorAction SilentlyContinue }
        $records += [pscustomobject]@{ runtime=$directory.Name; component=$component; process_ids=$owned }
    }
}
$report = Join-Path $runRoot 'round-20261116-26-retired-processes.json'
if (Test-Path -LiteralPath $report) { throw 'Preserve previous retirement report' }
$records | ConvertTo-Json -Depth 5 | Set-Content -LiteralPath $report -Encoding utf8
[pscustomobject]@{ retired_components=$records.Count; kept_runtimes=$keep; data_deleted=$false } | ConvertTo-Json
