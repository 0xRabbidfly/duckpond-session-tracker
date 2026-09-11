@echo off
rem Dev launch: live Claude Code sessions with the normal Blender UI. Pass --stub for the demo fixture, --both for both.
rem Blender is found from DUCKPOND_BLENDER, then the default install folder, then PATH.
setlocal
set "BLENDER=%DUCKPOND_BLENDER%"
if not defined BLENDER if exist "%ProgramFiles%\Blender Foundation\Blender 5.2\blender.exe" set "BLENDER=%ProgramFiles%\Blender Foundation\Blender 5.2\blender.exe"
if not defined BLENDER set "BLENDER=blender"
"%BLENDER%" --python "%~dp0launch.py" -- %*
