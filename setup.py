import os

from setuptools import setup, find_packages

here = os.path.abspath(os.path.dirname(__file__))
readme_path = os.path.join(here, "README.rst")
with open(readme_path, "r") as f:
    README = f.read()

setup(
    name="remarkbox",
    version="0.2.01",
    description="remarkbox",
    long_description=README,
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
