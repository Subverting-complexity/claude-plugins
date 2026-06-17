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

$skillDirs = Get-ChildItem -Path $sharedDir -Directory | Where-Object { $_.Name -ne '_shared' -and $_.Name -ne 'references' }
$sharedSubDir = Join-Path $sharedDir '_shared'
$hasShared = Test-Path $sharedSubDir
$referencesDir = Join-Path $sharedDir 'references'
$hasReferences = Test-Path $referencesDir

$script:driftFound = $false
$script:syncCount = 0
$script:deleteCount = 0

function Get-PluginVersion {
    param([string]$PluginName)
    $pluginJsonPath = Join-Path (Join-Path (Join-Path $repoRoot $PluginName) '.claude-plugin') 'plugin.json'
    if (Test-Path $pluginJsonPath) {
        $pluginJson = Get-Content -Path $pluginJsonPath -Raw -Encoding UTF8 | ConvertFrom-Json
        return $pluginJson.version
    }
    return '0.0.0'
}

function Process-MdContent {
    param([string]$Content, [string]$PluginName)
    $result = $Content -replace '\{\{PLUGIN_NAME\}\}', $PluginName
    $version = Get-PluginVersion -PluginName $PluginName
    $result = $result -replace '\{\{PLUGIN_VERSION\}\}', $version
    $result = $result -replace "`r`n", "`n"

    # Already carries the banner -- leave it untouched (idempotent re-sync).
    if ($result.Contains($syncComment)) {
        return $result
    }

    # The banner is an HTML comment, but a SKILL.md must keep its YAML
    # frontmatter ('---') on line 1 or the skill loader cannot parse it and
    # the skill silently fails to register. So when the file opens with
    # frontmatter, insert the banner on its own line immediately AFTER the
    # closing '---'. Files without frontmatter get the banner prepended.
    $lines = $result -split "`n", -1
    if ($lines.Count -gt 1 -and $lines[0] -eq '---') {
        for ($i = 1; $i -lt $lines.Count; $i++) {
            if ($lines[$i] -eq '---') {
                $before = $lines[0..$i]
                $after = if ($i + 1 -le $lines.Count - 1) { $lines[($i + 1)..($lines.Count - 1)] } else { @() }
                return (($before + $syncComment + $after) -join "`n")
            }
        }
    }
    return $syncComment + "`n" + $result
}

$script:expectedFiles = @{}

