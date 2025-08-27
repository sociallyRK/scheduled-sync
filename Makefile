.PHONY: check run clean venv

check:
	@git fetch origin
	@git diff --quiet origin/main -- app.py index.html && echo "OK: matches remote" || echo "DIFF: differs from remote"
	@git log -n 1 --pretty='[%h] %ad %an: %s' --date=iso -- app.py
	@git log -n 1 --pretty='[%h] %ad %an: %s' --date=iso -- index.html

venv:
	@python3 -m venv .venv
	@. .venv/bin/activate && pip install -r requirements.txt

run: venv
	@. .venv/bin/activate && python app.py

clean:
	@rm -rf .venv
gunicorn: venv
	@. .venv/bin/activate && gunicorn -w 2 -b 0.0.0.0:5000 app:app


lint: venv
	@. .venv/bin/activate && pip install -q ruff && ruff check .

format: venv
	@. .venv/bin/activate && pip install -q black && black .

deploy:
	@git push origin main
