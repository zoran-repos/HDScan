@echo off
setlocal
cd /d "%~dp0"

echo ============================================
echo   File Archive Catalog - Skeniranje
echo ============================================
echo.

set /p SCANPATH="Putanja za skeniranje (npr. D:\ ili D:\Fotografije): "
if "%SCANPATH%"=="" (
    echo.
    echo Putanja je obavezna.
    pause
    exit /b 1
)
rem Putanja koja se zavrsava na "\" (npr. C:\) lomi navodnike u komandi ispod
rem (Windows tumaci \" kao pobegli navodnik) - udvostruci zavrsni backslash.
if "%SCANPATH:~-1%"=="\" set SCANPATH=%SCANPATH%\

echo.
echo Nacin hesovanja fajlova:
echo   [1] sampled  - brzo, veliki fajlovi se hesuju delimicno  (PREPORUCENO)
echo   [2] full     - sporo, cita se ceo sadrzaj svakog fajla (najtacnije za duplikate)
echo   [3] none     - najbrze, bez hesa (bez detekcije duplikata)
set /p HASHCHOICE="Izaberi [1/2/3, Enter = 1]: "

if "%HASHCHOICE%"=="2" (
    set HASHMODE=full
) else if "%HASHCHOICE%"=="3" (
    set HASHMODE=none
) else (
    set HASHMODE=sampled
)

echo.
set /p SKIPEXCEL="Preskoci pravljenje Excel izvestaja posle skeniranja? [y/N]: "
set EXCELFLAG=
if /i "%SKIPEXCEL%"=="y" set EXCELFLAG=--no-excel

echo.
echo ----------------------------------------------
echo Pokrecem: scan "%SCANPATH%" --hash-mode %HASHMODE% %EXCELFLAG%
echo ----------------------------------------------
echo.

".venv\Scripts\python.exe" -m file_archive scan "%SCANPATH%" --hash-mode %HASHMODE% %EXCELFLAG%

echo.
pause
