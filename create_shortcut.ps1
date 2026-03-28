$WshShell = New-Object -ComObject WScript.Shell
$Desktop = [Environment]::GetFolderPath('Desktop')
$Shortcut = $WshShell.CreateShortcut("$Desktop\AudioStream.lnk")
$Shortcut.TargetPath = "D:\AudioStream\AudioStream.vbs"
$Shortcut.IconLocation = "C:\Windows\System32\imageres.dll,109"
$Shortcut.Description = "AudioStream - Stream audio to Mac"
$Shortcut.Save()
Write-Host "Shortcut created on Desktop"
