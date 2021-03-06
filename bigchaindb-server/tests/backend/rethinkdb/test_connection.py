import time
import multiprocessing as mp
from threading import Thread
from unittest.mock import patch

import pytest
import rethinkdb as r


def test_get_connection_returns_the_correct_instance():
    from bigchaindb.backend import connect
    from bigchaindb.backend.connection import Connection
    from bigchaindb.backend.rethinkdb.connection import RethinkDBConnection

    config = {
        'backend': 'rethinkdb',
        'host': 'localhost',
        'port': 28015,
        'name': 'test'
    }

    conn = connect(**config)
    assert isinstance(conn, Connection)
    assert isinstance(conn, RethinkDBConnection)


def test_run_a_simple_query():
    from bigchaindb.backend import connect

    conn = connect()
    query = r.expr('1')
    assert conn.run(query) == '1'


def test_raise_exception_when_max_tries():
    from bigchaindb.backend import connect

    class MockQuery:
        def run(self, conn):
            raise r.ReqlDriverError('mock')

    conn = connect()

    with pytest.raises(r.ReqlDriverError):
        conn.run(MockQuery())


def test_reconnect_when_connection_lost():
    from bigchaindb.backend import connect

    def raise_exception(*args, **kwargs):
        raise r.ReqlDriverError('mock')

    conn = connect()
    original_connect = r.connect
    r.connect = raise_exception

    def delayed_start():
        time.sleep(1)
        r.connect = original_connect

    thread = Thread(target=delayed_start)
    query = r.expr('1')
    thread.start()
    assert conn.run(query) == '1'


def test_changefeed_reconnects_when_connection_lost(monkeypatch):
    from bigchaindb.backend.changefeed import ChangeFeed
    from bigchaindb.backend.rethinkdb.changefeed import RethinkDBChangeFeed

    class MockConnection:
        tries = 0

        def run(self, *args, **kwargs):
            return self

        def __iter__(self):
            return self

        def __next__(self):
            self.tries += 1
            if self.tries == 1:
                raise r.ReqlDriverError('mock')
            elif self.tries == 2:
                return {'new_val': {'fact':
                                    'A group of cats is called a clowder.'},
                        'old_val': None}
            if self.tries == 3:
                raise r.ReqlDriverError('mock')
            elif self.tries == 4:
                return {'new_val': {'fact': 'Cats sleep 70% of their lives.'},
                        'old_val': None}
            else:
                time.sleep(10)

    changefeed = RethinkDBChangeFeed('cat_facts', ChangeFeed.INSERT,
                                     connection=MockConnection())
    changefeed.outqueue = mp.Queue()
    t_changefeed = Thread(target=changefeed.run_forever, daemon=True)

    t_changefeed.start()
    time.sleep(1)
    # try 1: MockConnection raises an error that will stop the
    #        ChangeFeed instance from iterating for 1 second.

    # try 2: MockConnection releases a new record. The new record
    #        will be put in the outqueue of the ChangeFeed instance.
    fact = changefeed.outqueue.get()['fact']
    assert fact == 'A group of cats is called a clowder.'

    # try 3: MockConnection raises an error that will stop the
    #        ChangeFeed instance from iterating for 1 second.
    assert t_changefeed.is_alive() is True

    time.sleep(2)
    # try 4: MockConnection releases a new record. The new record
    #        will be put in the outqueue of the ChangeFeed instance.

    fact = changefeed.outqueue.get()['fact']
    assert fact == 'Cats sleep 70% of their lives.'


@patch('rethinkdb.connect')
def test_connection_happens_one_time_if_successful(mock_connect):
    from bigchaindb.backend import connect

    query = r.expr('1')
    conn = connect('rethinkdb', 'localhost', 1337, 'whatev')
    conn.run(query)
    mock_connect.assert_called_once_with(host='localhost',
                                         port=1337,
                                         db='whatev')
