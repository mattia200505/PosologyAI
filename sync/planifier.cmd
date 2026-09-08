@echo off
REM ============================================================================
REM  Lanceur des cycles de synchronisation MedicSearch.
REM
REM  PYTHONIOENCODING est indispensable : la console Windows est en cp1252 et
REM  plusieurs modules du projet impriment des emojis. Sans cette variable, une
REM  execution dont la sortie est redirigee - ce qui est toujours le cas d'une
REM  tache planifiee - echoue sur UnicodeEncodeError avant d'avoir rien fait.
REM
REM  Usage :
REM      planifier.cmd quotidien
REM      planifier.cmd hebdomadaire
REM      planifier.cmd installer     (declare les deux taches planifiees)
REM ============================================================================

setlocal
set "RACINE=%~dp0.."
set "PYTHONIOENCODING=utf-8"
set "JOURNAL=%RACINE%\logs\sync"

if not exist "%JOURNAL%" mkdir "%JOURNAL%"

for /f "tokens=2 delims==" %%d in ('wmic os get localdatetime /value') do set "DT=%%d"
set "HORODATAGE=%DT:~0,8%_%DT:~8,6%"

if /i "%~1"=="quotidien" goto quotidien
if /i "%~1"=="hebdomadaire" goto hebdomadaire
if /i "%~1"=="installer" goto installer

echo Usage : planifier.cmd [quotidien^|hebdomadaire^|installer]
exit /b 1

:quotidien
REM Reconciliation par dumps, publication hors reseau, propagation.
REM Quelques secondes de reseau, aucune notice telechargee.
cd /d "%RACINE%"
python -m sync.cli cycle --daily >> "%JOURNAL%\quotidien_%HORODATAGE%.log" 2>&1
exit /b %errorlevel%

:hebdomadaire
REM Ajoute la sonde de revision : environ 12 000 notices, 30 minutes.
cd /d "%RACINE%"
python -m sync.cli cycle --weekly >> "%JOURNAL%\hebdomadaire_%HORODATAGE%.log" 2>&1
exit /b %errorlevel%

:installer
schtasks /create /tn "MedicSearch - sync quotidien" /tr "\"%~f0\" quotidien" ^
    /sc daily /st 03:00 /f
schtasks /create /tn "MedicSearch - sync hebdomadaire" /tr "\"%~f0\" hebdomadaire" ^
    /sc weekly /d SUN /st 02:00 /f
echo.
echo Taches declarees. Codes de sortie du cycle :
echo    0 = termine sans alerte critique
echo    1 = cycle refuse ou en echec
echo    2 = alerte critique levee
exit /b 0
