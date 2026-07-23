# Script de mise à jour pour PiKaraoke sur Windows
# Ce script est conçu pour être lancé de manière détachée par l'application.

$ErrorActionPreference = "Stop"

# Attendre quelques secondes que l'application principale se ferme
Start-Sleep -Seconds 5

Write-Host "--- PiKaraoke Updater ---"

# Mettre à jour l'application avec uv
Write-Host "Upgrading pikaraoke via uv..."
uv tool upgrade pikaraoke
if ($LASTEXITCODE -ne 0) {
    Write-Error "Failed to upgrade pikaraoke via uv tool. The system will not be restarted."
    Start-Sleep -Seconds 10
    exit 1
}

Write-Host "Update complete. Restarting system..."
Restart-Computer -Force