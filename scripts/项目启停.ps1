[CmdletBinding()]
param(
    [Parameter(Position = 0)]
    [ValidateSet("start", "stop", "restart", "status")]
    [string]$Action = "status",

    [ValidateSet("production", "sqlite")]
    [string]$Mode = "production",

    [int]$BackendPort = 0,
    [int]$FrontendPort = 3000,
    [int]$PostgresPort = 5432,
    [int]$RedisPort = 6379,
    [string]$DatabaseName = "ybt_local",
    [string]$DatabaseUser = "ybt_app",
    [string]$DatabaseFile = "local_main_test.db",
    [switch]$SkipDataMigration
)

Set-StrictMode -Version Latest
$ErrorActionPreference = "Stop"

$repoRoot = Split-Path -Parent $PSScriptRoot
$backendRoot = Join-Path $repoRoot "backend"
$frontendRoot = Join-Path $repoRoot "frontend"
$runtimeRoot = Join-Path $repoRoot ".local-run"
$logRoot = Join-Path $runtimeRoot "logs"
$statePath = Join-Path $runtimeRoot "processes.json"
$secretsPath = Join-Path $runtimeRoot "local-secrets.json"
$pgPassPath = Join-Path $runtimeRoot "postgres.pgpass"
$postgresDataRoot = Join-Path $runtimeRoot "postgres-data"
$redisDataRoot = Join-Path $runtimeRoot "redis-data"
$backendPython = Join-Path $backendRoot ".venv\Scripts\python.exe"
$migrationScript = Join-Path $PSScriptRoot "迁移SQLite到PostgreSQL.py"

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

function Wait-Port {
    param([int]$Port, [int]$TimeoutSeconds = 30)
    $deadline = (Get-Date).AddSeconds($TimeoutSeconds)
    while ((Get-Date) -lt $deadline) {
        $client = New-Object Net.Sockets.TcpClient
        try {
            $async = $client.BeginConnect("127.0.0.1", $Port, $null, $null)
            if ($async.AsyncWaitHandle.WaitOne(500) -and $client.Connected) {
                return $true
            }
        } catch {
            # 服务启动期间连接失败属于预期。
        } finally {
            $client.Dispose()
        }
        Start-Sleep -Milliseconds 500
    }
    return $false
}

function Wait-Endpoint {
    param([string]$Url, [int]$TimeoutSeconds = 90)
    $deadline = (Get-Date).AddSeconds($TimeoutSeconds)
    while ((Get-Date) -lt $deadline) {
        try {
            $response = Invoke-WebRequest -Uri $Url -UseBasicParsing -TimeoutSec 3
            if ($response.StatusCode -ge 200 -and $response.StatusCode -lt 500) {
                return $true
            }
        } catch {
            # 服务启动期间连接失败属于预期。
        }
        Start-Sleep -Seconds 1
    }
    return $false
}

function Resolve-Executable {
    param([string]$Name, [string[]]$Fallbacks)
    $command = Get-Command $Name -ErrorAction SilentlyContinue
    if ($null -ne $command) {
        return $command.Source
    }
    foreach ($candidate in $Fallbacks) {
        if (Test-Path -LiteralPath $candidate) {
            return $candidate
        }
    }
    throw "找不到 $Name。请先安装对应的本地依赖。"
}

function Assert-SafeIdentifier {
    param([string]$Value, [string]$Label)
    if ($Value -notmatch "^[a-z][a-z0-9_]{2,62}$") {
        throw "$Label 只能使用小写字母、数字和下划线，并以字母开头。"
    }
}

