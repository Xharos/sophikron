<#
.SYNOPSIS
Build Sophikron images with the checked-out Git revision embedded.
.DESCRIPTION
Requires Git, Docker Compose v2 and PowerShell 5.1 or later (pwsh on Linux).
Only reads Git metadata. Does not fetch or change branches. Starts containers only with -Start.
.PARAMETER Local
Include the existing local Compose overlay.
.PARAMETER Start
After a successful build, start services in the background and wait for readiness.
.PARAMETER Preview
Show revision metadata and planned commands without building images or starting services.
#>
[CmdletBinding()]
param(
    [switch]$Local,
    [switch]$Start,
    [switch]$Preview
)

$ErrorActionPreference = 'Stop'
$projectRoot = $PSScriptRoot
$previousRevision = [Environment]::GetEnvironmentVariable('SOPHIKRON_BUILD_REVISION', 'Process')

Push-Location -LiteralPath $projectRoot
try {
    Get-Command git -ErrorAction Stop | Out-Null
    $revisionOutput = & git rev-parse --verify HEAD
    if ($LASTEXITCODE -ne 0) { throw 'Cannot read the checked-out Git commit.' }
    $revision = ($revisionOutput -join '').Trim()
    if ($revision -notmatch '^[0-9a-f]{40}$') { throw 'Unsupported Git revision format.' }

    # Ignored files (including local secrets and generated files) do not mark a build dirty.
    $changes = & git status --porcelain --untracked-files=normal
    if ($LASTEXITCODE -ne 0) { throw 'Cannot inspect local Git changes.' }
    if ($changes) { $revision += '-dirty' }

    $composeArguments = @('compose', '-f', 'compose.yaml')
    if ($Local) { $composeArguments += @('-f', 'compose.local.yaml') }
    $buildArguments = $composeArguments + @('build')
    $startArguments = $composeArguments + @('up', '-d', '--wait')

    Write-Host "Build revision: $revision"
    Write-Host ("docker " + ($buildArguments -join ' '))
    if ($Start -and $Preview) {
        Write-Host ("docker " + ($startArguments -join ' '))
    }
    if (-not $Preview) {
        Get-Command docker -ErrorAction Stop | Out-Null
        [Environment]::SetEnvironmentVariable('SOPHIKRON_BUILD_REVISION', $revision, 'Process')
        & docker @buildArguments
        if ($LASTEXITCODE -ne 0) { throw 'Docker Compose build failed.' }
        if ($Start) {
            Write-Host ("docker " + ($startArguments -join ' '))
            & docker @startArguments
            if ($LASTEXITCODE -ne 0) { throw 'Docker Compose startup failed.' }
        }
    }
}
finally {
    [Environment]::SetEnvironmentVariable('SOPHIKRON_BUILD_REVISION', $previousRevision, 'Process')
    Pop-Location
}
