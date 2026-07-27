[CmdletBinding()]
param(
    [Parameter(Position = 0)]
    [ValidateSet("start", "stop", "restart", "status")]
    [string]$Action = "status",

    [int]$BackendPort = 0,
    [int]$FrontendPort = 3000,
    [string]$DatabaseFile = "local_development.db"
)

Set-StrictMode -Version Latest
$ErrorActionPreference = "Stop"

$repoRoot = Split-Path -Parent $PSScriptRoot
$backendRoot = Join-Path $repoRoot "backend"
$frontendRoot = Join-Path $repoRoot "frontend"
$runtimeRoot = Join-Path $repoRoot ".local-run"
$logRoot = Join-Path $runtimeRoot "logs"
$statePath = Join-Path $runtimeRoot "processes.json"
$backendPython = Join-Path $backendRoot ".venv\Scripts\python.exe"

function Get-ConfiguredBackendPort {
    if ($BackendPort -gt 0) {
        return $BackendPort
    }

    $frontendEnvironment = Join-Path $frontendRoot ".env.local"
    if (Test-Path -LiteralPath $frontendEnvironment) {
        $apiBaseLine = Get-Content -LiteralPath $frontendEnvironment |
            Where-Object { $_ -match "^\s*NEXT_PUBLIC_API_BASE_URL\s*=" } |
            Select-Object -First 1
        if ($apiBaseLine -and $apiBaseLine -match "https?://(?:localhost|127\.0\.0\.1):(\d+)(?:/|$)") {
            return [int]$Matches[1]
        }
    }

    return 8000
}

function Get-PortOwner {
    param([int]$Port)

    $connection = Get-NetTCPConnection -State Listen -LocalPort $Port -ErrorAction SilentlyContinue |
        Select-Object -First 1
    if ($null -eq $connection) {
        return $null
    }
    return [int]$connection.OwningProcess
}

function Wait-Endpoint {
    param(
        [string]$Url,
        [int]$TimeoutSeconds = 60
    )

    $deadline = (Get-Date).AddSeconds($TimeoutSeconds)
    while ((Get-Date) -lt $deadline) {
        try {
            $response = Invoke-WebRequest -Uri $Url -UseBasicParsing -TimeoutSec 3
            if ($response.StatusCode -ge 200 -and $response.StatusCode -lt 500) {
                return $true
            }
        } catch {
            # 服务启动期间连接失败属于预期，继续等待。
        }
        Start-Sleep -Seconds 1
    }
    return $false
}

function Assert-LocalPrerequisites {
    if (-not (Test-Path -LiteralPath $backendPython)) {
        throw "缺少 backend\.venv。请先在 backend 目录创建虚拟环境并安装 requirements.txt。"
    }
    if (-not (Test-Path -LiteralPath (Join-Path $frontendRoot "node_modules"))) {
        throw "缺少 frontend\node_modules。请先在 frontend 目录执行 npm ci。"
    }
    if ($null -eq (Get-Command npm.cmd -ErrorAction SilentlyContinue)) {
        throw "找不到 npm.cmd，请先安装 Node.js。"
    }
    if ([IO.Path]::GetFileName($DatabaseFile) -ne $DatabaseFile) {
        throw "DatabaseFile 只能是 backend 目录下的文件名，不能包含路径。"
    }
}

function Set-ProjectEnvironment {
    param([int]$Port)

    $env:DATABASE_URL = "sqlite:///./$DatabaseFile"
    $env:STORAGE_DIR = "./dev_storage_local"
    $env:AUTH_MODE = "optional"
    $env:TASK_QUEUE_PROVIDER = "inline"
    $env:LLM_PROVIDER = "mock"
    $env:EMBEDDING_PROVIDER = "mock"
    $env:VECTOR_STORE_PROVIDER = "mock"
    $env:CORS_ORIGINS = "http://localhost:$FrontendPort,http://127.0.0.1:$FrontendPort"
    $env:LOCAL_BACKEND_PORT = [string]$Port
}

