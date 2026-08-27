[CmdletBinding()]
param(
    [Parameter(Mandatory = $true)]
    [string]$StagingDirectory
)

$ErrorActionPreference = 'Stop'

$expected = @{
    'cantinho_estudos_v2.html' = '3ca391d210e5edca9c8a05d42399c3010b915d32392dd0ca72230fb8dc2b3733'
    'Simbolo.png' = '73092ca27b8a9d20f4c376f00f702c120404886454b89f1decad06371205540a'
    'Mini-Icone.png' = 'd7a170e345c7e865a009d39ba4057a8e54737a3f0054e8eb14d7e7132dc30a91'
    'MCP-Jurisprudencio.zip' = '9ea64f8a04a511ebf569e07ab8c6cee8bcb8202d1fb54f854a1c58d743618800'
}

foreach ($entry in $expected.GetEnumerator()) {
    $path = Join-Path $StagingDirectory $entry.Key
    if (-not (Test-Path -LiteralPath $path -PathType Leaf)) {
        throw "Missing artifact: $($entry.Key)"
    }
    $actual = (Get-FileHash -Algorithm SHA256 -LiteralPath $path).Hash.ToLowerInvariant()
    if ($actual -ne $entry.Value) {
        throw "Hash mismatch for $($entry.Key): expected $($entry.Value), got $actual"
    }
}

$htmlPath = Join-Path $StagingDirectory 'cantinho_estudos_v2.html'
$html = Get-Item -LiteralPath $htmlPath
$lines = ([System.IO.File]::ReadLines($html.FullName) | Measure-Object).Count
if ($html.Length -ne 288409 -or $lines -ne 3852) {
    throw "HTML baseline mismatch: bytes=$($html.Length), lines=$lines"
}

'ARTIFACT_VERIFICATION=PASS'

