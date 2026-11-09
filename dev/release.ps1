# Publish a Callbooker release: tag, attach assets, mark latest.
# Run from the repo root:  dev\release.bat 1.12   (or: powershell -File dev\release.ps1 -Version 1.12)
#
# - Downloads Callbooker.exe from the GitHub Actions run if it is not in the folder
# - Creates/pushes the tag if missing
# - Reuses an existing draft/prerelease for the tag, or creates a new release
# - Uploads Callbooker.exe, Callbooker.cfg.template, LICENSE (replacing same-named assets)
# - Publishes it as the latest release

param(
    [string]$Version = "1.12",
    [string]$Repo    = "s55oo/N1MM_callbook",
    [string]$RunId   = "41925834753",   # Actions run that built Callbooker.exe
    [switch]$Download                   # force re-download of the exe from the run
)

$ErrorActionPreference = "Stop"
$tag = "v$Version"

function Fail($msg) { Write-Host "ERROR: $msg" -ForegroundColor Red; exit 1 }
function Check($what) { if ($LASTEXITCODE -ne 0) { Fail "$what failed (exit $LASTEXITCODE)" } }

if (-not (Test-Path ".git")) { Fail "run this from the repo folder (no .git here)" }

cmd /c "gh auth status >nul 2>&1"
if ($LASTEXITCODE -ne 0) { Fail "gh is not logged in - run 'gh auth login' (or set a valid GH_TOKEN)" }

Write-Host "== git pull"
cmd /c "git pull --ff-only 2>&1"; Check "git pull"

# 1. the exe
if ($Download -or -not (Test-Path "Callbooker.exe")) {
    Write-Host "== downloading Callbooker.exe from run $RunId"
    if (Test-Path "Callbooker.exe") { Remove-Item "Callbooker.exe" -Force }
    gh run download $RunId -R $Repo -n Callbooker.exe -D .; Check "gh run download"
}
foreach ($f in "Callbooker.exe", "Callbooker.cfg.template", "LICENSE") {
    if (-not (Test-Path $f)) { Fail "$f not found in this folder" }
}
$hash = (Get-FileHash "Callbooker.exe" -Algorithm SHA256).Hash
Write-Host "Callbooker.exe SHA-256: $hash"

# 2. the tag
cmd /c "git rev-parse -q --verify refs/tags/$tag >nul 2>&1"
if ($LASTEXITCODE -ne 0) { Write-Host "== creating tag $tag"; cmd /c "git tag $tag 2>&1"; Check "git tag" }
cmd /c "git push origin $tag >nul 2>&1"   # fine if it is already on the remote
Write-Host "tag $tag is on origin"

# 3. find or create the release (drafts are only visible by id, not by tag)
$rels = gh api "repos/$Repo/releases?per_page=100" | ConvertFrom-Json
Check "listing releases"
$rel = $rels | Where-Object { $_.tag_name -eq $tag } | Select-Object -First 1
if ($rel) {
    Write-Host "== reusing existing release id $($rel.id) (draft=$($rel.draft), prerelease=$($rel.prerelease))"
} else {
    Write-Host "== creating release $tag (as draft until assets are up)"
    $body = "Callbooker $Version`n`nCallbooker.exe SHA-256: $hash`n`nThe exe is unsigned and may trigger an antivirus warning; see the README changelog."
    $rel = gh api -X POST "repos/$Repo/releases" -f tag_name=$tag -f name=$tag -f body=$body -F draft=true | ConvertFrom-Json
    Check "creating release"
}
$id = $rel.id

# 4. assets (replace same-named ones)
$existing = (gh api "repos/$Repo/releases/$id" | ConvertFrom-Json).assets
foreach ($f in "Callbooker.exe", "Callbooker.cfg.template", "LICENSE") {
    $old = $existing | Where-Object { $_.name -eq $f }
    if ($old) { gh api -X DELETE "repos/$Repo/releases/assets/$($old.id)" | Out-Null }
    Write-Host "== uploading $f"
    gh api -X POST "https://uploads.github.com/repos/$Repo/releases/$id/assets?name=$f" `
        -H "Content-Type: application/octet-stream" --input $f | Out-Null
    Check "uploading $f"
}

# 5. publish as latest
Write-Host "== publishing"
gh api -X PATCH "repos/$Repo/releases/$id" -F draft=false -F prerelease=false -f make_latest=true | Out-Null
Check "publishing"

Write-Host ""
Write-Host "Done: https://github.com/$Repo/releases/tag/$tag" -ForegroundColor Green
gh release view $tag -R $Repo
