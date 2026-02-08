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
	$(PIP) install setuptools

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
	@echo "Installing remarkbox from source (editable mode)..."
	$(PIP) install --editable .
	$(PIP) install --upgrade -r requirements-dev.txt
	$(PIP) install --upgrade -r requirements-test.txt

install-source-prod: venv install-themes
	@echo "Deleting tests from source code for production..."
	rm -rf remarkbox/tests
	@echo "Installing remarkbox from source (in non-editable mode)..."
	$(PIP) install .
	$(PIP) install --upgrade -r requirements-prod.txt


# -----------------------------------------------------------------------------
# Database Initialization and Server Targets
# -----------------------------------------------------------------------------

# Initialize the database using the configuration file
init-db: venv config
	@echo "Initializing the remarkbox database..."
	$(RB_INIT) $(DATA_DIR)/$(CONFIG_FILE)
	$(ALEMBIC) -c $(DATA_DIR)/$(CONFIG_FILE) stamp head

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

# Run the test suite (installs test dependencies if needed)
test: install-source-dev-and-test
	@echo "Running tests in parallel..."
	$(VENV_DIR)/bin/py.test -n auto

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
	$(TWINE_VENV)/bin/pip install --upgrade pip twine

twine-venv: $(TWINE_VENV)/bin/twine

twine-upload: twine-venv
	@echo "Building and uploading to PyPI..."
	python3 setup.py sdist bdist_wheel
	$(TWINE) upload dist/*

# -----------------------------------------------------------------------------
# Cleanup Target
# -----------------------------------------------------------------------------

# Remove the virtual environment directory
clean:
	@echo "Cleaning up: removing $(VENV_DIR)..."
	rm -rf $(VENV_DIR)
