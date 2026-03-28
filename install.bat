@echo off
echo === AudioStream - Install dependencies ===
echo.
echo [Windows - sender]
pip install pyaudiowpatch sounddevice numpy
echo.
echo [Mac - receiver: chay tren Mac]
echo   pip install sounddevice numpy
echo.
echo Xong! Dung:
echo   Windows: python send.py ^<IP_MAC^>
echo   Mac:     python recv.py
echo.
pause