function Sync-Directory {
    param([string]$SourceDir, [string]$DestDir, [string]$PluginName)

    $sourceFiles = Get-ChildItem -Path $SourceDir -Recurse -File

    foreach ($file in $sourceFiles) {
        $relativePath = $file.FullName.Substring($SourceDir.Length).TrimStart('\', '/')
        $destPath = Join-Path $DestDir $relativePath
        $destParent = Split-Path $destPath -Parent

        $script:expectedFiles[$destPath] = $true

        if ($file.Extension -eq '.md') {
            $sourceContent = Get-Content -Path $file.FullName -Raw -Encoding UTF8
            $processedContent = Process-MdContent -Content $sourceContent -PluginName $PluginName

            if ($Verify) {
                if (Test-Path $destPath) {
                    $existingContent = (Get-Content -Path $destPath -Raw -Encoding UTF8) -replace "`r`n", "`n"
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

function Remove-OrphanedFiles {
    param([string]$DestDir, [string]$Label)

    if (-not (Test-Path $DestDir)) { return }

    $existingFiles = Get-ChildItem -Path $DestDir -Recurse -File
    foreach ($file in $existingFiles) {
        if (-not $script:expectedFiles.ContainsKey($file.FullName)) {
            $relativePath = $file.FullName.Substring($DestDir.Length).TrimStart('\', '/')
            if ($Verify) {
                Write-Output "  ORPHAN: $relativePath (would be deleted)"
                $script:driftFound = $true
            } else {
                Remove-Item -Path $file.FullName -Force
                $script:deleteCount++
                Write-Output "  Deleted orphan: $relativePath"
            }
        }
    }

    # Clean up empty directories left behind
    if (-not $Verify) {
        $dirs = Get-ChildItem -Path $DestDir -Recurse -Directory | Sort-Object { $_.FullName.Length } -Descending
        foreach ($dir in $dirs) {
            if ((Get-ChildItem -Path $dir.FullName -Force).Count -eq 0) {
                Remove-Item -Path $dir.FullName -Force
                Write-Output "  Removed empty dir: $($dir.Name)"
            }
        }
    }
}

# ---------------------------------------------------------------------------
# Runtime variant compilation (PowerShell equivalent of bash functions above)
# ---------------------------------------------------------------------------

function Strip-RationaleBlocks {
    param([string]$Content)
    $lines = $Content -split "`n"
    $result = [System.Collections.Generic.List[string]]::new()
    $skip = $false
    $prevBlank = $false

    foreach ($line in $lines) {
        if ($line -match '<!-- rationale:start -->') { $skip = $true; continue }
        if ($line -match '<!-- rationale:end -->') { $skip = $false; continue }
        if ($skip) { continue }
        if ($line -match '^[[:space:]]*$' -or $line.Trim() -eq '') {
            if (-not $prevBlank) { $result.Add(''); $prevBlank = $true }
            continue
        }
        $result.Add($line)
        $prevBlank = $false
    }

    while ($result.Count -gt 0 -and $result[$result.Count - 1] -eq '') {
        $result.RemoveAt($result.Count - 1)
    }

    return ($result -join "`n")
}

function Compile-RuntimeVariants {
    $templatesDir = Join-Path (Join-Path $repoRoot 'github-workflow') 'templates'
    $runtimeDir = Join-Path $templatesDir 'runtime'

    if (-not (Test-Path $templatesDir)) { return }

    $compiled = 0
    $expectedRuntime = @{}

    $templateFiles = Get-ChildItem -Path $templatesDir -Filter '*.md' -File -ErrorAction SilentlyContinue
    foreach ($srcFile in $templateFiles) {
        $filename = $srcFile.Name

        if ($filename -match '-rationale\.md$') { continue }

        $srcContent = Get-Content -Path $srcFile.FullName -Raw -Encoding UTF8
        if ($srcContent -notmatch '<!-- rationale:start -->') { continue }

        $expectedRuntime[$filename] = $true
        $dstFile = Join-Path $runtimeDir $filename
        $header = "<!-- COMPILED from templates/$filename -- edit the source, not this file. -->"
        $stripped = Strip-RationaleBlocks -Content ($srcContent -replace "`r`n", "`n")
        $fullContent = $header + "`n" + $stripped

        if ($Verify) {
            if (-not (Test-Path $dstFile)) {
                Write-Output "  MISSING: runtime/$filename"
                $script:driftFound = $true
            } else {
                $existing = (Get-Content -Path $dstFile -Raw -Encoding UTF8) -replace "`r`n", "`n"
                if ($existing.Trim() -ne $fullContent.Trim()) {
                    Write-Output "  DRIFT: runtime/$filename"
                    $script:driftFound = $true
                } else {
                    Write-Output "  OK: runtime/$filename"
                }
            }
        } else {
            if (-not (Test-Path $runtimeDir)) {
                New-Item -ItemType Directory -Path $runtimeDir -Force | Out-Null
            }
            $existing = ''
            if (Test-Path $dstFile) {
                $existing = (Get-Content -Path $dstFile -Raw -Encoding UTF8) -replace "`r`n", "`n"
            }
            if ($existing.Trim() -ne $fullContent.Trim()) {
                [System.IO.File]::WriteAllText($dstFile, $fullContent + "`n", [System.Text.UTF8Encoding]::new($false))
                Write-Output "  Compiled: runtime/$filename"
                $compiled++
            }
        }
    }

    if (Test-Path $runtimeDir) {
        $runtimeFiles = Get-ChildItem -Path $runtimeDir -Filter '*.md' -File -ErrorAction SilentlyContinue
        foreach ($rf in $runtimeFiles) {
            if (-not $expectedRuntime.ContainsKey($rf.Name)) {
                if ($Verify) {
                    Write-Output "  ORPHAN: runtime/$($rf.Name) (would be deleted)"
                    $script:driftFound = $true
                } else {
                    Remove-Item -Path $rf.FullName -Force
                    Write-Output "  Deleted orphan: runtime/$($rf.Name)"
                }
            }
        }
    }

    if (-not $Verify -and $compiled -gt 0) {
        Write-Output "  $compiled runtime variant(s) compiled."
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

    $script:expectedFiles = @{}

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

    if ($hasReferences) {
        $destReferencesDir = Join-Path (Join-Path $repoRoot $pluginName) 'references'
        Write-Output "  [references]"
        Sync-Directory -SourceDir $referencesDir -DestDir $destReferencesDir -PluginName $pluginName
    }

    # Clean up orphaned files from removed shared skills
    Write-Output "  [cleanup]"
    foreach ($skillDir in $skillDirs) {
        $destSkillDir = Join-Path $pluginSkillsDir $skillDir.Name
        Remove-OrphanedFiles -DestDir $destSkillDir -Label $skillDir.Name
    }
    if ($hasShared) {
        Remove-OrphanedFiles -DestDir (Join-Path $pluginSkillsDir '_shared') -Label '_shared'
    }
    if ($hasReferences) {
        Remove-OrphanedFiles -DestDir (Join-Path (Join-Path $repoRoot $pluginName) 'references') -Label 'references'
    }
}

Write-Output ""
Write-Output "[runtime variants]"
Compile-RuntimeVariants

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
    Write-Output "Synced $($script:syncCount) file(s), deleted $($script:deleteCount) orphan(s) across $($plugins.Count) plugin(s)."
    if ($script:syncCount -gt 0 -or $script:deleteCount -gt 0) {
        Write-Output ""
        Write-Output "REMINDER: Bump plugin version(s) if these changes are user-facing."
        foreach ($pluginName in $plugins) {
            $pluginJsonPath = Join-Path (Join-Path (Join-Path $repoRoot $pluginName) '.claude-plugin') 'plugin.json'
            if (Test-Path $pluginJsonPath) {
                $pluginJson = Get-Content -Path $pluginJsonPath -Raw -Encoding UTF8 | ConvertFrom-Json
                Write-Output "  $pluginName : current version $($pluginJson.version)"
            }
        }
    }
}
