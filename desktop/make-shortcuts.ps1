$exe = "C:\Users\GabeMaher\Documents\Development\Vaults\luminize-vault\Development\apps\parker\dist\Parker\Parker.exe"
$icon = "C:\Users\GabeMaher\Documents\Development\Vaults\luminize-vault\Development\apps\parker\desktop\assets\icon.ico"
$desktop = [Environment]::GetFolderPath("Desktop")
$startMenu = "$env:APPDATA\Microsoft\Windows\Start Menu\Programs"

$ws = New-Object -ComObject WScript.Shell

# Remove any old "Compliance Agent" shortcuts (rename leftovers)
foreach ($old in @("$desktop\Compliance Agent.lnk", "$startMenu\Compliance Agent.lnk")) {
    if (Test-Path $old) { Remove-Item $old -Force; Write-Output "Removed old shortcut: $old" }
}

# Desktop shortcut
$s1 = $ws.CreateShortcut("$desktop\Parker.lnk")
$s1.TargetPath = $exe
$s1.WorkingDirectory = Split-Path $exe
$s1.IconLocation = "$icon,0"
$s1.Description = "Parker - e-commerce compliance agent - EU/US/UK regulations, catalog ingestion"
$s1.Save()

# Start Menu shortcut
$s2 = $ws.CreateShortcut("$startMenu\Parker.lnk")
$s2.TargetPath = $exe
$s2.WorkingDirectory = Split-Path $exe
$s2.IconLocation = "$icon,0"
$s2.Description = "Parker - e-commerce compliance agent - EU/US/UK regulations, catalog ingestion"
$s2.Save()

Write-Output "Desktop shortcut: $desktop\Parker.lnk"
Write-Output "Start Menu shortcut: $startMenu\Parker.lnk"
if (Test-Path "$desktop\Parker.lnk") { Write-Output "OK: desktop link exists" }
if (Test-Path "$startMenu\Parker.lnk") { Write-Output "OK: start menu link exists" }