function Protect-LocalSecretFile {
    param([string]$Path)
    $identity = [System.Security.Principal.WindowsIdentity]::GetCurrent().Name
    & icacls.exe $Path "/reset" | Out-Null
    if ($LASTEXITCODE -ne 0) {
        throw "无法重置本机凭据文件权限：$Path"
    }
    & icacls.exe $Path "/inheritance:r" "/grant:r" "${identity}:(F)" | Out-Null
    if ($LASTEXITCODE -ne 0) {
        throw "无法限制本机凭据文件权限：$Path"
    }
    $acl = Get-Acl -LiteralPath $Path
    $unexpectedRules = @($acl.Access | Where-Object {
        $_.IdentityReference.Value -ne $identity -or
        $_.AccessControlType -ne [System.Security.AccessControl.AccessControlType]::Allow -or
        ($_.FileSystemRights -band [System.Security.AccessControl.FileSystemRights]::FullControl) -ne
            [System.Security.AccessControl.FileSystemRights]::FullControl
    })
    if (-not $acl.AreAccessRulesProtected -or $acl.Access.Count -ne 1 -or $unexpectedRules.Count -ne 0) {
        throw "本机凭据文件权限校验失败：$Path"
    }
}

function Get-LocalSecrets {
    New-Item -ItemType Directory -Path $runtimeRoot -Force | Out-Null
    if (Test-Path -LiteralPath $secretsPath) {
        Protect-LocalSecretFile -Path $secretsPath
        return Get-Content -Raw -LiteralPath $secretsPath | ConvertFrom-Json
    }
    $secrets = [PSCustomObject]@{
        postgresSuperPassword = ([guid]::NewGuid().ToString("N") + [guid]::NewGuid().ToString("N"))
        databasePassword = ([guid]::NewGuid().ToString("N") + [guid]::NewGuid().ToString("N"))
    }
    $secrets | ConvertTo-Json | Set-Content -LiteralPath $secretsPath -Encoding UTF8
    Protect-LocalSecretFile -Path $secretsPath
    return $secrets
}

function Write-PostgresPassFile {
    param([object]$Secrets)
    @(
        "127.0.0.1`:$PostgresPort`:*`:postgres`:$([string]$Secrets.postgresSuperPassword)",
        "127.0.0.1`:$PostgresPort`:$DatabaseName`:$DatabaseUser`:$([string]$Secrets.databasePassword)"
    ) | Set-Content -LiteralPath $pgPassPath -Encoding ASCII
    Protect-LocalSecretFile -Path $pgPassPath
}

function Get-PostgresTools {
    $scoopRoot = Join-Path $env:USERPROFILE "scoop\apps\postgresql\current\bin"
    return [PSCustomObject]@{
        postgres = Resolve-Executable "postgres.exe" @((Join-Path $scoopRoot "postgres.exe"))
        pgCtl = Resolve-Executable "pg_ctl.exe" @((Join-Path $scoopRoot "pg_ctl.exe"))
        initdb = Resolve-Executable "initdb.exe" @((Join-Path $scoopRoot "initdb.exe"))
        psql = Resolve-Executable "psql.exe" @((Join-Path $scoopRoot "psql.exe"))
        createdb = Resolve-Executable "createdb.exe" @((Join-Path $scoopRoot "createdb.exe"))
    }
}

function Get-RedisExecutable {
    $scoopPath = Join-Path $env:USERPROFILE "scoop\apps\redis\current\redis-server.exe"
    return Resolve-Executable "redis-server.exe" @($scoopPath)
}

