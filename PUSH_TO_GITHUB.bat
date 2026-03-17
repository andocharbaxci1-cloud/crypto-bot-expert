@echo off
title GitHub Auto-Push
cd /d "%~dp0"
echo Adding changes...
git add .
echo Committing changes...
git commit -m "Auto-update: %date% %time%"
echo Pushing to GitHub...
git push origin master
echo Done! Render will now update your bot.
pause
