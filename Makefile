# Makefile for operating the remarkbox server using either PyPI packages or source

# Variables (using the current working directory)
VENV_DIR = $(shell pwd)/env
DATA_DIR = $(shell pwd)/data
CONFIG_FILE = development.ini
CONFIG_URL = https://git.unturf.com/engineering/remarkbox/remarkbox/-/raw/main/development.ini

PYTHON   = $(VENV_DIR)/bin/python
PIP      = $(VENV_DIR)/bin/pip
PSERVE   = $(VENV_DIR)/bin/pserve
ALEMBIC  = $(VENV_DIR)/bin/alembic
RB_INIT  = $(VENV_DIR)/bin/remarkbox_init_db

# Default target: PyPI installation followed by server start.
all: install-from-pypi serve

# -----------------------------------------------------------------------------
# Environment Setup Targets (using file targets to avoid re-running)
# -----------------------------------------------------------------------------

# Virtual environment target: creates env if $(VENV_DIR)/bin/activate doesn't exist.
$(VENV_DIR)/bin/activate:
	@echo "Creating virtual environment in $(VENV_DIR)..."
	python3 -m venv $(VENV_DIR)
	@echo "Installing setuptools (required by Pyramid, not bundled in Python 3.12+ venvs)..."
	$(PIP) install 'setuptools<81'

venv: $(VENV_DIR)/bin/activate

# Configuration file target: creates data directory and downloads config if it doesn't exist.
$(DATA_DIR)/$(CONFIG_FILE):
	@echo "Creating data directory in $(DATA_DIR) and downloading configuration file..."
	mkdir -p $(DATA_DIR)
	cd $(DATA_DIR) && wget -O $(CONFIG_FILE) $(CONFIG_URL)

config: $(DATA_DIR)/$(CONFIG_FILE)

# -----------------------------------------------------------------------------
# Package Installation Targets for PyPI Installation
# -----------------------------------------------------------------------------

# Install remarkbox core package from PyPI
install-core: venv
	@echo "Installing remarkbox core package from PyPI..."
	$(PIP) install remarkbox

# Install development extras from PyPI
install-dev: venv
	@echo "Installing remarkbox development extras from PyPI..."
	$(PIP) install remarkbox[dev]

# Install optional themes (from Git) via PyPI
install-themes: venv
	@echo "Installing optional themes from Git..."
	$(PIP) install git+https://git.unturf.com/engineering/remarkbox/remarkbox-theme-meta.git
	$(PIP) install git+https://git.unturf.com/engineering/remarkbox/remarkbox-westworld.git

# Combined installation target for PyPI
install: install-core install-dev install-themes

# -----------------------------------------------------------------------------
# Package Installation Targets for Source Installation
# -----------------------------------------------------------------------------

# Install remarkbox from source (editable mode) plus dev, test, and themes
install-source-dev-and-test: venv install-themes
	@echo "Ensuring setuptools is installed (required by Pyramid on Python 3.12+)..."
	$(PIP) install 'setuptools<81'
	@echo "Installing remarkbox from source (editable mode)..."
	$(PIP) install --editable .
	$(PIP) install --upgrade -r requirements-dev.txt
	$(PIP) install --upgrade -r requirements-test.txt

# Supply-chain: external PyPI deps install from requirements-prod.lock (exact
# versions + SHA256, --require-hashes). First-party git themes are not hashable;
# 'pip install .' resolves them (SHA-pinned by their own repos) without
# re-resolving the already-satisfied, hash-pinned PyPI deps. Regenerate the lock
# with: make pins-lock
install-source-prod: venv install-themes
	@echo "Ensuring setuptools is installed (required by Pyramid on Python 3.12+)..."
	$(PIP) install 'setuptools<81'
	@echo "Deleting tests from source code for production..."
	rm -rf remarkbox/tests
	@echo "Installing pinned, hash-verified PyPI dependencies (supply-chain)..."
	$(PIP) install --require-hashes -r requirements-prod.lock
	@echo "Installing remarkbox from source; first-party git themes resolve here..."
	$(PIP) install .

