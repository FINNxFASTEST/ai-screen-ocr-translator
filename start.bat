@echo off
echo [1/2] Pulling translation model...
docker model pull docker.io/ai/gemma3:4B-F16

echo [2/2] Pulling OCR model...
docker model pull docker.io/ai/gemma3n:2B-F16

echo.
echo Models ready. Starting app...
python main.py
