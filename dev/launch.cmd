@echo off
rem Double-click: live Claude Code sessions. Pass --stub for the demo fixture, --both for both.
set BLENDER="C:\Program Files\Blender Foundation\Blender 5.2\blender.exe"
%BLENDER% --python "%~dp0launch.py" -- %*
