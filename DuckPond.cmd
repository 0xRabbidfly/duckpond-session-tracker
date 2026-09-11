@echo off
rem Duck Pond app mode: the pool only (no Blender UI) in a normal maximised window, watching your live Claude Code sessions.
rem Add --fullscreen for borderless fullscreen. Ctrl+Space restores the panels, Alt+F11 toggles fullscreen, Alt+F4 quits.
rem Blender is found from DUCKPOND_BLENDER, then the default install folder, then PATH.
setlocal
set "BLENDER=%DUCKPOND_BLENDER%"
if not defined BLENDER if exist "%ProgramFiles%\Blender Foundation\Blender 5.2\blender.exe" set "BLENDER=%ProgramFiles%\Blender Foundation\Blender 5.2\blender.exe"
if not defined BLENDER set "BLENDER=blender"
"%BLENDER%" --window-maximized --python "%~dp0dev\launch.py" -- --app %*
