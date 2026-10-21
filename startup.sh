#!/bin/bash
# Azure App Service (Linux, Python) runs this as the startup command.
# Set in: App Service -> Configuration -> General settings -> Startup Command
python -m uvicorn app.main:app --host 0.0.0.0 --port 8000
