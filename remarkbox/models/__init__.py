# alias: `from .event import *` below binds our models' `event` submodule
# over any bare `event` global in this package namespace.
from sqlalchemy import engine_from_config
from sqlalchemy import event as sa_event
from sqlalchemy.orm import sessionmaker
from sqlalchemy.orm import configure_mappers
import zope.sqlalchemy

# import all models here to ensure they are attached to the
# Base.metadata prior to any initialization routines ( init_db).
from .uri import *
from .user import *
from .namespace import *
from .namespace_user import *
from .namespace_request import *
from .node import *
from .node_cache import *
from .vote import *
from .oauth import *
from .watcher import *
from .event import *
from .notification import *
from .pay_what_you_can import *
from .payment import *
from .webmention import *
from .sudo_otp import *
from .revision import *
from .api_token import *
from .mfa_method import *

# run configure_mappers after defining all of the models to ensure
# all relationships can be setup
configure_mappers()


def get_engine(settings, prefix="sqlalchemy."):
    engine = engine_from_config(settings, prefix)
    if engine.url.get_backend_name() == "sqlite":

        @sa_event.listens_for(engine, "connect")
        def set_sqlite_pragma(dbapi_conn, connection_record):
            cursor = dbapi_conn.cursor()
            # wait rather than raise "database is locked" under contention.
            cursor.execute("PRAGMA busy_timeout = 30000")

            # WAL lets readers run while a writer holds the database —
            # without it every comment INSERT blocks every reader for the
            # length of the write. journal_mode is a persistent property
            # of the database file, not the connection, so this is a
            # no-op after the first connect; we set it on every connect
            # anyway so a restored or newly provisioned database can
            # never quietly run in rollback mode. In-memory databases
            # (test fixtures) answer "memory" and ignore the request,
            # which is harmless.
            cursor.execute("PRAGMA journal_mode = WAL")

            # NORMAL fsyncs at checkpoints instead of at every commit.
            # With WAL this risks losing only the last transactions on an
            # OS/hardware crash — never a corrupt database — and is the
            # standard pairing for WAL.
            cursor.execute("PRAGMA synchronous = NORMAL")

            # deliberately NOT setting PRAGMA foreign_keys = ON here.
            # These databases have run with SQLite's default (off) since
            # day one; enabling enforcement now would start rejecting
            # deletes against whatever orphan rows history has left us —
            # a behaviour change to shake out on its own, not a rider on
            # a journal-mode change.

            cursor.close()

    return engine


def get_session_factory(engine):
    factory = sessionmaker()
    factory.configure(bind=engine)
    return factory


def get_tm_session(session_factory, transaction_manager):
    """
    Get a ``sqlalchemy.orm.Session`` instance backed by a transaction.

    This function will hook the session to the transaction manager which
    will take care of committing any changes.

    - When using pyramid_tm it will automatically be committed or aborted
      depending on whether an exception is raised.

    - When using scripts you should wrap the session in a manager yourself.
      For example::

          import transaction

          engine = get_engine(settings)
          session_factory = get_session_factory(engine)
          with transaction.manager:
              dbsession = get_tm_session(session_factory, transaction.manager)

    """
    dbsession = session_factory()
    zope.sqlalchemy.register(dbsession, transaction_manager=transaction_manager)
    return dbsession


def includeme(config):
    """
    Initialize the model for a Pyramid app.

    Activate this setup using ``config.include('pyratest.models')``.

    """
    settings = config.get_settings()
    settings["tm.manager_hook"] = "pyramid_tm.explicit_manager"

    # use pyramid_tm to hook the transaction lifecycle to the request
    config.include("pyramid_tm")

    # use pyramid_retry to retry a request when transient exceptions occur
    config.include("pyramid_retry")

    session_factory = get_session_factory(get_engine(settings))
    config.registry["dbsession_factory"] = session_factory

    # make request.dbsession available for use in Pyramid
    config.add_request_method(
        # r.tm is the transaction manager used by pyramid_tm
        lambda r: get_tm_session(session_factory, r.tm),
        "dbsession",
        reify=True,
    )