# Regenerate requirements-prod.lock from requirements-prod.in (latest compatible),
# then strip the unhashable first-party git theme deps.
pins-lock:
	uv pip compile --generate-hashes --upgrade --python-version 3.12 \
		-o requirements-prod.lock requirements-prod.in
	python3 scripts/strip-vcs-from-lock.py requirements-prod.lock


# -----------------------------------------------------------------------------
# Database Initialization and Server Targets
# -----------------------------------------------------------------------------

# Initialize the database using the configuration file
init-db: venv config
	@echo "Initializing the remarkbox database..."
	$(RB_INIT) $(DATA_DIR)/$(CONFIG_FILE)
	$(ALEMBIC) -c $(DATA_DIR)/$(CONFIG_FILE) stamp head

# Create a new Alembic migration with a proper auto-generated revision ID.
# Usage: make migration m="description of change"
# Autogenerate compares current models against DB schema and writes the diff.
# ALWAYS use this — NEVER hand-write revision IDs.
migration: venv config
	@if [ -z "$(m)" ]; then echo "ERROR: provide a message: make migration m=\"add foo column\""; exit 1; fi
	$(ALEMBIC) -c $(DATA_DIR)/$(CONFIG_FILE) revision --autogenerate -m "$(m)"

# Verified, WAL-safe, timestamped backup of the SQLite database behind
# the ini's sqlalchemy.url. Our databases run journal_mode=WAL, so a bare
# `cp` misses recent commits living in the -wal sidecar — this uses
# SQLite's online backup API and integrity-checks the result. No-op with
# a note when the database doesn't exist yet.
backup-db: venv config
	@if [ -f $(DATA_DIR)/remarkbox.sqlite ]; then \
		$(VENV_DIR)/bin/remarkbox_backup_db -c $(DATA_DIR)/$(CONFIG_FILE) \
			--output-dir $(DATA_DIR) --no-upload --no-compress; \
	else \
		echo "No database yet — nothing to back up."; \
	fi

# Prove our newest backup restores: integrity check, expected tables,
# alembic revision, non-empty core tables.
restore-drill: venv config
	$(VENV_DIR)/bin/remarkbox_restore_drill -c $(DATA_DIR)/$(CONFIG_FILE) \
		--backup-dir $(DATA_DIR)

# --- Production backups (see docs/backups.md) --------------------------------
# Our production server hosts several remarkbox sites in one site dir
# (my.remarkbox.com, demo, westworld2, foxhop.net, ...), each with its
# own ini + sqlite. Override per-invocation when needed:
#   make backup-prod PROD_HOST=fox@other.host
PROD_HOST ?= fox@origin.remarkbox.com
PROD_SITE_DIR ?= /opt/remarkbox

# Run a verified, WAL-safe backup ON our production server for EVERY
# deployed site ini. Timestamped, integrity-checked backups land in
# $(PROD_SITE_DIR)/backups owned by uwsgi; retention pruning applies.
# Interactive: sudo prompts for your password on the server.
backup-prod:
	ssh -t $(PROD_HOST) 'rc=0; for ini in $(PROD_SITE_DIR)/*.ini; do \
		echo "== $$ini"; \
		sudo -u uwsgi $(PROD_SITE_DIR)/env/bin/remarkbox_backup_db -c "$$ini" \
			--output-dir $(PROD_SITE_DIR)/backups || { rc=1; echo "!! backup failed for $$ini"; }; \
	done; exit $$rc'

