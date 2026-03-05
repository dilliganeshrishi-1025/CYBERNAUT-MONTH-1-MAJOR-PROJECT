# Tech Job Portal (starter)

This is a starter Flask project that demonstrates a simple tech job portal layout and a respectful example scraper. It does NOT include production-ready authentication, database models, or large-scale scraping.

Setup (Windows PowerShell):

```powershell
python -m venv .venv; .\.venv\Scripts\Activate.ps1
pip install -r requirements.txt
python app.py
```

Visit http://127.0.0.1:5000/ in your browser. The `/scrape` endpoint runs a sample scraper against a permissive job listing site and returns JSON.

Notes:
- Do NOT scrape LinkedIn/Glassdoor/Indeed without their permission or their public APIs. Their ToS forbid scraping and they actively block bots.
- For production: add database models, authentication, rate-limiting, error handling, tests, and a proper scheduler (Celery + Redis) for high-volume scraping.
