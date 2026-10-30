param(
    [Parameter(Mandatory = $true, Position = 0, ValueFromRemainingArguments = $true)]
    [string[]]$ConfigFiles,

    [string]$BlenderExe,

    [switch]$ValidateOnly
)

if ($BlenderExe) {
    if (-not (Test-Path -LiteralPath $BlenderExe -PathType Leaf)) {
        Write-Error "Blender executable not found: $BlenderExe"
        exit 1
    }
    $resolvedBlender = (Resolve-Path -LiteralPath $BlenderExe).Path
} else {
    $blenderCommand = Get-Command blender.exe -CommandType Application -ErrorAction SilentlyContinue |
        Select-Object -First 1

    if ($blenderCommand) {
        $resolvedBlender = $blenderCommand.Source
    } else {
        $installRoots = @(
            $env:ProgramFiles,
            ${env:ProgramFiles(x86)},
            (Join-Path $env:LOCALAPPDATA "Programs")
        ) | Where-Object { $_ }

        $candidates = foreach ($root in $installRoots) {
            Get-ChildItem `
                -Path (Join-Path $root "Blender Foundation\Blender*\blender.exe") `
                -File `
                -ErrorAction SilentlyContinue |
                Select-Object -ExpandProperty FullName
        }

        $preferred = $candidates |
            Where-Object { $_ -match "\\Blender 5\.2(?:[^\\]*)\\blender\.exe$" } |
            Select-Object -First 1
        if ($preferred) {
            $resolvedBlender = $preferred
        } else {
            $resolvedBlender = $candidates | Select-Object -First 1
        }
    }
}

if (-not $resolvedBlender) {
    Write-Error @"
Blender was not found on PATH or in a standard Windows installation folder.
Install Blender 5.2, add its folder to PATH, or pass its executable explicitly:
  .\run_blender.ps1 config_samples\bunny_monochrome.ini -BlenderExe "C:\path\to\blender.exe"
"@
    exit 1
}

$resolvedConfigs = @(
    foreach ($config in $ConfigFiles) {
        if (-not [System.IO.Path]::IsPathRooted($config)) {
            $config = Join-Path (Get-Location) $config
        }
        if (-not (Test-Path -LiteralPath $config -PathType Leaf)) {
            Write-Error "Configuration file not found: $config"
            exit 1
        }
        (Resolve-Path -LiteralPath $config).Path
    }
)

Write-Host "Using Blender: $resolvedBlender"

$blenderArguments = @("-b", "-P", "render_object.py", "--")
if ($ValidateOnly) {
    $blenderArguments += "--validate-only"
}
$blenderArguments += $resolvedConfigs

Push-Location $PSScriptRoot
& $resolvedBlender @blenderArguments
$blenderExitCode = $LASTEXITCODE
Pop-Location
exit $blenderExitCode
