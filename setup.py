import os
from setuptools import setup, find_packages

def parse_requirements(filename):
    """
    Read and parse a requirements file, ignoring comments and blank lines.
    """
    req_path = os.path.join(os.path.dirname(__file__), filename)
    with open(req_path, "r", encoding="utf-8") as f:
        lines = f.read().splitlines()
    return [line.strip() for line in lines if line.strip() and not line.startswith("#")]

# Read the long description from README.rst
here = os.path.abspath(os.path.dirname(__file__))
with open(os.path.join(here, "README.rst"), "r", encoding="utf-8") as f:
    long_description = f.read()

# Use the Python 3 requirements file by default.
install_requires = parse_requirements("requirements.py3.txt")

# Extras for development, production, testing, and Windows WSL.
extras_require = {
    'dev': parse_requirements("requirements-dev.txt"),
    'prod': parse_requirements("requirements-prod.txt"),
    'test': parse_requirements("requirements-test.txt"),
    'wsl': parse_requirements("requirements-wsl.txt"),
}

setup(
    name="remarkbox",
    version="0.0.11",
    description="remarkbox",
    long_description=long_description,
    classifiers=[
        "Programming Language :: Python",
        "Framework :: Pyramid",
        "Topic :: Internet :: WWW/HTTP",
        "Topic :: Internet :: WWW/HTTP :: WSGI :: Application",
    ],
    author="Russell Ballestrini",
    author_email="russell@ballestrini.net",
    url="https://russell.ballestrini.net",
    keywords="remarkbox question answer forum embed comments reviews",
    include_package_data=True,
    packages=find_packages(),
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
        ],
    },
)

# python setup.py sdist bdist_wheel
# twine upload dist/*
