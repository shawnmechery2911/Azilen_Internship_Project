$ErrorActionPreference = 'Stop'
Remove-Item -Force -ErrorAction SilentlyContinue .\mapping_store.json
Remove-Item -Force -ErrorAction SilentlyContinue .\exceptions.json
Remove-Item -Force -ErrorAction SilentlyContinue .\processing_log.json, .\ai_usage.json, .\drift_counts.json, .\validation_rules.json
py .\seed.py
