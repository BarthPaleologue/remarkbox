Quick Start: Operating a Server with PyPI or Source Code
==============================================================

Before you install, navigate to the directory you want to install into.

This ``Makefile`` based workflow lets you choose between installing Remarkbox from PyPI packages or directly from the source code (editable mode). Both flows create a virtual environment in ``./env`` and store configuration and SQLite data in the persistent ``./data`` directory.

1. **Install Remarkbox**

   - For a PyPI Installation, run::

         wget "https://git.unturf.com/engineering/remarkbox/remarkbox/-/raw/main/Makefile"
         make install-from-pypi

   - For a Source Installation (editable mode), run::

         git clone ssh://git@git.unturf.com:2222/engineering/remarkbox/remarkbox.git
         make install-from-source

2. **Activate the Virtual Environment**

   Before running any subsequent commands or scripts (including starting the server or running tests), activate the virtual environment with::

         source env/bin/activate

   Activating the virtual environment ensures that all Python commands (such as ``pip`` or ``pshell``) use the packages and settings in ``./env`` rather than your system-wide Python installation. This is crucial for consistency throughout the rest of this document.

3. **Start the Development Server**

   You'll want to configure the system in ``data/development.ini``.

   Typically I control most stuff with environment vars, for example ``vars.sh``::

         # optional but currently broken...
         export REMARKBOX_APP_STRIPE_PUBLIC="pk_test_removed"
         export REMARKBOX_APP_STRIPE_SECRET="sk_test_removed"
         
         # optional & you will need to create you're own slack app/bot.
         export REMARKBOX_APP_SLACK_PUBLIC="removed"
         export REMARKBOX_APP_SLACK_SECRET="removed"
         
         # optional, defaults to localhost & http://localhost:6543
         export REMARKBOX_APP_ROOT_DOMAIN="example.com"
         export REMARKBOX_APP_URL="https://example.com"

   Once the virtual environment is active, run::

         source vars.sh
         make serve

Other commands—such as ``make test``, and ``make http`` operate within this environment.


Remarkbox
==============================================

This is the codebase that powers both self‑hosted and SaaS Remarkbox!

SaaS Sites
----------

- `https://www.remarkbox.com <https://www.remarkbox.com>`_
- `https://faq.remarkbox.com <https://faq.remarkbox.com>`_
- `https://meta.remarkbox.com <https://meta.remarkbox.com>`_

Self‑hosted Example Running a Custom Theme
-------------------------------------------

- `https://westworld2.com <https://westworld2.com>`_

What is Remarkbox?
------------------
Remarkbox is a standalone question and answer site (forum) or an embedded comments/product reviews service that works anywhere HTML is supported.

Features
--------
- **Dark Mode Support:** User-configurable theme preferences with automatic theme detection for embedded contexts
- **Passwordless Authentication:** One-time-password codes via email for secure registration and login
- **Multi-tenant Architecture:** Host multiple forums and comment systems on a single installation
- **Customizable Themes:** Plugin-based theme system supporting custom branding and styling
- **Embed Anywhere:** Works with static sites, WordPress, or any platform that supports HTML

Project Goals
==============================================

*Note: These goals are not in priority order.*

#. **Support Multiple Use Cases:**  
   - Q&A sites (e.g. StackOverflow)  
   - Embedded comment systems for static sites  
   - Forums  
   - Product review sections on e‑commerce sites

#. **Adopt Widely Used Tools:**  
   - GitHub (with GitLab under consideration) over Bitbucket  
   - Git instead of Mercurial  
   - Jinja2 templates instead of Mako  
   - Markdown rather than reStructuredText  
   - …and more, choosing solutions trusted by the majority.

#. To be popular  
#. To be safe from spammers  
#. To be easy to manage and clean up spam  
#. To be passwordless – using one‑time-password codes via email for registration and authentication  
#. To scale horizontally  
#. To be multitenant  
#. To minimize friction for new users  
#. To be engaging for users  
#. To be search engine optimized  
#. To have great test coverage  
#. To be easy to create and load custom themes (similar to WordPress)

Local Installation
==============================================

This repository includes a Makefile that automates your local Remarkbox environment setup by creating:
- A virtual environment in ``./env``
- A persistent data directory in ``./data`` (which holds your ``development.ini`` and SQLite database)

*Note: The Makefile handles environment setup and database initialization, so you do not need to run these steps manually.*

Functional Testing Environment
==============================================

To set up a functional testing environment on your workstation, open two terminal shells:

1. In the first shell, start the Remarkbox server::

       make serve

2. In the second shell, run a simple HTTP server (to serve an ``index.html`` file)::

       make http

Browse to `http://127.0.0.1:8000 <http://127.0.0.1:8000>`_ to view the homepage, which embeds a local copy of Remarkbox. In development, one‑time-password codes are logged to the console if an SMTP server is not available.

SQL Migrations
==============================================

For new environments, migrations are not needed—the Makefile creates and stamps the database schema as ready. For existing deployments, you can run:

- **Upgrade to the Latest Revision:**

  ::

      env/bin/alembic -c data/development.ini upgrade head

- **View Migration History and Current Revision:**

  ::

      env/bin/alembic -c data/development.ini history
      env/bin/alembic -c data/development.ini current

- **Create a New Migration Script:**

  ::

      env/bin/alembic -c data/development.ini revision -m "Added email_id column to User table."

- **Autogenerate a Migration Script:**

  ::

      env/bin/alembic -c data/development.ini revision --autogenerate -m "autogenerated indices."

Review the generated script before applying it.

Looking Up Paying Customers
==============================================

To list paying customers, execute:

.. code-block:: sql

    SELECT * FROM rb_payment
        INNER JOIN rb_user ON rb_user.id = rb_payment.user_id
        WHERE status = 'completed';

Python Pyramid Shell
==============================================

To interact with Remarkbox’s models and database using an interactive Python shell, run:

.. code-block:: bash

    env/bin/pshell data/development.ini

For example, the following script modifies every ``Node`` that has a ``Uri``:

.. code-block:: python

    # Begin the database transaction.
    request.tm.begin()
    
    # Retrieve all Uri objects.
    uris = m.uri.get_all_uris(request.dbsession)
    
    # Update each Node.
    for uri in uris:
        uri.node.has_uri = True
        request.dbsession.add(uri.node)
    
    # Flush and commit changes.
    request.dbsession.flush()
    request.tm.commit()

Contributing
==============================================

- Establish communication with Russell or another admin to have your GitLab account approved.
- Clone the repository and make commits.
- Create merge requests; unit and headless functional tests run automatically on each commit.
- Upon merge, changes are released to production and become visible to users.

*Optional Formatting Guidelines:*

- **Python:** Use `black <https://black.readthedocs.io/>`_ (manual execution).
- **Jinja2/HTML:** No formatter needed.
- **JavaScript/CSS:** Use Prettier or Biome (manual execution).

Licence
==============================================

All contributed code is placed in the public domain.

source code: `https://git.unturf.com/engineering/remarkbox/remarkbox <https://git.unturf.com/engineering/remarkbox/remarkbox>`_

Remarkbox is trademarked, do not misrepresent the brand.

Feel free to white label any code or themes into your own brand.

**Original Developer:**  
`Russell Ballestrini <https://russell.ballestrini.net>`_