function Start-Project {
    Assert-LocalPrerequisites
    $resolvedBackendPort = Get-ConfiguredBackendPort

    foreach ($port in @($FrontendPort, $resolvedBackendPort)) {
        $owner = Get-PortOwner -Port $port
        if ($null -ne $owner) {
            throw "端口 $port 已被 PID $owner 占用。为避免误停其他程序，请先释放该端口。"
        }
    }

    New-Item -ItemType Directory -Path $logRoot -Force | Out-Null
    $timestamp = Get-Date -Format "yyyyMMdd-HHmmss"
    $backendOut = Join-Path $logRoot "backend-$timestamp.stdout.log"
    $backendErr = Join-Path $logRoot "backend-$timestamp.stderr.log"
    $frontendOut = Join-Path $logRoot "frontend-$timestamp.stdout.log"
    $frontendErr = Join-Path $logRoot "frontend-$timestamp.stderr.log"

    $environmentNames = @(
        "DATABASE_URL",
        "STORAGE_DIR",
        "AUTH_MODE",
        "TASK_QUEUE_PROVIDER",
        "LLM_PROVIDER",
        "EMBEDDING_PROVIDER",
        "VECTOR_STORE_PROVIDER",
        "CORS_ORIGINS",
        "LOCAL_BACKEND_PORT"
    )
    $previousEnvironment = @{}
    foreach ($name in $environmentNames) {
        $previousEnvironment[$name] = [Environment]::GetEnvironmentVariable($name, "Process")
    }

    $backendStarter = $null
    $frontendStarter = $null
    try {
        Set-ProjectEnvironment -Port $resolvedBackendPort

        Write-Host "正在执行数据库迁移..."
        Push-Location $backendRoot
        try {
            & $backendPython -m alembic upgrade head
        } finally {
            Pop-Location
        }
        if ($LASTEXITCODE -ne 0) {
            throw "数据库迁移失败，退出码：$LASTEXITCODE"
        }

        $backendStarter = Start-Process `
            -FilePath $backendPython `
            -ArgumentList @("-m", "uvicorn", "app.main:app", "--host", "127.0.0.1", "--port", [string]$resolvedBackendPort) `
            -WorkingDirectory $backendRoot `
            -RedirectStandardOutput $backendOut `
            -RedirectStandardError $backendErr `
            -WindowStyle Hidden `
            -PassThru

        $frontendStarter = Start-Process `
            -FilePath (Get-Command npm.cmd).Source `
            -ArgumentList @("run", "dev", "--", "-p", [string]$FrontendPort) `
            -WorkingDirectory $frontendRoot `
            -RedirectStandardOutput $frontendOut `
            -RedirectStandardError $frontendErr `
            -WindowStyle Hidden `
            -PassThru

        if (-not (Wait-Endpoint -Url "http://127.0.0.1:$resolvedBackendPort/health/ready")) {
            throw "后端在 60 秒内未就绪，请检查日志：$backendErr"
        }
        if (-not (Wait-Endpoint -Url "http://127.0.0.1:$FrontendPort/")) {
            throw "前端在 60 秒内未就绪，请检查日志：$frontendErr"
        }

        $backendOwner = Get-PortOwner -Port $resolvedBackendPort
        $frontendOwner = Get-PortOwner -Port $FrontendPort
        if ($null -eq $backendOwner -or $null -eq $frontendOwner) {
            throw "服务已响应，但无法确认监听进程。"
        }
        $backendOwnerProcess = Get-CimInstance Win32_Process -Filter "ProcessId = $backendOwner"

        [PSCustomObject]@{
            startedAt = (Get-Date).ToString("o")
            backendPort = $resolvedBackendPort
            backendPid = $backendOwner
            backendExecutable = $backendOwnerProcess.ExecutablePath
            backendCommandLine = $backendOwnerProcess.CommandLine
            frontendPort = $FrontendPort
            frontendPid = $frontendOwner
            frontendRoot = $frontendRoot
            databaseFile = $DatabaseFile
            backendLog = $backendErr
            frontendLog = $frontendErr
        } | ConvertTo-Json | Set-Content -LiteralPath $statePath -Encoding UTF8

        Write-Host "项目启动成功。"
        Write-Host "前端：http://localhost:$FrontendPort"
        Write-Host "后端：http://localhost:$resolvedBackendPort/docs"
        Write-Host "日志目录：$logRoot"
    } catch {
        foreach ($process in @($frontendStarter, $backendStarter)) {
            if ($null -ne $process -and -not $process.HasExited) {
                Stop-Process -Id $process.Id -Force -ErrorAction SilentlyContinue
            }
        }
        $frontendOwner = Get-PortOwner -Port $FrontendPort
        if ($null -ne $frontendOwner) {
            $temporaryState = [PSCustomObject]@{ frontendRoot = $frontendRoot }
            if (Test-ManagedOwner -ProcessId $frontendOwner -Service "frontend" -State $temporaryState) {
                Stop-Process -Id $frontendOwner -Force -ErrorAction SilentlyContinue
            }
        }
        throw
    } finally {
        foreach ($name in $environmentNames) {
            [Environment]::SetEnvironmentVariable($name, $previousEnvironment[$name], "Process")
        }
    }
}

