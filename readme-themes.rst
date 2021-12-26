Install meta theme
-----------------------

Remarkbox supports custom themes which makes it possible to provide "whitelabel" deployments which are rebranded.

The default Remarkbox theme is called `meta` and may be installed in development like this:

.. code-block:: bash

 git clone https://github.com/russellballestrini/remarkbox-theme-meta.git
 cd remarkbox-theme-meta
 python setup.py develop
 
If you don't want to install this theme, that is ok, comment out `app.theme = meta` in the `development.ini`
