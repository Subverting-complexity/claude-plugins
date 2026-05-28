<#
.SYNOPSIS
    Syncs shared skills from _shared-skills/ into each plugin's skills/ directory.
.PARAMETER Verify
    Check for drift without writing. Exits with code 1 if drift is found.
.PARAMETER Plugin
    Sync only the named plugin instead of all plugins.
#>
param(
    [switch]$Verify,
    [string]$Plugin
)

$ErrorActionPreference = 'Stop'

if ($PSScriptRoot) {
    $repoRoot = $PSScriptRoot
} else {
    $repoRoot = Split-Path -Parent (Resolve-Path $MyInvocation.MyCommand.Path)
}

$sharedDir = Join-Path $repoRoot '_shared-skills'
$syncComment = '<!-- SYNCED from _shared-skills/ -- edit the source, not this copy -->'

$allPlugins = @('github-workflow', 'local-workflow')

if ($Plugin) {
    if ($Plugin -notin $allPlugins) {
        Write-Output "Unknown plugin: $Plugin. Known: $($allPlugins -join ', ')"
        exit 1
    }
    $plugins = @($Plugin)
} else {
    $plugins = $allPlugins
}

$skillDirs = Get-ChildItem -Path $sharedDir -Directory | Where-Object { $_.Name -ne '_shared' }
$sharedSubDir = Join-Path $sharedDir '_shared'
$hasShared = Test-Path $sharedSubDir

$script:driftFound = $false
$script:syncCount = 0

function Process-MdContent {
    param([string]$Content, [string]$PluginName)
    $result = $Content -replace '\{\{PLUGIN_NAME\}\}', $PluginName
    if (-not $result.StartsWith($syncComment)) {
        $result = $syncComment + "`n" + $result
    }
    return $result
}

function Sync-Directory {
    param([string]$SourceDir, [string]$DestDir, [string]$PluginName)

    $sourceFiles = Get-ChildItem -Path $SourceDir -Recurse -File

    foreach ($file in $sourceFiles) {
        $relativePath = $file.FullName.Substring($SourceDir.Length).TrimStart('\', '/')
        $destPath = Join-Path $DestDir $relativePath
        $destParent = Split-Path $destPath -Parent

        if ($file.Extension -eq '.md') {
            $sourceContent = Get-Content -Path $file.FullName -Raw -Encoding UTF8
            $processedContent = Process-MdContent -Content $sourceContent -PluginName $PluginName

            if ($Verify) {
                if (Test-Path $destPath) {
                    $existingContent = Get-Content -Path $destPath -Raw -Encoding UTF8
                    if ($existingContent.Trim() -ne $processedContent.Trim()) {
                        Write-Output "  DRIFT: $relativePath"
                        $script:driftFound = $true
                    } else {
                        Write-Output "  OK: $relativePath"
                    }
                } else {
                    Write-Output "  MISSING: $relativePath"
                    $script:driftFound = $true
                }
            } else {
                if (-not (Test-Path $destParent)) {
                    New-Item -ItemType Directory -Path $destParent -Force | Out-Null
                }
                [System.IO.File]::WriteAllText($destPath, $processedContent, [System.Text.UTF8Encoding]::new($false))
                $script:syncCount++
                Write-Output "  Synced: $relativePath"
            }
        } else {
            if ($Verify) {
                if (Test-Path $destPath) {
                    $sourceHash = (Get-FileHash -Path $file.FullName -Algorithm SHA256).Hash
                    $destHash = (Get-FileHash -Path $destPath -Algorithm SHA256).Hash
                    if ($sourceHash -ne $destHash) {
                        Write-Output "  DRIFT: $relativePath"
                        $script:driftFound = $true
                    } else {
                        Write-Output "  OK: $relativePath"
                    }
                } else {
                    Write-Output "  MISSING: $relativePath"
                    $script:driftFound = $true
                }
            } else {
                if (-not (Test-Path $destParent)) {
                    New-Item -ItemType Directory -Path $destParent -Force | Out-Null
                }
                Copy-Item -Path $file.FullName -Destination $destPath -Force
                $script:syncCount++
                Write-Output "  Synced: $relativePath"
            }
        }
    }
}

foreach ($pluginName in $plugins) {
    $pluginSkillsDir = Join-Path (Join-Path $repoRoot $pluginName) 'skills'

    if (-not (Test-Path $pluginSkillsDir)) {
        Write-Output "WARN: Plugin skills dir not found: $pluginSkillsDir -- skipping"
        continue
    }

    Write-Output ""
    Write-Output "=== $pluginName ==="

    foreach ($skillDir in $skillDirs) {
        $destSkillDir = Join-Path $pluginSkillsDir $skillDir.Name
        Write-Output "  [$($skillDir.Name)]"
        Sync-Directory -SourceDir $skillDir.FullName -DestDir $destSkillDir -PluginName $pluginName
    }

    if ($hasShared) {
        $destSharedDir = Join-Path $pluginSkillsDir '_shared'
        Write-Output "  [_shared]"
        Sync-Directory -SourceDir $sharedSubDir -DestDir $destSharedDir -PluginName $pluginName
    }
}

Write-Output ""
if ($Verify) {
    if ($script:driftFound) {
        Write-Output "DRIFT DETECTED -- run sync-skills.ps1 to fix"
        exit 1
    } else {
        Write-Output "All synced files are up to date."
        exit 0
    }
} else {
    Write-Output "Synced $($script:syncCount) file(s) across $($plugins.Count) plugin(s)."
}
