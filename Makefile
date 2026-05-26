.PHONY: install test test-watch lint clean setup run seed-mock seed-sentry activate-scenario

PROJECT_DIR := investigator
VENV := .venv
PYTHON := $(VENV)/bin/python

$(VENV)/bin/python:
	python3 -m venv $(VENV)

install: $(VENV)/bin/python
	$(VENV)/bin/pip install --upgrade pip
	$(VENV)/bin/pip install -r requirements.txt

test:
	$(PYTHON) -m pytest $(PROJECT_DIR)/tests/ -v --tb=short

test-watch:
	$(PYTHON) -m pytest $(PROJECT_DIR)/tests/ -v --tb=short -f

test-coverage:
	$(PYTHON) -m pytest $(PROJECT_DIR)/tests/ -v --tb=short --cov=$(PROJECT_DIR) --cov-report=term-missing

lint:
	$(PYTHON) -m py_compile $(PROJECT_DIR)/agent/coral_client.py

clean:
	find . -type d -name __pycache__ -exec rm -rf {} + 2>/dev/null || true
	find . -type f -name '*.pyc' -delete
	rm -rf .pytest_cache

setup: install
	mkdir -p $(PROJECT_DIR)/data/reports
	cp -n .env.example .env 2>/dev/null || true
	@echo "Setup complete. Edit .env with your API keys."

seed-mock:
	$(PYTHON) -m $(PROJECT_DIR).scripts.generate_mock
	$(PYTHON) -m $(PROJECT_DIR).scripts.generate_mock --activate 1

seed-sentry:
	$(PYTHON) -m $(PROJECT_DIR).scripts.seed_sentry

activate-scenario:
	$(PYTHON) -m $(PROJECT_DIR).scripts.generate_mock --activate $(SCENARIO)

run:
	$(PYTHON) -m $(PROJECT_DIR).bot.handler

verify:
	$(PYTHON) -m pytest $(PROJECT_DIR)/tests/ -v --tb=short
