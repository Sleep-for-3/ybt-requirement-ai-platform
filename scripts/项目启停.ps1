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
$actionWasSpecified = $PSBoundParameters.ContainsKey("Action")
$modeWasSpecified = $PSBoundParameters.ContainsKey("Mode")
$databaseFileWasSpecified = $PSBoundParameters.ContainsKey("DatabaseFile")
$databaseNameWasSpecified = $PSBoundParameters.ContainsKey("DatabaseName")

$repoRoot = Split-Path -Parent $PSScriptRoot
$backendRoot = Join-Path $repoRoot "backend"
$frontendRoot = Join-Path $repoRoot "frontend"
$runtimeRoot = Join-Path $repoRoot ".local-run"
$logRoot = Join-Path $runtimeRoot "logs"
$statePath = Join-Path $runtimeRoot "processes.json"
$secretsPath = Join-Path $runtimeRoot "local-secrets.json"
$semanticComposeEnvPath = Join-Path $runtimeRoot "semantic-compose.env"
$pgPassPath = Join-Path $runtimeRoot "postgres.pgpass"
$postgresDataRoot = Join-Path $runtimeRoot "postgres-data"
$redisDataRoot = Join-Path $runtimeRoot "redis-data"
$fastEmbedCacheRoot = Join-Path $runtimeRoot "fastembed-cache"
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

function Wait-BackendReady {
    param([int]$Port, [int]$TimeoutSeconds = 90)
    $url = "http://127.0.0.1:$Port/health/ready"
    $deadline = (Get-Date).AddSeconds($TimeoutSeconds)
    $lastChecks = ""
    while ((Get-Date) -lt $deadline) {
        try {
            $health = Invoke-RestMethod -Uri $url -UseBasicParsing -TimeoutSec 3
            if ([string]$health.status -eq "ready") {
                return $health
            }
            if ($null -ne $health.checks) {
                $lastChecks = (($health.checks.psobject.Properties | ForEach-Object {
                    "$($_.Name)=$($_.Value)"
                }) -join ", ")
            }
        } catch {
            # 服务启动期间连接失败或返回 503 属于预期。
        }
        Start-Sleep -Seconds 1
    }
    $suffix = if ([string]::IsNullOrWhiteSpace($lastChecks)) { "" } else { "；最近检查：$lastChecks" }
    throw "后端在 $TimeoutSeconds 秒内未通过 /health/ready：$url$suffix"
}

