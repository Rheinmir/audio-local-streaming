Add-Type -AssemblyName System.Windows.Forms
Add-Type -AssemblyName System.Drawing
Add-Type -AssemblyName Microsoft.VisualBasic

# Doc IP Mac tu config
$configFile = "D:\AudioStream\config.txt"
$macIP = "100.103.134.121"
if (Test-Path $configFile) {
    $saved = (Get-Content $configFile -Raw).Trim()
    if ($saved -match '^\d+\.\d+\.\d+\.\d+$') { $macIP = $saved }
}

# Hoi IP
$input = [Microsoft.VisualBasic.Interaction]::InputBox("IP cua Mac (Tailscale):", "AudioStream Sender", $macIP)
if ([string]::IsNullOrWhiteSpace($input)) { exit }
$macIP = $input.Trim()
$macIP | Set-Content $configFile

# Start sender
$proc = Start-Process python -ArgumentList "`"D:\AudioStream\send.py`" $macIP" -WindowStyle Hidden -PassThru

# Tray icon
$tray = New-Object System.Windows.Forms.NotifyIcon
$tray.Icon = [System.Drawing.SystemIcons]::Application
$tray.Text = "AudioStream -> $macIP"
$tray.Visible = $true
$tray.ShowBalloonTip(3000, "AudioStream", "Dang stream toi $macIP", [System.Windows.Forms.ToolTipIcon]::Info)

# Menu
$menu = New-Object System.Windows.Forms.ContextMenuStrip
$infoItem = $menu.Items.Add("Streaming -> $macIP")
$infoItem.Enabled = $false
$menu.Items.Add("-") | Out-Null
$stopItem = $menu.Items.Add("Stop & Exit")

$stopItem.add_Click({
    $tray.Visible = $false
    $proc | Stop-Process -Force -ErrorAction SilentlyContinue
    [System.Windows.Forms.Application]::Exit()
})

$tray.ContextMenuStrip = $menu
$tray.add_DoubleClick({
    [System.Windows.Forms.MessageBox]::Show(
        "Dang stream audio toi:`n$macIP`n`nLatency: ~25ms",
        "AudioStream"
    ) | Out-Null
})

Register-EngineEvent -SourceIdentifier PowerShell.Exiting -Action {
    $proc | Stop-Process -Force -ErrorAction SilentlyContinue
}

[System.Windows.Forms.Application]::Run()
