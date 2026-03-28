Add-Type -AssemblyName System.Windows.Forms
Add-Type -AssemblyName System.Drawing

# Kill tat ca python process dang chiem port 8443 hoac 8765
$pids = @()
try {
    $pids = (Get-NetTCPConnection -LocalPort 8443,8765 -ErrorAction SilentlyContinue).OwningProcess |
            Where-Object { $_ -gt 0 } | Sort-Object -Unique
} catch {}
foreach ($id in $pids) {
    Stop-Process -Id $id -Force -ErrorAction SilentlyContinue
}
if ($pids.Count -gt 0) { Start-Sleep -Milliseconds 800 }

# Start server (hien cua so de xem log)
$proc = Start-Process python -ArgumentList "`"D:\AudioStream\web\server.py`"" `
    -WorkingDirectory "D:\AudioStream\web" `
    -WindowStyle Normal -PassThru

# Doi 4 giay cho server san sang
Start-Sleep -Seconds 4

# Kiem tra server con song khong
if ($proc.HasExited) {
    [System.Windows.Forms.MessageBox]::Show(
        "Server khoi dong that bai!`nKiem tra console de xem loi.",
        "AudioStream Error", 0, 16) | Out-Null
    exit
}

# Mo browser
Start-Process "https://localhost:8443"

# Tray icon
$tray = New-Object System.Windows.Forms.NotifyIcon
$tray.Icon = [System.Drawing.SystemIcons]::Application
$tray.Text = "AudioStream :8443"
$tray.Visible = $true

# Menu
$menu = New-Object System.Windows.Forms.ContextMenuStrip
$openItem = $menu.Items.Add("Mo AudioStream")
$stopItem = $menu.Items.Add("Dung & Thoat")

$openItem.add_Click({ Start-Process "https://localhost:8443" })
$stopItem.add_Click({
    $tray.Visible = $false
    $proc | Stop-Process -Force -ErrorAction SilentlyContinue
    [System.Windows.Forms.Application]::Exit()
})

$tray.ContextMenuStrip = $menu
$tray.add_DoubleClick({ Start-Process "https://localhost:8443" })

Register-EngineEvent -SourceIdentifier PowerShell.Exiting -Action {
    $proc | Stop-Process -Force -ErrorAction SilentlyContinue
}

[System.Windows.Forms.Application]::Run()