function Get-BackendReadiness {
    param([int]$Port)
    try {
        return Invoke-RestMethod -Uri "http://127.0.0.1:$Port/health/ready" -UseBasicParsing -TimeoutSec 3
    } catch {
        return $null
    }
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

function ConvertTo-WslPath {
    param([string]$WindowsPath)
    $resolved = [IO.Path]::GetFullPath($WindowsPath)
    if ($resolved -notmatch "^([A-Za-z]):\\(.*)$") {
        throw "WSL Docker 只支持当前项目位于 Windows 盘符路径下。"
    }
    $drive = $Matches[1].ToLowerInvariant()
    $remainder = $Matches[2].Replace("\", "/")
    return "/mnt/$drive/$remainder"
}

function Get-DockerRuntime {
    $nativeDocker = Get-Command docker.exe -ErrorAction SilentlyContinue
    if ($null -ne $nativeDocker) {
        & $nativeDocker.Source "info" "--format" "{{.ServerVersion}}" 2>$null | Out-Null
        if ($LASTEXITCODE -eq 0) {
            return [PSCustomObject]@{
                kind = "windows"
                executable = $nativeDocker.Source
                distribution = $null
            }
        }
    }

    $wsl = Get-Command wsl.exe -ErrorAction SilentlyContinue
    if ($null -eq $wsl) {
        return $null
    }
    foreach ($distribution in @("Ubuntu")) {
        & $wsl.Source "-d" $distribution "--" "docker" "info" "--format" "{{.ServerVersion}}" 2>$null | Out-Null
        if ($LASTEXITCODE -eq 0) {
            return [PSCustomObject]@{
                kind = "wsl"
                executable = $wsl.Source
                distribution = $distribution
            }
        }
    }
    return $null
}

function Invoke-DockerCommand {
    param(
        [object]$Runtime,
        [string[]]$Arguments,
        [switch]$AllowFailure
    )
    if ($null -eq $Runtime) {
        throw "找不到可用 Docker Engine。已检查 Windows Docker CLI 和 WSL Ubuntu。"
    }
    if ([string]$Runtime.kind -eq "windows") {
        $result = & ([string]$Runtime.executable) @Arguments
    } else {
        $result = & ([string]$Runtime.executable) "-d" ([string]$Runtime.distribution) "--" "docker" @Arguments
    }
    if ($LASTEXITCODE -ne 0 -and -not $AllowFailure) {
        throw "Docker 命令执行失败，退出码：$LASTEXITCODE"
    }
    return $result
}

function Invoke-DockerCommandWithRetry {
    param(
        [object]$Runtime,
        [string[]]$Arguments,
        [int]$Attempts = 5
    )
    for ($attempt = 1; $attempt -le $Attempts; $attempt++) {
        try {
            return Invoke-DockerCommand -Runtime $Runtime -Arguments $Arguments
        } catch {
            if ($attempt -eq $Attempts) {
                throw "Docker 命令连续失败 $Attempts 次：$($_.Exception.Message)"
            }
            Write-Host "Docker 镜像仓库连接失败，正在进行第 $($attempt + 1)/$Attempts 次重试..."
            Start-Sleep -Seconds ([Math]::Min(3 * $attempt, 12))
        }
    }
}

function Start-DockerKeepAlive {
    param([object]$Runtime)
    if ($null -eq $Runtime -or [string]$Runtime.kind -ne "wsl") {
        return $null
    }
    $process = Start-Process `
        -FilePath ([string]$Runtime.executable) `
        -ArgumentList @("-d", [string]$Runtime.distribution, "--", "sleep", "infinity") `
        -WindowStyle Hidden `
        -PassThru
    Start-Sleep -Seconds 1
    if ($process.HasExited) {
        throw "无法保持 WSL Docker 运行；sleep infinity 已提前退出。"
    }
    return $process
}

function Stop-DockerKeepAlive {
    param([int]$ProcessId)
    if ($ProcessId -le 0) {
        return
    }
    $process = Get-CimInstance Win32_Process -Filter "ProcessId = $ProcessId" -ErrorAction SilentlyContinue
    if ($null -eq $process) {
        return
    }
    if (
        $process.Name -eq "wsl.exe" -and
        $process.CommandLine -like "*sleep*infinity*"
    ) {
        Stop-Process -Id $ProcessId -Force -ErrorAction SilentlyContinue
    }
}

function Get-DockerRunningServices {
    param([object]$Runtime)
    $services = @{}
    if ($null -eq $Runtime) {
        return $services
    }
    $rows = Invoke-DockerCommand -Runtime $Runtime -AllowFailure -Arguments @(
        "ps",
        "--filter", "label=com.docker.compose.service",
        "--format", "{{.Labels}}"
    )
    foreach ($row in @($rows)) {
        if ([string]$row -match "(?:^|,)com\.docker\.compose\.service=([^,]+)") {
            $services[$Matches[1]] = $true
        }
    }
    return $services
}

function Get-DockerStatusSnapshot {
    $nativeDocker = Get-Command docker.exe -ErrorAction SilentlyContinue
    if ($null -ne $nativeDocker) {
        $runtime = Get-DockerRuntime
        return [PSCustomObject]@{
            runtime = $runtime
            services = Get-DockerRunningServices -Runtime $runtime
        }
    }

    $wsl = Get-Command wsl.exe -ErrorAction SilentlyContinue
    if ($null -eq $wsl) {
        return [PSCustomObject]@{ runtime = $null; services = @{} }
    }
    # A normal call-operator invocation lets wsl.exe inherit the control
    # console's stdin. When the menu is still refreshing, an early key press
    # can then be consumed by WSL instead of Read-Host. Capture WSL with a
    # deliberately closed stdin so the menu remains responsive.
    $command = (
        'docker info --format "ENGINE={{.ServerVersion}}" 2>/dev/null && ' +
        'docker ps --filter label=com.docker.compose.service --format "LABELS={{.Labels}}"'
    )
    $startInfo = New-Object System.Diagnostics.ProcessStartInfo
    $startInfo.FileName = $wsl.Source
    $startInfo.Arguments = "-d Ubuntu -- sh -lc `"$command`""
    $startInfo.UseShellExecute = $false
    $startInfo.CreateNoWindow = $true
    $startInfo.RedirectStandardInput = $true
    $startInfo.RedirectStandardOutput = $true
    $startInfo.RedirectStandardError = $true
    $probe = New-Object System.Diagnostics.Process
    $probe.StartInfo = $startInfo
    [void]$probe.Start()
    $probe.StandardInput.Close()
    $output = $probe.StandardOutput.ReadToEnd()
    [void]$probe.StandardError.ReadToEnd()
    $probe.WaitForExit()
    $rows = @($output -split "\r?\n" | Where-Object { -not [string]::IsNullOrWhiteSpace($_) })
    if ($probe.ExitCode -ne 0 -or @($rows | Where-Object { $_ -like "ENGINE=*" }).Count -eq 0) {
        return [PSCustomObject]@{ runtime = $null; services = @{} }
    }
    $services = @{}
    foreach ($row in @($rows | Where-Object { $_ -like "LABELS=*" })) {
        $labelText = ([string]$row).Substring("LABELS=".Length)
        if ($labelText -match "(?:^|,)com\.docker\.compose\.service=([^,]+)") {
            $services[$Matches[1]] = $true
        }
    }
    return [PSCustomObject]@{
        runtime = [PSCustomObject]@{
            kind = "wsl"
            executable = $wsl.Source
            distribution = "Ubuntu"
        }
        services = $services
    }
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
        $secrets = Get-Content -Raw -LiteralPath $secretsPath | ConvertFrom-Json
        $updated = $false
        if ($secrets.PSObject.Properties.Name -notcontains "milvusMinioUser") {
            $secrets | Add-Member -NotePropertyName "milvusMinioUser" -NotePropertyValue "ybt_milvus"
            $updated = $true
        }
        if ($secrets.PSObject.Properties.Name -notcontains "milvusMinioPassword") {
            $secrets | Add-Member `
                -NotePropertyName "milvusMinioPassword" `
                -NotePropertyValue ([guid]::NewGuid().ToString("N") + [guid]::NewGuid().ToString("N"))
            $updated = $true
        }
        if ($updated) {
            $secrets | ConvertTo-Json | Set-Content -LiteralPath $secretsPath -Encoding UTF8
            Protect-LocalSecretFile -Path $secretsPath
        }
        return $secrets
    }
    $secrets = [PSCustomObject]@{
        postgresSuperPassword = ([guid]::NewGuid().ToString("N") + [guid]::NewGuid().ToString("N"))
        databasePassword = ([guid]::NewGuid().ToString("N") + [guid]::NewGuid().ToString("N"))
        milvusMinioUser = "ybt_milvus"
        milvusMinioPassword = ([guid]::NewGuid().ToString("N") + [guid]::NewGuid().ToString("N"))
    }
    $secrets | ConvertTo-Json | Set-Content -LiteralPath $secretsPath -Encoding UTF8
    Protect-LocalSecretFile -Path $secretsPath
    return $secrets
}

function Write-SemanticComposeEnvFile {
    param([object]$Secrets)
    @(
        # Compose expands variables for every declared service even when only
        # the Milvus profile is targeted. Explicit non-secret placeholders
        # keep status/start/stop output free of unrelated warnings.
        "POSTGRES_USER=not-used-by-semantic-profile",
        "POSTGRES_PASSWORD=not-used-by-semantic-profile",
        "POSTGRES_DB=not-used-by-semantic-profile",
        "S3_ACCESS_KEY=not-used-by-semantic-profile",
        "S3_SECRET_KEY=not-used-by-semantic-profile",
        "MILVUS_MINIO_ROOT_USER=$([string]$Secrets.milvusMinioUser)",
        "MILVUS_MINIO_ROOT_PASSWORD=$([string]$Secrets.milvusMinioPassword)"
    ) | Set-Content -LiteralPath $semanticComposeEnvPath -Encoding ASCII
    Protect-LocalSecretFile -Path $semanticComposeEnvPath
}

function Get-DockerComposeArguments {
    param([object]$Runtime)
    if ([string]$Runtime.kind -eq "wsl") {
        return @(
            "compose",
            "--project-name", "ybt-requirement-ai-platform",
            "--project-directory", (ConvertTo-WslPath -WindowsPath $repoRoot),
            "--env-file", (ConvertTo-WslPath -WindowsPath $semanticComposeEnvPath)
        )
    }
    return @(
        "compose",
        "--project-name", "ybt-requirement-ai-platform",
        "--project-directory", $repoRoot,
        "--env-file", $semanticComposeEnvPath
    )
}

function Start-SemanticInfrastructure {
    param([object]$Runtime, [object]$Secrets)
    Write-SemanticComposeEnvFile -Secrets $Secrets
    $arguments = @(
        Get-DockerComposeArguments -Runtime $Runtime
    ) + @(
        "--profile", "milvus",
        "up", "-d",
        "etcd", "milvus-minio", "milvus"
    )
    Invoke-DockerCommandWithRetry -Runtime $Runtime -Arguments $arguments | Out-Host
    if (-not (Wait-Port -Port 19530 -TimeoutSeconds 180)) {
        throw "Milvus 未能在 180 秒内启动，请使用项目状态命令检查容器。"
    }
}

function Stop-SemanticInfrastructure {
    param([object]$Runtime)
    if ($null -eq $Runtime -or -not (Test-Path -LiteralPath $semanticComposeEnvPath)) {
        return
    }
    $arguments = @(
        Get-DockerComposeArguments -Runtime $Runtime
    ) + @(
        "--profile", "milvus",
        "stop",
        "etcd", "milvus-minio", "milvus"
    )
    Invoke-DockerCommand -Runtime $Runtime -Arguments $arguments | Out-Host
}

function Start-LocalEmbeddingInfrastructure {
    param([string]$OutLog, [string]$ErrorLog)
    & $backendPython -c "import fastembed" 2>$null
    if ($LASTEXITCODE -ne 0) {
        throw "缺少 FastEmbed 运行依赖。请在 backend 目录执行 .venv\Scripts\python.exe -m pip install -r requirements.txt。"
    }
    New-Item -ItemType Directory -Path $fastEmbedCacheRoot -Force | Out-Null
    $env:FASTEMBED_CACHE_PATH = $fastEmbedCacheRoot
    $env:FASTEMBED_THREADS = "2"
    $process = Start-Process `
        -FilePath $backendPython `
        -ArgumentList @(
            "-m", "uvicorn",
            "app.local_embedding_server:app",
            "--host", "127.0.0.1",
            "--port", "11434"
        ) `
        -WorkingDirectory $backendRoot `
        -RedirectStandardOutput $OutLog `
        -RedirectStandardError $ErrorLog `
        -WindowStyle Hidden `
        -PassThru
    if (-not (Wait-Port -Port 11434 -TimeoutSeconds 60)) {
        throw "本地 FastEmbed 服务未能在 60 秒内启动。"
    }
    Write-Host "正在验证本地中文 Embedding 模型；首次运行会下载约 90 MB 的模型文件并持久缓存。"
    try {
        $selfCheckBody = @{
            model = "BAAI/bge-small-zh-v1.5"
            input = @("本地语义索引启动自检")
        } | ConvertTo-Json -Compress
        $selfCheck = Invoke-RestMethod `
            -Uri "http://127.0.0.1:11434/v1/embeddings" `
            -Method Post `
            -ContentType "application/json; charset=utf-8" `
            -Body ([Text.Encoding]::UTF8.GetBytes($selfCheckBody)) `
            -TimeoutSec 600
        $selfCheckDimension = @($selfCheck.data[0].embedding).Count
        if ($selfCheckDimension -ne 512) {
            throw "返回维度 $selfCheckDimension，预期维度 512。"
        }
    } catch {
        throw "Embedding 向量生成自检失败：$($_.Exception.Message)"
    }
    return $process
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

function Move-StalePostgresPidFile {
    $pidPath = Join-Path $postgresDataRoot "postmaster.pid"
    if (-not (Test-Path -LiteralPath $pidPath)) {
        return
    }

    $recordedPid = (Get-Content -LiteralPath $pidPath -TotalCount 1 -ErrorAction Stop).Trim()
    if ($recordedPid -notmatch "^\d+$") {
        return
    }
    if ($null -ne (Get-PortOwner -Port $PostgresPort)) {
        return
    }
    if ($null -ne (Get-Process -Id ([int]$recordedPid) -ErrorAction SilentlyContinue)) {
        return
    }

    $backupName = "postmaster.pid.stale-$(Get-Date -Format 'yyyyMMdd-HHmmss')"
    Move-Item -LiteralPath $pidPath -Destination (Join-Path $postgresDataRoot $backupName) -ErrorAction Stop
    Write-Host "PostgreSQL 陈旧 PID 文件已移至备份：$backupName"
}

function Start-Postgres {
    param([object]$Tools, [object]$Secrets, [string]$LogPath)
    Initialize-Postgres -Tools $Tools -Secrets $Secrets
    Move-StalePostgresPidFile
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
    # Production must never start in legacy-system mode.  SQLite is the
    # explicitly local-development profile and is the only launcher mode
    # allowed to retain optional authentication.
    $env:ENVIRONMENT = if ($Mode -eq "production") { "production" } else { "development" }
    $env:AUTH_MODE = if ($Mode -eq "production") { "required" } else { "optional" }
    $env:CORS_ORIGINS = "http://localhost:$FrontendPort,http://127.0.0.1:$FrontendPort"
    $env:LOCAL_BACKEND_PORT = [string]$Port
    # Keep the long-running dev server isolated from `next build`'s production `.next` output.
    # Without this, a build can replace chunks while the dev server is still serving HTML.
    $env:NEXT_DIST_DIR = ".next-dev"
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

function Get-BackendEnvironmentValue {
    param([string]$Name)
    $processValue = [Environment]::GetEnvironmentVariable($Name, "Process")
    if (-not [string]::IsNullOrWhiteSpace($processValue)) {
        return $processValue
    }
    $line = Get-Content -LiteralPath (Join-Path $backendRoot ".env") -ErrorAction SilentlyContinue |
        Where-Object { $_ -match "^\s*$([regex]::Escape($Name))\s*=" } |
        Select-Object -First 1
    if ($line -match "^\s*$([regex]::Escape($Name))\s*=\s*(.*)$") {
        return $Matches[1].Trim().Trim('"').Trim("'")
    }
    return ""
}

function Set-SemanticEnvironment {
    $configuredProvider = Get-BackendEnvironmentValue -Name "EMBEDDING_PROVIDER"

    $env:VECTOR_STORE_PROVIDER = "milvus"
    $env:MILVUS_URI = "http://127.0.0.1:19530"
    if ([string]::IsNullOrWhiteSpace($configuredProvider) -or $configuredProvider -eq "mock") {
        $env:EMBEDDING_PROVIDER = "local_vllm"
        $env:EMBEDDING_BASE_URL = "http://127.0.0.1:11434/v1"
        $env:EMBEDDING_MODEL = "BAAI/bge-small-zh-v1.5"
        $env:EMBEDDING_DIMENSION = "512"
        $env:EMBEDDING_API_KEY_ENV_NAME = "EMBEDDING_API_KEY"
        return [PSCustomObject]@{
            provider = $env:EMBEDDING_PROVIDER
            model = $env:EMBEDDING_MODEL
            dimension = [int]$env:EMBEDDING_DIMENSION
            usesManagedFastEmbed = $true
        }
    }
    $configuredDimension = Get-BackendEnvironmentValue -Name "EMBEDDING_DIMENSION"
    return [PSCustomObject]@{
        provider = $configuredProvider
        model = Get-BackendEnvironmentValue -Name "EMBEDDING_MODEL"
        dimension = if ($configuredDimension -match "^\d+$") { [int]$configuredDimension } else { 0 }
        usesManagedFastEmbed = $false
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
        try {
            $marker = Get-Content -Raw -LiteralPath $migrationMarker | ConvertFrom-Json
        } catch {
            throw "SQLite 迁移标记无法读取。为避免覆盖数据，请先备份并手工核验。"
        }
        $sourceItem = Get-Item -LiteralPath $source
        $currentSourcePath = [IO.Path]::GetFullPath($source)
        $markerSourcePath = [IO.Path]::GetFullPath([string]$marker.source)
        $sourceIsUnchanged = $currentSourcePath.Equals(
            $markerSourcePath,
            [StringComparison]::OrdinalIgnoreCase
        ) -and
            [long]$marker.sourceLength -eq [long]$sourceItem.Length -and
            [string]$marker.sourceLastWriteTime -eq $sourceItem.LastWriteTimeUtc.ToString("o") -and
            [string]$marker.databaseName -eq $DatabaseName
        if (-not $sourceIsUnchanged) {
            throw "SQLite 源文件已变化，与迁移标记不一致。为避免覆盖数据，请先备份并手工核验。"
        }
        $markerSourceProjectCount = if ($marker.PSObject.Properties.Name -contains "sourceProjectCount") {
            [int]$marker.sourceProjectCount
        } else {
            [int]$sourceProjectCount
        }
        if ($sourceProjectCount -ne $markerSourceProjectCount) {
            throw "SQLite 源文件中的项目数已变化。为避免覆盖数据，请先备份并手工核验。"
        }
        if ($targetProjectCount -lt $markerSourceProjectCount) {
            throw "PostgreSQL 项目数少于已迁移的 SQLite 项目数。为避免覆盖数据，请先备份并手工核验。"
        }
        if (-not ($marker.PSObject.Properties.Name -contains "sourceProjectCount")) {
            $marker | Add-Member -NotePropertyName "sourceProjectCount" -NotePropertyValue $sourceProjectCount
            $marker | ConvertTo-Json | Set-Content -LiteralPath $migrationMarker -Encoding UTF8
        }
        if ($targetProjectCount -ge $markerSourceProjectCount) {
            return
        }
    }
    if (-not $DatabaseCreatedNow) {
        $protectedTables = Get-PostgresProtectedDataTables
        if ($targetProjectCount -gt 0 -or $protectedTables.Count -gt 0) {
            Write-Host "检测到已有 PostgreSQL 业务数据，PostgreSQL 作为权威数据源；跳过 SQLite 自动迁移。"
            return
        }
        $detail = if ($protectedTables.Count -gt 0) {
            "；已检测到：$($protectedTables -join ', ')"
        } else {
            ""
        }
        throw "PostgreSQL 不是本次启动新建的专用空库且没有业务数据或完整迁移标记，禁止自动覆盖$detail。请先备份并手工核验。"
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
            sourceProjectCount = $sourceProjectCount
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
        "embedding" {
            return $process.CommandLine -like "*uvicorn*" -and
                $process.CommandLine -like "*app.local_embedding_server:app*" -and
                $process.CommandLine -like "*--port 11434*"
        }
        "redis" {
            return $process.CommandLine -like "*redis-server*" -and
                $process.CommandLine -like "*$([int]$State.redisPort)*" -and
                $process.CommandLine -like "*$redisDataRoot*"
        }
    }
    return $false
}

function Stop-FailedLaunchPortOwner {
    param(
        [ValidateSet("frontend", "backend", "embedding")]
        [string]$Service,
        [int]$Port
    )
    $owner = Get-PortOwner -Port $Port
    if ($null -eq $owner) {
        return
    }
    $process = Get-CimInstance Win32_Process -Filter "ProcessId = $owner" -ErrorAction SilentlyContinue
    if ($null -eq $process) {
        return
    }
    $owned = if ($Service -eq "frontend") {
        $process.CommandLine -like "*$frontendRoot*" -and
            $process.CommandLine -like "*next*"
    } elseif ($Service -eq "backend") {
        $process.CommandLine -like "*uvicorn*" -and
            $process.CommandLine -like "*app.main:app*" -and
            $process.CommandLine -like "*--port $Port*"
    } else {
        $process.CommandLine -like "*uvicorn*" -and
            $process.CommandLine -like "*app.local_embedding_server:app*" -and
            $process.CommandLine -like "*--port $Port*"
    }
    if ($owned) {
        Stop-Process -Id $owner -Force -ErrorAction SilentlyContinue
    }
}

function Start-Project {
    Assert-LocalPrerequisites
    $resolvedBackendPort = Get-ConfiguredBackendPort
    $ports = @($FrontendPort, $resolvedBackendPort)
    if ($Mode -eq "production") {
        $ports += @($PostgresPort, $RedisPort)
        $configuredEmbeddingProvider = Get-BackendEnvironmentValue -Name "EMBEDDING_PROVIDER"
        if (
            [string]::IsNullOrWhiteSpace($configuredEmbeddingProvider) -or
            $configuredEmbeddingProvider -eq "mock"
        ) {
            $ports += 11434
        }
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
        embeddingOut = Join-Path $logRoot "embedding-$timestamp.stdout.log"
        embeddingErr = Join-Path $logRoot "embedding-$timestamp.stderr.log"
        workerOut = Join-Path $logRoot "worker-$timestamp.stdout.log"
        workerErr = Join-Path $logRoot "worker-$timestamp.stderr.log"
        backendOut = Join-Path $logRoot "backend-$timestamp.stdout.log"
        backendErr = Join-Path $logRoot "backend-$timestamp.stderr.log"
        frontendOut = Join-Path $logRoot "frontend-$timestamp.stdout.log"
        frontendErr = Join-Path $logRoot "frontend-$timestamp.stderr.log"
    }
    $environmentNames = @(
        "DATABASE_URL", "STORAGE_DIR", "ENVIRONMENT", "AUTH_MODE", "TASK_QUEUE_PROVIDER",
        "REDIS_URL", "CELERY_BROKER_URL", "CELERY_RESULT_BACKEND",
        "LLM_PROVIDER", "EMBEDDING_PROVIDER", "VECTOR_STORE_PROVIDER",
        "EMBEDDING_BASE_URL", "EMBEDDING_MODEL", "EMBEDDING_DIMENSION",
        "EMBEDDING_API_KEY_ENV_NAME", "MILVUS_URI",
        "FASTEMBED_CACHE_PATH", "FASTEMBED_THREADS",
        "CORS_ORIGINS", "LOCAL_BACKEND_PORT", "KNOWLEDGE_INGESTION_BATCH_SIZE",
        "PGPASSFILE", "NEXT_DIST_DIR"
    )
    $previousEnvironment = @{}
    foreach ($name in $environmentNames) {
        $previousEnvironment[$name] = [Environment]::GetEnvironmentVariable($name, "Process")
    }

    $postgresTools = $null
    $redisStarter = $null
    $workerStarter = $null
    $embeddingStarter = $null
    $backendStarter = $null
    $frontendStarter = $null
    $postgresStarted = $false
    $semanticStarted = $false
    $localEmbeddingStarted = $false
    $dockerRuntime = $null
    $dockerKeepAlive = $null
    $semanticRuntime = $null
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
            $dockerRuntime = Get-DockerRuntime
            $dockerKeepAlive = Start-DockerKeepAlive -Runtime $dockerRuntime
            Start-SemanticInfrastructure -Runtime $dockerRuntime -Secrets $secrets
            $semanticStarted = $true
            $databaseUrl = "postgresql+psycopg://$DatabaseUser@127.0.0.1`:$PostgresPort/$DatabaseName"
        } else {
            $databaseUrl = "sqlite:///./$DatabaseFile"
        }
        Set-ProjectEnvironment -Port $resolvedBackendPort -DatabaseUrl $databaseUrl
        if ($Mode -eq "production") {
            $semanticRuntime = Set-SemanticEnvironment
            if ($semanticRuntime.usesManagedFastEmbed) {
                $embeddingStarter = Start-LocalEmbeddingInfrastructure `
                    -OutLog $logs.embeddingOut `
                    -ErrorLog $logs.embeddingErr
                $localEmbeddingStarted = $true
            }
        }
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

        $backendReadiness = Wait-BackendReady -Port $resolvedBackendPort -TimeoutSeconds 90
        if (-not (Wait-Endpoint -Url "http://127.0.0.1:$FrontendPort/")) {
            throw "前端在 90 秒内未就绪，请检查日志：$($logs.frontendErr)"
        }

        $backendOwner = Get-PortOwner -Port $resolvedBackendPort
        $frontendOwner = Get-PortOwner -Port $FrontendPort
        if ($null -eq $backendOwner -or $null -eq $frontendOwner) {
            throw "服务已响应，但无法确认监听进程。"
        }
        $readinessChecks = @{}
        if ($null -ne $backendReadiness.checks) {
            foreach ($property in $backendReadiness.checks.psobject.Properties) {
                $readinessChecks[[string]$property.Name] = [string]$property.Value
            }
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
            dockerRuntime = if ($null -ne $dockerRuntime) { [string]$dockerRuntime.kind } else { $null }
            dockerDistribution = if ($null -ne $dockerRuntime) { [string]$dockerRuntime.distribution } else { $null }
            dockerKeepAlivePid = if ($null -ne $dockerKeepAlive) { $dockerKeepAlive.Id } else { $null }
            embeddingPort = if ($localEmbeddingStarted) { 11434 } else { $null }
            embeddingPid = if ($localEmbeddingStarted) { Get-PortOwner -Port 11434 } else { $null }
            embeddingStarterPid = if ($null -ne $embeddingStarter) { $embeddingStarter.Id } else { $null }
            embeddingProvider = if ($null -ne $semanticRuntime) { [string]$semanticRuntime.provider } else { "mock" }
            embeddingModel = if ($null -ne $semanticRuntime) { [string]$semanticRuntime.model } else { "mock" }
            embeddingDimension = if ($null -ne $semanticRuntime) { [int]$semanticRuntime.dimension } else { 0 }
            localEmbeddingManaged = $localEmbeddingStarted
            vectorStoreProvider = if ($Mode -eq "production") { "milvus" } else { "mock" }
            backendLog = $logs.backendErr
            frontendLog = $logs.frontendErr
            workerLog = $logs.workerErr
            embeddingLog = $logs.embeddingErr
            readinessChecks = $readinessChecks
        }
        $state | ConvertTo-Json | Set-Content -LiteralPath $statePath -Encoding UTF8
        Write-Host "项目启动成功（$Mode 模式）。"
        Write-Host "前端入口：http://127.0.0.1:$FrontendPort/login"
        Write-Host "后端：http://localhost:$resolvedBackendPort/docs"
        if ($Mode -eq "production") {
            Write-Host "PostgreSQL：127.0.0.1:$PostgresPort/$DatabaseName"
            Write-Host "Redis：127.0.0.1:$RedisPort"
            Write-Host "Celery Worker：PID $($workerStarter.Id)"
        }
        Write-Host "日志目录：$logRoot"
    } catch {
        foreach ($process in @($frontendStarter, $backendStarter, $workerStarter, $embeddingStarter, $redisStarter)) {
            if ($null -ne $process -and -not $process.HasExited) {
                Stop-Process -Id $process.Id -Force -ErrorAction SilentlyContinue
            }
        }
        Stop-FailedLaunchPortOwner -Service "frontend" -Port $FrontendPort
        Stop-FailedLaunchPortOwner -Service "backend" -Port $resolvedBackendPort
        Stop-FailedLaunchPortOwner -Service "embedding" -Port 11434
        if ($semanticStarted) {
            Stop-SemanticInfrastructure -Runtime $dockerRuntime
        }
        if ($null -ne $dockerKeepAlive) {
            Stop-DockerKeepAlive -ProcessId $dockerKeepAlive.Id
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
    if ($candidate -le 0) {
        Write-Host "$Name 已停止（没有有效的记录 PID）。"
        return
    }
    $existingProcess = Get-Process -Id $candidate -ErrorAction SilentlyContinue
    if ($null -eq $existingProcess) {
        Write-Host "$Name 已停止（PID $candidate 不存在）。"
        return
    }
    if (-not (Test-ManagedOwner -ProcessId $candidate -Service $Name -State $State)) {
        if ($Port -le 0) {
            Write-Host "$Name 已停止（记录的 PID 已不属于此项目，按已停止处理）。"
            return
        }
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
        $stopDockerRuntime = Get-DockerRuntime
        if (
            $state.PSObject.Properties.Name -contains "localEmbeddingManaged" -and
            [bool]$state.localEmbeddingManaged
        ) {
            try {
                Stop-ManagedProcess `
                    -Name "embedding" `
                    -ProcessId ([int]$state.embeddingPid) `
                    -Port ([int]$state.embeddingPort) `
                    -State $state
                Write-Host "本地 FastEmbed 服务已停止；模型缓存已保留。"
            } catch {
                $errors += $_.Exception.Message
            }
        }
        try {
            Stop-SemanticInfrastructure -Runtime $stopDockerRuntime
            Write-Host "Milvus、etcd 和 Milvus MinIO 已停止；持久化 Volume 已保留。"
        } catch {
            $errors += $_.Exception.Message
        }
        if ($state.PSObject.Properties.Name -contains "dockerKeepAlivePid") {
            Stop-DockerKeepAlive -ProcessId ([int]$state.dockerKeepAlivePid)
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
            if ($null -eq (Get-PortOwner -Port ([int]$state.postgresPort))) {
                Write-Host "postgres 已停止。"
            } else {
                $tools = Get-PostgresTools
                & $tools.pgCtl "-D" $postgresDataRoot "-m" "fast" "-w" "stop" | Out-Null
                if ($LASTEXITCODE -ne 0) {
                    throw "PostgreSQL 未能正常停止。"
                }
                Write-Host "postgres 已停止。"
            }
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
    $state = $null
    $hasManagedState = Test-Path -LiteralPath $statePath
    if ($hasManagedState) {
        $state = Get-Content -Raw -LiteralPath $statePath | ConvertFrom-Json
    }

    $statusFrontendPort = if ($null -ne $state) { [int]$state.frontendPort } else { $FrontendPort }
    $statusBackendPort = if ($null -ne $state) { [int]$state.backendPort } else { Get-ConfiguredBackendPort }
    $frontendOwner = Get-PortOwner -Port $statusFrontendPort
    $backendOwner = Get-PortOwner -Port $statusBackendPort
    $backendHealthy = $false
    $backendReadiness = $null
    if ($null -ne $backendOwner) {
        $backendReadiness = Get-BackendReadiness -Port $statusBackendPort
        $backendHealthy = $null -ne $backendReadiness -and [string]$backendReadiness.status -eq "ready"
    }

    $dockerSnapshot = Get-DockerStatusSnapshot
    $dockerRuntime = $dockerSnapshot.runtime
    $runningDockerServices = $dockerSnapshot.services
    $milvusRunning = $runningDockerServices.ContainsKey("milvus")
    $embeddingOwner = if (
        $null -ne $state -and
        $state.PSObject.Properties.Name -contains "embeddingPort" -and
        $null -ne $state.embeddingPort
    ) {
        Get-PortOwner -Port ([int]$state.embeddingPort)
    } else {
        $null
    }
    $semanticProvider = if (
        $null -ne $state -and
        $state.PSObject.Properties.Name -contains "embeddingProvider"
    ) {
        [string]$state.embeddingProvider
    } else {
        "未由启停脚本配置"
    }
    $isProduction = $null -ne $state -and [string]$state.mode -eq "production"
    $postgresOwner = $null
    $redisOwner = $null
    $worker = $null
    if ($isProduction) {
        $postgresOwner = Get-PortOwner -Port ([int]$state.postgresPort)
        $redisOwner = Get-PortOwner -Port ([int]$state.redisPort)
        $worker = if (Test-ManagedOwner -ProcessId ([int]$state.workerPid) -Service "worker" -State $state) {
            Get-Process -Id ([int]$state.workerPid) -ErrorAction SilentlyContinue
        } else {
            $null
        }
    }
    $fullyRunning = $hasManagedState -and
        $null -ne $frontendOwner -and
        $null -ne $backendOwner -and
        $backendHealthy -and
        (-not $isProduction -or (
            $null -ne $postgresOwner -and
            $null -ne $redisOwner -and
            $null -ne $worker -and
            $milvusRunning -and
            (
                $state.PSObject.Properties.Name -notcontains "localEmbeddingManaged" -or
                -not [bool]$state.localEmbeddingManaged -or
                $null -ne $embeddingOwner
            )
        ))

    Write-Host ""
    Write-Host "================ 项目运行状态 ================" -ForegroundColor Cyan
    if ($fullyRunning) {
        Write-Host "总体状态：完整运行" -ForegroundColor Green
    } else {
        Write-Host "总体状态：未完整启动" -ForegroundColor Yellow
    }
    Write-Host "前端服务：$(if ($null -ne $frontendOwner) { "运行中（PID $frontendOwner）" } else { "未运行" })"
    Write-Host "前端入口：http://127.0.0.1:$statusFrontendPort/login"
    Write-Host "后端服务：$(if ($null -ne $backendOwner) { "运行中（PID $backendOwner）" } else { "未运行" })"
    Write-Host "接口文档：http://127.0.0.1:$statusBackendPort/docs"
    Write-Host "健康检查：http://127.0.0.1:$statusBackendPort/health/ready（$(if ($backendHealthy) { "正常" } else { "不可用" })）"
    if ($null -ne $backendReadiness -and $null -ne $backendReadiness.checks) {
        $checkSummary = (($backendReadiness.checks.psobject.Properties | ForEach-Object {
            "$($_.Name)=$($_.Value)"
        }) -join ", ")
        Write-Host "就绪依赖：$checkSummary"
    }
    Write-Host "Docker 引擎：$(if ($null -eq $dockerRuntime) { "不可用" } elseif ([string]$dockerRuntime.kind -eq "wsl") { "运行中（WSL $($dockerRuntime.distribution)）" } else { "运行中（Windows）" })"
    Write-Host "Milvus：$(if ($milvusRunning) { "运行中（127.0.0.1:19530）" } else { "未运行" })"
    $embeddingStatusSuffix = if ($null -ne $embeddingOwner) { "（本地 FastEmbed 运行中，PID $embeddingOwner）" } else { "" }
    Write-Host "Embedding：${semanticProvider}${embeddingStatusSuffix}"
    if ($null -ne $state) {
        Write-Host "运行模式：$($state.mode)"
        Write-Host "启动时间：$($state.startedAt)"
        if ($isProduction) {
            Write-Host "PostgreSQL：$(if ($null -ne $postgresOwner) { "运行中（PID $postgresOwner）" } else { "未运行" })"
            Write-Host "数据库地址：127.0.0.1:$($state.postgresPort)/$($state.databaseName)"
            Write-Host "Redis：$(if ($null -ne $redisOwner) { "运行中（PID $redisOwner）" } else { "未运行" })"
            Write-Host "Redis 地址：127.0.0.1:$($state.redisPort)"
            Write-Host "Celery Worker：$(if ($null -ne $worker) { "运行中（PID $($worker.Id)）" } else { "未运行" })"
        } else {
            Write-Host "数据库：backend\$($state.databaseFile)"
        }
    } else {
        Write-Host "运行记录：未找到；如需启动，请选择“启动项目”。"
    }
    Write-Host "日志目录：$logRoot"
    Write-Host "==============================================" -ForegroundColor Cyan
}

function Show-RecentErrorLogs {
    if (-not (Test-Path -LiteralPath $logRoot)) {
        return
    }
    $logs = @(Get-ChildItem -LiteralPath $logRoot -Filter "*.stderr.log" -File |
        Sort-Object LastWriteTime -Descending |
        Select-Object -First 3)
    if ($logs.Count -eq 0) {
        return
    }
    Write-Host ""
    Write-Host "最近错误日志（每个文件末尾 12 行）：" -ForegroundColor Yellow
    foreach ($log in $logs) {
        Write-Host "--- $($log.Name) ---" -ForegroundColor DarkYellow
        Get-Content -LiteralPath $log.FullName -Tail 12
    }
}

function Invoke-ProjectAction {
    param(
        [ValidateSet("start", "stop", "restart", "status")]
        [string]$RequestedAction
    )
    switch ($RequestedAction) {
        "start" {
            Start-Project
            Show-ProjectStatus
        }
        "stop" { Stop-Project }
        "restart" {
            if (Test-Path -LiteralPath $statePath) {
                $restartState = Get-Content -Raw -LiteralPath $statePath | ConvertFrom-Json
                if (-not $modeWasSpecified) {
                    $Mode = [string]$restartState.mode
                }
                if (-not $databaseFileWasSpecified) {
                    $DatabaseFile = [string]$restartState.databaseFile
                }
                if (-not $databaseNameWasSpecified) {
                    $DatabaseName = [string]$restartState.databaseName
                }
            }
            Stop-Project
            Start-Project
            Show-ProjectStatus
        }
        "status" { Show-ProjectStatus }
    }
}

function Start-InteractiveConsole {
    try {
        [Console]::Title = "一表通口径平台 - 项目启停"
    } catch {
        # 输出被重定向时可能没有可设置标题的控制台。
    }
    while ($true) {
        Show-ProjectStatus
        Write-Host ""
        Write-Host "操作菜单：" -ForegroundColor Cyan
        Write-Host "  [1] 启动项目（直接按 Enter）"
        Write-Host "  [2] 刷新状态"
        Write-Host "  [3] 重启项目"
        Write-Host "  [4] 停止项目"
        Write-Host "  [0] 退出窗口（不会停止已运行的项目）"
        $choice = Read-Host "请选择"
        if ([string]::IsNullOrWhiteSpace($choice)) {
            $choice = "1"
        }
        if ($choice -eq "0") {
            return
        }
        $requestedAction = switch ($choice) {
            "1" { "start" }
            "2" { "status" }
            "3" { "restart" }
            "4" { "stop" }
            default { $null }
        }
        if ($null -eq $requestedAction) {
            Write-Host "无法识别的选项：$choice" -ForegroundColor Yellow
            continue
        }
        try {
            Invoke-ProjectAction -RequestedAction $requestedAction
        } catch {
            Write-Host ""
            Write-Host "操作失败：$($_.Exception.Message)" -ForegroundColor Red
            Show-RecentErrorLogs
        }
        Write-Host ""
        Read-Host "按 Enter 返回操作菜单" | Out-Null
    }
}

if (-not $actionWasSpecified) {
    Start-InteractiveConsole
    exit 0
}

try {
    Invoke-ProjectAction -RequestedAction $Action
} catch {
    Write-Error $_
    Show-RecentErrorLogs
    exit 1
}
