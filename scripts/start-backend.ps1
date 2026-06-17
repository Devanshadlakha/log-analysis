# Builds (if needed) and runs the Spring Boot backend.
# Uses `java -jar` instead of `mvn spring-boot:run` because Lombok 1.18.44 + Java 25
# crashes mvn spring-boot:run with NoClassDefFoundError: PasswordEncoder.

$ErrorActionPreference = 'Stop'
$root = Split-Path -Parent $PSScriptRoot
Set-Location $root

# Load all KEY=VALUE pairs from .env into this process's env.
if (-not (Test-Path .env)) { throw ".env missing at repo root. Copy .env.example and fill in values." }
Get-Content .env | ForEach-Object {
    if ($_ -match '^\s*([^#=][^=]*)=(.*)$') {
        $name = $matches[1].Trim()
        $value = $matches[2].Trim()
        [Environment]::SetEnvironmentVariable($name, $value, 'Process')
    }
}

# The dockerized mongo requires SCRAM auth; backend's default URI assumes no auth.
# Override here so the backend can connect.
$env:SPRING_DATA_MONGODB_URI = "mongodb://$($env:MONGO_USER):$($env:MONGO_PASS)@127.0.0.1:27017/log-intelligence?authSource=admin"

# Build the fat JAR if it isn't already there.
$jar = "backend\target\backend-0.0.1-SNAPSHOT.jar"
if (-not (Test-Path $jar)) {
    Write-Host "Building backend JAR (one-time)..." -ForegroundColor Cyan
    Push-Location backend
    mvn package -DskipTests
    Pop-Location
}

Write-Host "Backend starting on http://localhost:8080" -ForegroundColor Green
java -jar $jar
