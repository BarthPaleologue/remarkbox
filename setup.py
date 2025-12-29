import os
from setuptools import setup, find_packages

def is_wsl():
    """
    Detect if we're running under Windows Subsystem for Linux.
    Checks if /proc/version exists and contains 'microsoft'.
    """
    try:
        with open('/proc/version', 'r', encoding='utf-8') as f:
            return 'microsoft' in f.read().lower()
    except Exception:
        return False

def parse_requirements(filename):
    """
    Read and parse a requirements file, ignoring comments and blank lines.
    """
    req_path = os.path.join(os.path.dirname(__file__), filename)
    with open(req_path, "r", encoding="utf-8") as f:
        lines = f.read().splitlines()
    reqs = [line.strip() for line in lines if line.strip() and not line.startswith("#")]
    return reqs

# Determine which requirements file to use
requirements_file = "requirements-wsl.txt" if is_wsl() else "requirements.py3.txt"
install_requires = parse_requirements(requirements_file)

# Optional extras for development, production, and testing.
extras_require = {
    'dev': parse_requirements("requirements-dev.txt"),
    'prod': parse_requirements("requirements-prod.txt"),
    'test': parse_requirements("requirements-test.txt"),
}

# Read the long description from README.rst
here = os.path.abspath(os.path.dirname(__file__))
with open(os.path.join(here, "README.rst"), "r", encoding="utf-8") as f:
    long_description = f.read()

setup(
    name="remarkbox",
    version="1.0.5",
    description="remarkbox",
    long_description=long_description,
    author="Russell Ballestrini",
    author_email="russell@ballestrini.net",
    url="https://russell.ballestrini.net",
    keywords="remarkbox question answer forum embed comments reviews",
    include_package_data=True,
    packages=find_packages(exclude=["tests"]),
    package_data={
        "remarkbox": ["scripts/alembic/*.py", "scripts/alembic/versions/*.py"]
    },
    zip_safe=False,
    test_suite="remarkbox",
    install_requires=install_requires,
    extras_require=extras_require,
    entry_points={
        "paste.app_factory": ["main = remarkbox:main"],
        "console_scripts": [
            "remarkbox_init_db = remarkbox.scripts.init_db:main",
            "remarkbox_modify_node = remarkbox.scripts.modify_node:main",
            "remarkbox_modify_user = remarkbox.scripts.modify_user:main",
            "remarkbox_modify_uris = remarkbox.scripts.modify_uris:main",
            "remarkbox_modify_namespace = remarkbox.scripts.modify_namespace:main",
            "remarkbox_json_import = remarkbox.scripts.json_import:main",
            "remarkbox_json_import2 = remarkbox.scripts.json_import2:main",
            "remarkbox_merge_dupes = remarkbox.scripts.merge_dupes:main",
            "remarkbox_invalidate_node_cache = remarkbox.scripts.invalidate_node_cache:main",
            "remarkbox_recompute_node_depths = remarkbox.scripts.recompute_node_depths:main",
            "remarkbox_safe_approve_all_nodes = remarkbox.scripts.safe_approve_all_nodes:main",
            "remarkbox_send_node_digest_notifications = remarkbox.scripts.send_node_digest_notifications:main",
            "remarkbox_delete_disabled_nodes = remarkbox.scripts.delete_disabled_nodes:main",
        ],
    },
    classifiers=[
        "Programming Language :: Python :: 3",
        "Programming Language :: Python :: 3.6",
        "Programming Language :: Python :: 3.7",
        "Programming Language :: Python :: 3.8",
        "Programming Language :: Python :: 3.9",
        "Programming Language :: Python :: 3.10",
        "Programming Language :: Python :: 3.11",
        "Programming Language :: Python :: 3.12",
        "Programming Language :: Python :: 3.13",
        "Programming Language :: Python :: 3.14",
        "Programming Language :: Python :: 3.15",
        "Programming Language :: Python",
        "Framework :: Pyramid",
        "Topic :: Internet :: WWW/HTTP",
        "Topic :: Internet :: WWW/HTTP :: WSGI :: Application",
    ],
)

# python setup.py sdist bdist_wheel
# twine upload dist/*
