@echo off
rem job launcher for Windows: runs bin\job with the first Python 3 found.
where py >nul 2>nul && goto :py
where python >nul 2>nul && goto :python
where python3 >nul 2>nul && goto :python3
echo Python 3 was not found. Install it from https://www.python.org/downloads/ and try again. 1>&2
exit /b 1
:py
py -3 "%~dp0job" %*
exit /b %errorlevel%
:python
python "%~dp0job" %*
exit /b %errorlevel%
:python3
python3 "%~dp0job" %*
exit /b %errorlevel%
