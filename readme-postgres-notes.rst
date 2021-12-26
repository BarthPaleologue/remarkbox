Setting up a development environment on Ubuntu
##############################################

#. we need ``git`` and ``PostgreSQL`` installed. If not, do:

   .. code-block:: bash
   
    sudo apt-get install git docker postgres-client libpq-dev (libpqxx-devel on fedora)
    sudo docker pull postgres:9.6.9-alpine

   create PostgreSQL docker container:
 
   .. code-block:: bash
    
    docker run --name development-postgres -d -p 5432:5432 postgres:9.6.9-alpine
 
   make yourself a Postgres Superuser (in my case `russellballestrini`):
 
   .. code-block:: bash
 
    psql --host=localhost --port 5432 --username postgres --command \
            "CREATE USER russellballestrini with SUPERUSER;"

   make the ``remarkbox`` database.

   .. code-block:: bash

    psql --host=localhost --port 5432 --username postgres --command \
            "CREATE DATABASE remarkbox;"

   make the ``remarkbox_test`` database.

   .. code-block:: bash

    psql --host=localhost --port 5432 --username postgres --command \
            "CREATE DATABASE remarkbox_test;"

#. checkout the Remarkbox codebase:

   .. code-block:: bash
   
    cd ~
    git clone https://russellballestrini@bitbucket.org/russellballestrini/remarkbox.git
    cd remarkbox

#. install ``python-pip``:

   .. code-block:: bash
   
    sudo apt-get install python-pip

#. use ``pip`` to upgrade ``pip`` and ``setuptools``:

   .. code-block:: bash
   
    sudo pip install --upgrade pip setuptools

#. use pip to install ``virtualenv``:

   .. code-block:: bash
   
    sudo pip install virtualenv

#. create a ``virtualenv``:

   .. code-block:: bash
   
    virtualenv env

#. source the new ``virtualenv``:

   .. code-block:: bash
   
    . env/bin/activate

#. install Remarkbox, using setuptool's in development mode:
 
   .. code-block:: bash
   
    python setup.py develop
 
#. install dev and test dependencies:

   .. code-block:: bash
   
    pip install -r requirements-dev.txt
    pip install -r requirements-test.txt

#. initialize the database schema:

   .. code-block:: bash
    
    remarkbox_init_db development.ini

#. spin up the application server using ``waitress``:

   .. code-block:: bash
    
    pserve development.ini --reload

Note: if you get an error about TemplateNotFound, you likely need to install the Remarkbox Meta theme. See readme-themes.rst for details.