function Initialize-Postgres {
    param([object]$Tools, [object]$Secrets)
    if (Test-Path -LiteralPath (Join-Path $postgresDataRoot "PG_VERSION")) {
        return
    }
    New-Item -ItemType Directory -Path $postgresDataRoot -Force | Out-Null
    $passwordFile = Join-Path $runtimeRoot "postgres-init-password.txt"
    Set-Content -LiteralPath $passwordFile -Value ([string]$Secrets.postgresSuperPassword) -Encoding ASCII
    Protect-LocalSecretFile -Path $passwordFile
    try {
        & $Tools.initdb `
            "-D" $postgresDataRoot `
            "-U" "postgres" `
            "--encoding=UTF8" `
            "--locale=C" `
            "--auth-local=scram-sha-256" `
            "--auth-host=scram-sha-256" `
            "--pwfile=$passwordFile"
        if ($LASTEXITCODE -ne 0) {
            throw "PostgreSQL 数据目录初始化失败，退出码：$LASTEXITCODE"
        }
    } finally {
        Remove-Item -LiteralPath $passwordFile -Force -ErrorAction SilentlyContinue
    }
}

function Start-Postgres {
    param([object]$Tools, [object]$Secrets, [string]$LogPath)
    Initialize-Postgres -Tools $Tools -Secrets $Secrets
    & $Tools.pgCtl `
        "-D" $postgresDataRoot `
        "-l" $LogPath `
        "-o" "-p $PostgresPort -h 127.0.0.1" `
        "-w" "start"
    if ($LASTEXITCODE -ne 0 -or -not (Wait-Port -Port $PostgresPort)) {
        throw "PostgreSQL 未能启动，请检查日志：$LogPath"
    }
}

function Initialize-PostgresApplicationDatabase {
    param([object]$Tools, [object]$Secrets)
    Assert-SafeIdentifier -Value $DatabaseName -Label "数据库名"
    Assert-SafeIdentifier -Value $DatabaseUser -Label "数据库用户"
    $roleSql = @'
DO $block$
BEGIN
    IF EXISTS (SELECT 1 FROM pg_roles WHERE rolname = '__DATABASE_USER__') THEN
        ALTER ROLE __DATABASE_USER__ WITH LOGIN PASSWORD '__DATABASE_PASSWORD__';
    ELSE
        CREATE ROLE __DATABASE_USER__ WITH LOGIN PASSWORD '__DATABASE_PASSWORD__';
    END IF;
END
$block$;
'@
    $roleSql = $roleSql.Replace("__DATABASE_USER__", $DatabaseUser).
        Replace("__DATABASE_PASSWORD__", [string]$Secrets.databasePassword)
    & $Tools.psql `
        "-h" "127.0.0.1" `
        "-p" ([string]$PostgresPort) `
        "-U" "postgres" `
        "-d" "postgres" `
        "-v" "ON_ERROR_STOP=1" `
        "-c" $roleSql | Out-Null
    if ($LASTEXITCODE -ne 0) {
        throw "PostgreSQL 应用用户初始化失败。"
    }
    $exists = & $Tools.psql `
        "-h" "127.0.0.1" `
        "-p" ([string]$PostgresPort) `
        "-U" "postgres" `
        "-d" "postgres" `
        "-tAc" "SELECT 1 FROM pg_database WHERE datname = '$DatabaseName'"
    if (($exists | Out-String).Trim() -ne "1") {
        & $Tools.createdb `
            "-h" "127.0.0.1" `
            "-p" ([string]$PostgresPort) `
            "-U" "postgres" `
            "-O" $DatabaseUser `
            $DatabaseName
        if ($LASTEXITCODE -ne 0) {
            throw "PostgreSQL 应用数据库创建失败。"
        }
        return $true
    }
    return $false
}

function Start-Redis {
    param([string]$Executable, [string]$OutLog, [string]$ErrorLog)
    New-Item -ItemType Directory -Path $redisDataRoot -Force | Out-Null
    $process = Start-Process `
        -FilePath $Executable `
        -ArgumentList @(
            "--bind", "127.0.0.1",
            "--port", [string]$RedisPort,
            "--protected-mode", "yes",
            "--dir", $redisDataRoot,
            "--dbfilename", "dump.rdb",
            "--appendonly", "yes"
        ) `
        -WorkingDirectory $runtimeRoot `
        -RedirectStandardOutput $OutLog `
        -RedirectStandardError $ErrorLog `
        -WindowStyle Hidden `
        -PassThru
    if (-not (Wait-Port -Port $RedisPort)) {
        if (-not $process.HasExited) {
            Stop-Process -Id $process.Id -Force -ErrorAction SilentlyContinue
        }
        throw "Redis 未能启动，请检查日志：$ErrorLog"
    }
    return $process
}

function Assert-LocalPrerequisites {
    if (-not (Test-Path -LiteralPath $backendPython)) {
        throw "缺少 backend\.venv。请先创建虚拟环境并安装 requirements.txt。"
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
    if ($Mode -eq "production" -and -not (Test-Path -LiteralPath $migrationScript)) {
        throw "缺少 SQLite 到 PostgreSQL 的迁移脚本。"
    }
}

function Set-ProjectEnvironment {
    param([int]$Port, [string]$DatabaseUrl)
    $env:DATABASE_URL = $DatabaseUrl
    $env:STORAGE_DIR = "./dev_storage_local"
    $env:AUTH_MODE = "optional"
    $env:LLM_PROVIDER = "mock"
    $env:EMBEDDING_PROVIDER = "mock"
    $env:VECTOR_STORE_PROVIDER = "mock"
    $env:CORS_ORIGINS = "http://localhost:$FrontendPort,http://127.0.0.1:$FrontendPort"
    $env:LOCAL_BACKEND_PORT = [string]$Port
    $env:KNOWLEDGE_INGESTION_BATCH_SIZE = "200"
    if ($Mode -eq "production") {
        $env:TASK_QUEUE_PROVIDER = "celery"
        $env:REDIS_URL = "redis://127.0.0.1:$RedisPort/0"
        $env:CELERY_BROKER_URL = "redis://127.0.0.1:$RedisPort/0"
        $env:CELERY_RESULT_BACKEND = "redis://127.0.0.1:$RedisPort/1"
    } else {
        $env:TASK_QUEUE_PROVIDER = "inline"
        $env:REDIS_URL = ""
        $env:CELERY_BROKER_URL = ""
        $env:CELERY_RESULT_BACKEND = ""
    }
}

function Invoke-DatabaseMigration {
    Write-Host "正在执行 Alembic 数据库迁移..."
    Push-Location $backendRoot
    try {
        & $backendPython -m alembic upgrade head
    } finally {
        Pop-Location
    }
    if ($LASTEXITCODE -ne 0) {
        throw "数据库迁移失败，退出码：$LASTEXITCODE"
    }
}

function Get-PostgresProjectCount {
    $result = & $backendPython -c "from sqlalchemy import create_engine,text; import os; e=create_engine(os.environ['DATABASE_URL']); print(e.connect().scalar(text('select count(*) from projects')))"
    if ($LASTEXITCODE -ne 0) {
        throw "无法检查 PostgreSQL 数据状态。"
    }
    return [int](($result | Select-Object -Last 1).Trim())
}

function Get-SqliteProjectCount {
    param([string]$Source)
    $result = & $backendPython -c "import sqlite3,sys; c=sqlite3.connect(sys.argv[1]); print(c.execute('select count(*) from projects').fetchone()[0]); c.close()" $Source
    if ($LASTEXITCODE -ne 0) {
        throw "无法检查 SQLite 数据状态。"
    }
    return [int](($result | Select-Object -Last 1).Trim())
}

function Get-PostgresProtectedDataTables {
    $result = & $backendPython $migrationScript "--inspect-target"
    if ($LASTEXITCODE -ne 0) {
        throw "无法检查 PostgreSQL 业务表状态。"
    }
    return @(($result | Select-Object -Last 1 | ConvertFrom-Json))
}

function Invoke-SqliteDataMigration {
    param([bool]$DatabaseCreatedNow)
    if ($SkipDataMigration) {
        return
    }
    $source = Join-Path $backendRoot $DatabaseFile
    if (-not (Test-Path -LiteralPath $source)) {
        Write-Host "未找到 backend\$DatabaseFile，跳过历史数据迁移。"
        return
    }
    $safeDatabaseFile = $DatabaseFile -replace "[^a-zA-Z0-9._-]", "_"
    $migrationMarker = Join-Path $runtimeRoot "sqlite-migration-complete-$DatabaseName-$safeDatabaseFile.json"
    $sourceProjectCount = Get-SqliteProjectCount -Source $source
    $targetProjectCount = Get-PostgresProjectCount
    if (Test-Path -LiteralPath $migrationMarker) {
        if ($targetProjectCount -eq $sourceProjectCount) {
            return
        }
        throw "SQLite 迁移标记与 PostgreSQL 项目数不一致。为避免覆盖数据，请先备份并手工核验。"
    }
    if (-not $DatabaseCreatedNow) {
        $protectedTables = Get-PostgresProtectedDataTables
        $detail = if ($protectedTables.Count -gt 0) {
            "；已检测到：$($protectedTables -join ', ')"
        } else {
            ""
        }
        throw "PostgreSQL 不是本次启动新建的专用空库且没有完整迁移标记，禁止自动覆盖$detail。请先备份并手工迁移。"
    }
    Write-Host "正在将 backend\$DatabaseFile 的有效数据迁移到 PostgreSQL..."
    $previousMigrationUrl = [Environment]::GetEnvironmentVariable("MIGRATION_DATABASE_URL", "Process")
    $env:MIGRATION_DATABASE_URL = "postgresql+psycopg://postgres@127.0.0.1`:$PostgresPort/$DatabaseName"
    try {
        & $backendPython $migrationScript `
            "--source" $source `
            "--batch-size" "2000" `
            "--replace-target"
        if ($LASTEXITCODE -ne 0) {
            throw "SQLite 数据迁移到 PostgreSQL 失败，退出码：$LASTEXITCODE"
        }
        [PSCustomObject]@{
            completedAt = (Get-Date).ToString("o")
            source = $source
            sourceLength = (Get-Item -LiteralPath $source).Length
            sourceLastWriteTime = (Get-Item -LiteralPath $source).LastWriteTimeUtc.ToString("o")
            databaseName = $DatabaseName
        } | ConvertTo-Json | Set-Content -LiteralPath $migrationMarker -Encoding UTF8
    } finally {
        [Environment]::SetEnvironmentVariable("MIGRATION_DATABASE_URL", $previousMigrationUrl, "Process")
    }
}

function Test-ManagedOwner {
    param([int]$ProcessId, [string]$Service, [object]$State)
    $process = Get-CimInstance Win32_Process -Filter "ProcessId = $ProcessId" -ErrorAction SilentlyContinue
    if ($null -eq $process) {
        return $false
    }
    switch ($Service) {
        "backend" {
            $starterPid = if ($State.PSObject.Properties.Name -contains "backendStarterPid") {
                [int]$State.backendStarterPid
            } else {
                [int]$process.ParentProcessId
            }
            $starter = Get-CimInstance Win32_Process -Filter "ProcessId = $starterPid" -ErrorAction SilentlyContinue
            return $null -ne $starter -and
                $process.ParentProcessId -eq $starterPid -and
                $process.CommandLine -like "*uvicorn*" -and
                $process.CommandLine -like "*--port $([int]$State.backendPort)*" -and
                $starter.CommandLine -like "*$backendPython*" -and
                $starter.CommandLine -like "*uvicorn*"
        }
        "frontend" {
            return $process.CommandLine -like "*next*" -and
                $process.CommandLine -like "*$([string]$State.frontendRoot)*"
        }
        "worker" {
            return $process.CommandLine -like "*celery*" -and
                $process.CommandLine -like "*app.workers.celery_app*" -and
                $process.CommandLine -like "*$backendPython*"
        }
        "redis" {
            return $process.CommandLine -like "*redis-server*" -and
                $process.CommandLine -like "*$([int]$State.redisPort)*" -and
                $process.CommandLine -like "*$redisDataRoot*"
        }
    }
    return $false
}

function Start-Project {
    Assert-LocalPrerequisites
    $resolvedBackendPort = Get-ConfiguredBackendPort
    $ports = @($FrontendPort, $resolvedBackendPort)
    if ($Mode -eq "production") {
        $ports += @($PostgresPort, $RedisPort)
    }
    foreach ($port in $ports) {
        $owner = Get-PortOwner -Port $port
        if ($null -ne $owner) {
            throw "端口 $port 已被 PID $owner 占用。为避免误停其他程序，请先释放该端口。"
        }
    }

    New-Item -ItemType Directory -Path $logRoot -Force | Out-Null
    $timestamp = Get-Date -Format "yyyyMMdd-HHmmss"
    $logs = [PSCustomObject]@{
        postgres = Join-Path $logRoot "postgres-$timestamp.log"
        redisOut = Join-Path $logRoot "redis-$timestamp.stdout.log"
        redisErr = Join-Path $logRoot "redis-$timestamp.stderr.log"
        workerOut = Join-Path $logRoot "worker-$timestamp.stdout.log"
        workerErr = Join-Path $logRoot "worker-$timestamp.stderr.log"
        backendOut = Join-Path $logRoot "backend-$timestamp.stdout.log"
        backendErr = Join-Path $logRoot "backend-$timestamp.stderr.log"
        frontendOut = Join-Path $logRoot "frontend-$timestamp.stdout.log"
        frontendErr = Join-Path $logRoot "frontend-$timestamp.stderr.log"
    }
    $environmentNames = @(
        "DATABASE_URL", "STORAGE_DIR", "AUTH_MODE", "TASK_QUEUE_PROVIDER",
        "REDIS_URL", "CELERY_BROKER_URL", "CELERY_RESULT_BACKEND",
        "LLM_PROVIDER", "EMBEDDING_PROVIDER", "VECTOR_STORE_PROVIDER",
        "CORS_ORIGINS", "LOCAL_BACKEND_PORT", "KNOWLEDGE_INGESTION_BATCH_SIZE",
        "PGPASSFILE"
    )
    $previousEnvironment = @{}
    foreach ($name in $environmentNames) {
        $previousEnvironment[$name] = [Environment]::GetEnvironmentVariable($name, "Process")
    }

    $postgresTools = $null
    $redisStarter = $null
    $workerStarter = $null
    $backendStarter = $null
    $frontendStarter = $null
    $postgresStarted = $false
    $databaseCreatedNow = $false
    try {
        if ($Mode -eq "production") {
            $postgresTools = Get-PostgresTools
            $secrets = Get-LocalSecrets
            Write-PostgresPassFile -Secrets $secrets
            $env:PGPASSFILE = $pgPassPath
            Start-Postgres -Tools $postgresTools -Secrets $secrets -LogPath $logs.postgres
            $postgresStarted = $true
            $databaseCreatedNow = Initialize-PostgresApplicationDatabase -Tools $postgresTools -Secrets $secrets
            $redisStarter = Start-Redis -Executable (Get-RedisExecutable) -OutLog $logs.redisOut -ErrorLog $logs.redisErr
            $databaseUrl = "postgresql+psycopg://$DatabaseUser@127.0.0.1`:$PostgresPort/$DatabaseName"
        } else {
            $databaseUrl = "sqlite:///./$DatabaseFile"
        }
        Set-ProjectEnvironment -Port $resolvedBackendPort -DatabaseUrl $databaseUrl
        Invoke-DatabaseMigration
        if ($Mode -eq "production") {
            Invoke-SqliteDataMigration -DatabaseCreatedNow $databaseCreatedNow
            $workerStarter = Start-Process `
                -FilePath $backendPython `
                -ArgumentList @(
                    "-m", "celery",
                    "-A", "app.workers.celery_app",
                    "worker",
                    "--loglevel=INFO",
                    "--pool=solo",
                    "--concurrency=1",
                    "--without-gossip",
                    "--without-mingle"
                ) `
                -WorkingDirectory $backendRoot `
                -RedirectStandardOutput $logs.workerOut `
                -RedirectStandardError $logs.workerErr `
                -WindowStyle Hidden `
                -PassThru
        }
        $backendStarter = Start-Process `
            -FilePath $backendPython `
            -ArgumentList @("-m", "uvicorn", "app.main:app", "--host", "127.0.0.1", "--port", [string]$resolvedBackendPort) `
            -WorkingDirectory $backendRoot `
            -RedirectStandardOutput $logs.backendOut `
            -RedirectStandardError $logs.backendErr `
            -WindowStyle Hidden `
            -PassThru
        $frontendStarter = Start-Process `
            -FilePath (Get-Command npm.cmd).Source `
            -ArgumentList @("run", "dev", "--", "-p", [string]$FrontendPort) `
            -WorkingDirectory $frontendRoot `
            -RedirectStandardOutput $logs.frontendOut `
            -RedirectStandardError $logs.frontendErr `
            -WindowStyle Hidden `
            -PassThru

        if (-not (Wait-Endpoint -Url "http://127.0.0.1:$resolvedBackendPort/health/ready")) {
            throw "后端在 90 秒内未就绪，请检查日志：$($logs.backendErr)"
        }
        if (-not (Wait-Endpoint -Url "http://127.0.0.1:$FrontendPort/")) {
            throw "前端在 90 秒内未就绪，请检查日志：$($logs.frontendErr)"
        }

        $backendOwner = Get-PortOwner -Port $resolvedBackendPort
        $frontendOwner = Get-PortOwner -Port $FrontendPort
        if ($null -eq $backendOwner -or $null -eq $frontendOwner) {
            throw "服务已响应，但无法确认监听进程。"
        }
        $state = [PSCustomObject]@{
            startedAt = (Get-Date).ToString("o")
            mode = $Mode
            backendPort = $resolvedBackendPort
            backendPid = $backendOwner
            backendStarterPid = $backendStarter.Id
            frontendPort = $FrontendPort
            frontendPid = $frontendOwner
            frontendRoot = $frontendRoot
            databaseFile = $DatabaseFile
            databaseName = $DatabaseName
            databaseUser = $DatabaseUser
            postgresPort = $PostgresPort
            postgresPid = if ($Mode -eq "production") { Get-PortOwner -Port $PostgresPort } else { $null }
            postgresDataRoot = $postgresDataRoot
            redisPort = $RedisPort
            redisPid = if ($Mode -eq "production") { Get-PortOwner -Port $RedisPort } else { $null }
            workerPid = if ($null -ne $workerStarter) { $workerStarter.Id } else { $null }
            backendLog = $logs.backendErr
            frontendLog = $logs.frontendErr
            workerLog = $logs.workerErr
        }
        $state | ConvertTo-Json | Set-Content -LiteralPath $statePath -Encoding UTF8
        Write-Host "项目启动成功（$Mode 模式）。"
        Write-Host "前端：http://localhost:$FrontendPort"
        Write-Host "后端：http://localhost:$resolvedBackendPort/docs"
        if ($Mode -eq "production") {
            Write-Host "PostgreSQL：127.0.0.1:$PostgresPort/$DatabaseName"
            Write-Host "Redis：127.0.0.1:$RedisPort"
            Write-Host "Celery Worker：PID $($workerStarter.Id)"
        }
        Write-Host "日志目录：$logRoot"
    } catch {
        foreach ($process in @($frontendStarter, $backendStarter, $workerStarter, $redisStarter)) {
            if ($null -ne $process -and -not $process.HasExited) {
                Stop-Process -Id $process.Id -Force -ErrorAction SilentlyContinue
            }
        }
        if ($postgresStarted -and $null -ne $postgresTools) {
            & $postgresTools.pgCtl "-D" $postgresDataRoot "-m" "fast" "-w" "stop" | Out-Null
        }
        throw
    } finally {
        foreach ($name in $environmentNames) {
            [Environment]::SetEnvironmentVariable($name, $previousEnvironment[$name], "Process")
        }
    }
}

function Stop-ManagedProcess {
    param([string]$Name, [int]$ProcessId, [object]$State, [int]$Port = 0)
    $candidate = $ProcessId
    if ($Port -gt 0) {
        $owner = Get-PortOwner -Port $Port
        if ($null -eq $owner) {
            Write-Host "$Name 已停止（端口 $Port 未监听）。"
            return
        }
        $candidate = $owner
    }
    if ($candidate -le 0 -or -not (Test-ManagedOwner -ProcessId $candidate -Service $Name -State $State)) {
        throw "无法确认 $Name 进程归属，已跳过停止。"
    }
    Stop-Process -Id $candidate -Force
    Write-Host "$Name 已停止（PID $candidate）。"
}

function Stop-Project {
    if (-not (Test-Path -LiteralPath $statePath)) {
        Write-Host "没有找到由启停脚本创建的运行状态，未停止任何进程。"
        return
    }
    $state = Get-Content -Raw -LiteralPath $statePath | ConvertFrom-Json
    $errors = @()
    foreach ($service in @(
        [PSCustomObject]@{ Name = "frontend"; Pid = [int]$state.frontendPid; Port = [int]$state.frontendPort },
        [PSCustomObject]@{ Name = "backend"; Pid = [int]$state.backendPid; Port = [int]$state.backendPort }
    )) {
        try {
            Stop-ManagedProcess -Name $service.Name -ProcessId $service.Pid -Port $service.Port -State $state
        } catch {
            $errors += $_.Exception.Message
        }
    }
    if ([string]$state.mode -eq "production") {
        try {
            Stop-ManagedProcess -Name "worker" -ProcessId ([int]$state.workerPid) -State $state
        } catch {
            $errors += $_.Exception.Message
        }
        try {
            Stop-ManagedProcess -Name "redis" -ProcessId ([int]$state.redisPid) -Port ([int]$state.redisPort) -State $state
        } catch {
            $errors += $_.Exception.Message
        }
        try {
            $expectedDataRoot = (Resolve-Path -LiteralPath $postgresDataRoot).Path
            $recordedDataRoot = (Resolve-Path -LiteralPath ([string]$state.postgresDataRoot)).Path
            if ($expectedDataRoot -ne $recordedDataRoot) {
                throw "PostgreSQL 数据目录与项目目录不匹配。"
            }
            $tools = Get-PostgresTools
            & $tools.pgCtl "-D" $postgresDataRoot "-m" "fast" "-w" "stop" | Out-Null
            if ($LASTEXITCODE -ne 0) {
                throw "PostgreSQL 未能正常停止。"
            }
            Write-Host "postgres 已停止。"
        } catch {
            $errors += $_.Exception.Message
        }
    }
    if ($errors.Count -gt 0) {
        throw "部分服务未能停止，运行状态已保留：$($errors -join '；')"
    }
    Remove-Item -LiteralPath $statePath -Force
}

function Show-ProjectStatus {
    $resolvedBackendPort = Get-ConfiguredBackendPort
    foreach ($service in @(
        [PSCustomObject]@{ Name = "前端"; Port = $FrontendPort },
        [PSCustomObject]@{ Name = "后端"; Port = $resolvedBackendPort }
    )) {
        $owner = Get-PortOwner -Port $service.Port
        if ($null -eq $owner) {
            Write-Host "$($service.Name)端口 $($service.Port)：未运行"
        } else {
            Write-Host "$($service.Name)端口 $($service.Port)：运行中（PID $owner）"
        }
    }
    if (Test-Path -LiteralPath $statePath) {
        $state = Get-Content -Raw -LiteralPath $statePath | ConvertFrom-Json
        Write-Host "运行模式：$($state.mode)"
        Write-Host "启动时间：$($state.startedAt)"
        if ([string]$state.mode -eq "production") {
            $postgresOwner = Get-PortOwner -Port ([int]$state.postgresPort)
            $redisOwner = Get-PortOwner -Port ([int]$state.redisPort)
            $worker = Get-Process -Id ([int]$state.workerPid) -ErrorAction SilentlyContinue
            Write-Host "PostgreSQL：$(if ($null -ne $postgresOwner) { "运行中（PID $postgresOwner）" } else { "未运行" })"
            Write-Host "Redis：$(if ($null -ne $redisOwner) { "运行中（PID $redisOwner）" } else { "未运行" })"
            Write-Host "Celery Worker：$(if ($null -ne $worker) { "运行中（PID $($worker.Id)）" } else { "未运行" })"
            Write-Host "数据库：PostgreSQL/$($state.databaseName)"
        } else {
            Write-Host "数据库：backend\$($state.databaseFile)"
        }
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
            if (Test-Path -LiteralPath $statePath) {
                $restartState = Get-Content -Raw -LiteralPath $statePath | ConvertFrom-Json
                if (-not $PSBoundParameters.ContainsKey("Mode")) {
                    $Mode = [string]$restartState.mode
                }
                if (-not $PSBoundParameters.ContainsKey("DatabaseFile")) {
                    $DatabaseFile = [string]$restartState.databaseFile
                }
                if (-not $PSBoundParameters.ContainsKey("DatabaseName")) {
                    $DatabaseName = [string]$restartState.databaseName
                }
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
