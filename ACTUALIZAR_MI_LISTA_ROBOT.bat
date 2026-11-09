@echo off
title ROBOT ACTUALIZADOR OMEGA VIP - LEONARDO
color 0A
cd /d "%~dp0"
echo ======================================================================
echo    EJECUTANDO ROBOT DE AUDITORIA, DESCUBRIMIENTO Y DESDUPLICACION
echo ======================================================================
echo.
python "robot_actualizador_leo.py"
echo.
echo ======================================================================
echo    PROCESO FINALIZADO. TU LISTA MAESTRA HA SIDO ACTUALIZADA.
echo ======================================================================
pause
