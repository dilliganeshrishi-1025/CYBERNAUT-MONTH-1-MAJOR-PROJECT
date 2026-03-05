from flask import Flask, render_template, request, redirect, url_for, jsonify
from config import Config
from flask_sqlalchemy import SQLAlchemy
from sqlalchemy.exc import IntegrityError
import requests
from bs4 import BeautifulSoup
from urllib.parse import urljoin
from apscheduler.schedulers.background import BackgroundScheduler
import atexit
from flask import flash

app = Flask(__name__)
app.config.from_object(Config)
db = SQLAlchemy(app)

# Job model for persistence
class Job(db.Model):
    id = db.Column(db.Integer, primary_key=True)
    title = db.Column(db.String(256))
    company = db.Column(db.String(256))
    url = db.Column(db.String(1024), unique=True, index=True)

    def to_dict(self):
        return {'title': self.title, 'company': self.company, 'url': self.url}

# create tables if they don't exist
with app.app_context():
    db.create_all()


@app.route('/')
def index():
    job_count = len(globals().get('SCRAPED_JOBS', []))
    return render_template('index.html', job_count=job_count)


@app.route('/register')
def register():
    return render_template('register.html')


@app.route('/login')
def login():
    return render_template('login.html')


@app.route('/jobs')
def jobs():
    # In a real app we'd fetch from DB; here use the in-memory cached scrape
    jobs_list = globals().get('SCRAPED_JOBS', [])
    # simple query filtering via ?q=search
    q = request.args.get('q', '').strip().lower()
    if q:
        def match(job):
            return any(q in (str(job.get(k) or '')).lower() for k in ('title', 'company', 'url'))
        jobs_list = [j for j in jobs_list if match(j)]
    return render_template('jobs.html', jobs=jobs_list, q=request.args.get('q', ''))


@app.route('/run-scrape', methods=['POST'])
def run_scrape():
    jobs = sample_scrape()
    flash(f"Scraped {len(jobs)} jobs", 'success')
    return redirect(url_for('jobs'))


def sample_scrape():
    """Scrape the RealPython fake jobs page (public test data) to extract a
    small list of job postings for demo purposes.
    """
    url = 'https://realpython.github.io/fake-jobs/'
    try:
        resp = requests.get(url, timeout=10, headers={'User-Agent': 'tech-job-portal-bot/1.0'})
        resp.raise_for_status()
        soup = BeautifulSoup(resp.text, 'html.parser')
        cards = soup.select('div.card')
        jobs = []
        # try to collect more cards from the test page (it contains many sample jobs)
        for card in cards[:100]:
            title_el = card.select_one('h2.title')
            company_el = card.select_one('h3.company')
            apply_link = None
            for a in card.select('a.card-footer-item'):
                if 'Apply' in a.get_text():
                    apply_link = a.get('href')
                    break
            title = title_el.get_text(strip=True) if title_el else None
            company = company_el.get_text(strip=True) if company_el else None
            # normalize and require a URL to be useful
            if apply_link:
                apply_link = urljoin(url, apply_link)
            if apply_link and title:
                jobs.append({'title': title, 'company': company, 'url': apply_link})
            # If RealPython didn't yield many jobs (rare), attempt a secondary source
            if len(jobs) < 50:
                try:
                    alt_url = 'https://remoteok.com/remote-dev-jobs'
                    r2 = requests.get(alt_url, timeout=8, headers={'User-Agent': 'tech-job-portal-bot/1.0'})
                    r2.raise_for_status()
                    soup2 = BeautifulSoup(r2.text, 'html.parser')
                    for tr in soup2.select('tr.job')[:100]:
                        # conservative parse of remoteok entries
                        t = tr.select_one('h2')
                        c = tr.select_one('.company')
                        link = tr.get('data-url')
                        title = t.get_text(strip=True) if t else None
                        company = c.get_text(strip=True) if c else None
                        url_link = ('https://remoteok.com' + link) if link else None
                        if url_link and title:
                            jobs.append({'title': title, 'company': company, 'url': url_link})
                except Exception:
                    pass

            # deduplicate by URL while preserving order
            seen = set()
            unique_jobs = []
            for j in jobs:
                u = j.get('url')
                if not u or u in seen:
                    continue
                seen.add(u)
                unique_jobs.append(j)

            print(f"Scraped {len(unique_jobs)} jobs (unique) from {url}")
            # persist into the database (upsert by URL)
            added = 0
            with app.app_context():
                for j in unique_jobs:
                    if not j.get('url'):
                        continue
                    exists = Job.query.filter_by(url=j['url']).first()
                    if exists:
                        # update basic fields
                        exists.title = j.get('title') or exists.title
                        exists.company = j.get('company') or exists.company
                    else:
                        new = Job(title=j.get('title'), company=j.get('company'), url=j.get('url'))
                        db.session.add(new)
                        added += 1
                try:
                    db.session.commit()
                except IntegrityError:
                    db.session.rollback()
            # refresh cache from DB
            with app.app_context():
                all_jobs = Job.query.order_by(Job.id.desc()).all()
            global SCRAPED_JOBS
            SCRAPED_JOBS = [j.to_dict() for j in all_jobs]
            return jobs
    except Exception as e:
        print('Scrape failed:', e)
        return []


@app.route('/scrape')
def scrape_route():
    jobs = sample_scrape()
    return jsonify({'count': len(jobs), 'jobs': jobs})


@app.route('/seed-sample-jobs', methods=['POST'])
def seed_sample_jobs():
    """Force-insert many sample jobs from the RealPython fake page into the DB."""
    url = 'https://realpython.github.io/fake-jobs/'
    try:
        resp = requests.get(url, timeout=10, headers={'User-Agent': 'tech-job-portal-bot/1.0'})
        resp.raise_for_status()
        soup = BeautifulSoup(resp.text, 'html.parser')
        cards = soup.select('div.card')
        inserted = 0
        with app.app_context():
            for card in cards:
                title_el = card.select_one('h2.title')
                company_el = card.select_one('h3.company')
                footer_links = card.select('a.card-footer-item')
                apply_link = None
                if footer_links:
                    apply_link = footer_links[-1].get('href')
                title = title_el.get_text(strip=True) if title_el else None
                company = company_el.get_text(strip=True) if company_el else None
                if not title or not apply_link:
                    continue
                full_link = urljoin(url, apply_link)
                exists = Job.query.filter_by(url=full_link).first()
                if not exists:
                    db.session.add(Job(title=title, company=company, url=full_link))
                    inserted += 1
            try:
                db.session.commit()
            except IntegrityError:
                db.session.rollback()
        return jsonify({'inserted': inserted, 'total': Job.query.count()})
    except Exception as e:
        return jsonify({'error': str(e)}), 500


if __name__ == '__main__':
    # Start scheduler to run scraper every 6 hours
    scheduler = BackgroundScheduler()
    scheduler.add_job(func=sample_scrape, trigger='interval', hours=6)
    scheduler.start()
    atexit.register(lambda: scheduler.shutdown())
    app.run(debug=True)