# Copy our newest production backups (one per site) into ./backups
# locally. Stages files world-readable in a private /tmp dir on the
# server first because backups are uwsgi-owned. Runs backup-prod first.
backup-fetch: backup-prod
	@mkdir -p backups
	ssh -t $(PROD_HOST) 'set -e; \
		rm -rf /tmp/rb-backup-staging && mkdir -m 700 /tmp/rb-backup-staging; \
		for f in $$(sudo ls -1t $(PROD_SITE_DIR)/backups | head -8); do \
			sudo install -m 644 "$(PROD_SITE_DIR)/backups/$$f" /tmp/rb-backup-staging/; \
		done'
	scp "$(PROD_HOST):/tmp/rb-backup-staging/*" backups/
	ssh $(PROD_HOST) 'rm -rf /tmp/rb-backup-staging'
	@ls -lt backups | head -10

# Apply all pending Alembic migrations (backs up the database first).
migrate: venv config backup-db
	$(ALEMBIC) -c $(DATA_DIR)/$(CONFIG_FILE) upgrade head

# Show current migration status.
migration-status: venv config
	$(ALEMBIC) -c $(DATA_DIR)/$(CONFIG_FILE) current
	$(ALEMBIC) -c $(DATA_DIR)/$(CONFIG_FILE) history --verbose

# Start the development server with auto-reload
serve: venv config
	@echo "Starting the remarkbox development server..."
	$(PSERVE) $(DATA_DIR)/$(CONFIG_FILE) --reload

# -----------------------------------------------------------------------------
# Combined Setup Targets
# -----------------------------------------------------------------------------

# Install and setup using PyPI packages
install-from-pypi: venv config install init-db

# Install and setup from source (editable mode)
install-from-source: venv config install-source-dev-and-test init-db

# Install and setup from source (no edit)
install-from-source-prod: venv config install-source-prod init-db

# -----------------------------------------------------------------------------
# Additional Targets
# -----------------------------------------------------------------------------

# Print instructions for activating the virtual environment
activate:
	@echo "To activate the virtual environment, run:"
	@echo "  source $(VENV_DIR)/bin/activate"

# Run the test suite (installs test dependencies if needed).
# --dist=loadgroup pins tests sharing an xdist_group marker to a single
# worker — used by test_pandoc.py to serialize ~14 pandoc subprocesses
# that would otherwise race cold-start CPU contention on CI and exceed
# the 5s/30s subprocess timeouts.
test: install-source-dev-and-test
	@echo "Running tests in parallel..."
	$(VENV_DIR)/bin/py.test -n auto --dist=loadgroup

# Start a simple HTTP server (for serving static files like index.html)
http: venv
	@echo "Starting simple HTTP server on port 8000..."
	$(PYTHON) -m http.server 8000

# -----------------------------------------------------------------------------
# Twine Upload Target (uses /tmp venv to avoid system python)
# -----------------------------------------------------------------------------

TWINE_VENV = /tmp/twine-venv
TWINE = $(TWINE_VENV)/bin/twine

$(TWINE_VENV)/bin/twine:
	@echo "Creating twine virtualenv in $(TWINE_VENV)..."
	python3 -m venv $(TWINE_VENV)
	# Pin twine <6 — newer twine auto-detects GitLab CI and refuses to
	# fall back to ~/.pypirc on the runner, requiring PYPI_ID_TOKEN
	# (Trusted Publishing OIDC). Until we migrate to Trusted Publishing,
	# stick with classic ~/.pypirc auth on the build runner.
	$(TWINE_VENV)/bin/pip install --upgrade pip
	$(TWINE_VENV)/bin/pip install "twine<6"

twine-venv: $(TWINE_VENV)/bin/twine

twine-upload: twine-venv
	@echo "Building and uploading to PyPI..."
	python3 setup.py sdist bdist_wheel
	$(TWINE) check dist/*
	$(TWINE) upload --non-interactive dist/*

# -----------------------------------------------------------------------------
# Cleanup Target
# -----------------------------------------------------------------------------

# Remove the virtual environment directory
clean:
	@echo "Cleaning up: removing $(VENV_DIR)..."
	rm -rf $(VENV_DIR)