function Test-ManagedOwner {
    param(
        [int]$ProcessId,
        [string]$Service,
        [object]$State
    )

    $process = Get-CimInstance Win32_Process -Filter "ProcessId = $ProcessId" -ErrorAction SilentlyContinue
    if ($null -eq $process) {
        return $false
    }
    if ($Service -eq "backend") {
        return (
            $process.ExecutablePath -eq [string]$State.backendExecutable -and
            $process.CommandLine -like "*uvicorn*" -and
            $process.CommandLine -like "*--port $([int]$State.backendPort)*"
        )
    }
    return $process.CommandLine -like "*next*" -and $process.CommandLine -like "*$([string]$State.frontendRoot)*"
}

function Stop-Project {
    if (-not (Test-Path -LiteralPath $statePath)) {
        Write-Host "没有找到由启停脚本创建的运行状态，未停止任何进程。"
        return
    }

    $state = Get-Content -Raw -LiteralPath $statePath | ConvertFrom-Json
    $services = @(
        [PSCustomObject]@{ Name = "frontend"; Port = [int]$state.frontendPort; Pid = [int]$state.frontendPid },
        [PSCustomObject]@{ Name = "backend"; Port = [int]$state.backendPort; Pid = [int]$state.backendPid }
    )
    $unresolvedServices = @()

    foreach ($service in $services) {
        $owner = Get-PortOwner -Port $service.Port
        if ($null -eq $owner) {
            Write-Host "$($service.Name) 已停止（端口 $($service.Port) 未监听）。"
            continue
        }
        if ($owner -ne $service.Pid -and -not (Test-ManagedOwner -ProcessId $owner -Service $service.Name -State $state)) {
            Write-Warning "端口 $($service.Port) 当前由 PID $owner 占用，无法确认是本项目进程，已跳过。"
            $unresolvedServices += $service.Name
            continue
        }
        if (-not (Test-ManagedOwner -ProcessId $owner -Service $service.Name -State $state)) {
            Write-Warning "PID $owner 与已记录的本项目进程不匹配，已跳过。"
            $unresolvedServices += $service.Name
            continue
        }
        Stop-Process -Id $owner -Force
        Write-Host "$($service.Name) 已停止（PID $owner）。"
    }

    if ($unresolvedServices.Count -gt 0) {
        throw "以下服务未能确认归属，运行状态已保留：$($unresolvedServices -join ', ')"
    }
    Remove-Item -LiteralPath $statePath -Force
}

function Show-ProjectStatus {
    $resolvedBackendPort = Get-ConfiguredBackendPort
    $frontendOwner = Get-PortOwner -Port $FrontendPort
    $backendOwner = Get-PortOwner -Port $resolvedBackendPort

    Write-Host "前端端口 $FrontendPort：" -NoNewline
    if ($null -eq $frontendOwner) { Write-Host "未运行" } else { Write-Host "运行中（PID $frontendOwner）" }
    Write-Host "后端端口 $resolvedBackendPort：" -NoNewline
    if ($null -eq $backendOwner) { Write-Host "未运行" } else { Write-Host "运行中（PID $backendOwner）" }

    if (Test-Path -LiteralPath $statePath) {
        $state = Get-Content -Raw -LiteralPath $statePath | ConvertFrom-Json
        Write-Host "启动时间：$($state.startedAt)"
        Write-Host "数据库：backend\$($state.databaseFile)"
        Write-Host "日志目录：$logRoot"
    } else {
        Write-Host "当前没有启停脚本管理的运行状态。"
    }
}

try {
    switch ($Action) {
        "start" { Start-Project }
        "stop" { Stop-Project }
        "restart" {
            if (-not $PSBoundParameters.ContainsKey("DatabaseFile") -and (Test-Path -LiteralPath $statePath)) {
                $restartState = Get-Content -Raw -LiteralPath $statePath | ConvertFrom-Json
                $DatabaseFile = [string]$restartState.databaseFile
            }
            Stop-Project
            Start-Project
        }
        "status" { Show-ProjectStatus }
    }
} catch {
    Write-Error $_
    exit 1
}
