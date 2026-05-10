$desktop = [Environment]::GetFolderPath("Desktop")
$shell = New-Object -ComObject WScript.Shell

$shortcuts = @(
    @{
        Name = "Auto-DevLog.lnk"
        Target = "C:\Users\29963\Desktop\daily_logs\launch_autodevlog.bat"
        Description = "Fast prompt-based development logging"
    },
    @{
        Name = "Auto-DevLog Editor.lnk"
        Target = "C:\Users\29963\Desktop\daily_logs\launch_autodevlog_editor.bat"
        Description = "Advanced editor-based development logging"
    }
)

foreach ($item in $shortcuts) {
    $shortcut = $shell.CreateShortcut((Join-Path $desktop $item.Name))
    $shortcut.TargetPath = $item.Target
    $shortcut.WorkingDirectory = "C:\Users\29963\Desktop\daily_logs"
    $shortcut.IconLocation = "%SystemRoot%\System32\shell32.dll,70"
    $shortcut.Description = $item.Description
    $shortcut.Save()
}
