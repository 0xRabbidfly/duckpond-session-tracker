@echo off
rem Duck Pond app mode: the pool only (no Blender UI) in a normal maximised window, watching your live Claude Code sessions.
rem Add --fullscreen for borderless fullscreen. Ctrl+Space restores the panels, Alt+F11 toggles fullscreen, Alt+F4 quits.
"C:\Program Files\Blender Foundation\Blender 5.2\blender.exe" --window-maximized --python "%~dp0dev\launch.py" -- --app %*
