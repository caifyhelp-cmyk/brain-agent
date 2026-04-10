@echo off
title 뇌 에이전트 시작 중...

REM Flask 앱 백그라운드 실행
start /MIN "" python "C:\Users\조경일\thinking_agent\app.py"

REM 앱 뜰 때까지 잠깐 대기
timeout /t 5 /nobreak > nul

REM ngrok 터널 실행
start /MIN "" ngrok http 5000

REM URL 확인용 (10초 후 ngrok 대시보드)
timeout /t 10 /nobreak > nul
start http://localhost:4040

echo 뇌 에이전트 + ngrok 실행 완료
echo URL 확인: http://localhost:4040
