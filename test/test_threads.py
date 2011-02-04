# Copyright 2009-2010 10gen, Inc.
#
# Licensed under the Apache License, Version 2.0 (the "License");
# you may not use this file except in compliance with the License.
# You may obtain a copy of the License at
#
# http://www.apache.org/licenses/LICENSE-2.0
#
# Unless required by applicable law or agreed to in writing, software
# distributed under the License is distributed on an "AS IS" BASIS,
# WITHOUT WARRANTIES OR CONDITIONS OF ANY KIND, either express or implied.
# See the License for the specific language governing permissions and
# limitations under the License.

"""Test that pymongo is thread safe."""

import unittest
import threading

from nose.plugins.skip import SkipTest

from test_connection import get_connection
from pymongo.errors import AutoReconnect, OperationFailure, DuplicateKeyError


class SaveAndFind(threading.Thread):

    def __init__(self, collection):
        threading.Thread.__init__(self)
        self.collection = collection

    def run(self):
        sum = 0
        for document in self.collection.find():
            sum += document["x"]
        assert sum == 499500, "sum was %d not 499500" % sum


class Insert(threading.Thread):

    def __init__(self, collection, n, expect_exception):
        threading.Thread.__init__(self)
        self.collection = collection
        self.n = n
        self.expect_exception = expect_exception

    def run(self):
        for _ in xrange(self.n):
            error = True

            try:
                self.collection.insert({"test": "insert"}, safe=True)
                error = False
            except:
                if not self.expect_exception:
                    raise

            if self.expect_exception:
                assert error


class Update(threading.Thread):

    def __init__(self, collection, n, expect_exception):
        threading.Thread.__init__(self)
        self.collection = collection
        self.n = n
        self.expect_exception = expect_exception

    def run(self):
        for _ in xrange(self.n):
            error = True

            try:
                self.collection.update({"test": "unique"}, {"$set": {"test": "update"}}, safe=True)
                error = False
            except:
                if not self.expect_exception:
                    raise

            if self.expect_exception:
                assert error


class IgnoreAutoReconnect(threading.Thread):

    def __init__(self, collection, n):
        threading.Thread.__init__(self)
        self.c = collection
        self.n = n

    def run(self):
        for _ in range(self.n):
            try:
                self.c.find_one()
            except AutoReconnect:
                pass


class AutoAuthenticateThreads(threading.Thread):

    def __init__(self, collection, n):
        threading.Thread.__init__(self)
        self.c = collection
        self.n = n
        self.success = True

    def run(self):
        try:
            for i in range(self.n):
                self.c.insert({'num':i}, safe=True)
                self.c.find_one({'num':i})
        except Exception, e:
            self.success = False


class TestThreads(unittest.TestCase):

    def setUp(self):
        self.db = get_connection().pymongo_test

    def test_threading(self):
        self.db.test.remove({})
        for i in xrange(1000):
            self.db.test.save({"x": i}, safe=True)

        threads = []
        for i in range(10):
            t = SaveAndFind(self.db.test)
            t.start()
            threads.append(t)

        for t in threads:
            t.join()

    def test_safe_insert(self):
        self.db.drop_collection("test1")
        self.db.test1.insert({"test": "insert"})
        self.db.drop_collection("test2")
        self.db.test2.insert({"test": "insert"})

        self.db.test2.create_index("test", unique=True)
        self.db.test2.find_one()

        okay = Insert(self.db.test1, 2000, False)
        error = Insert(self.db.test2, 2000, True)

        error.start()
        okay.start()

        error.join()
        okay.join()

    def test_safe_update(self):
        self.db.drop_collection("test1")
        self.db.test1.insert({"test": "update"})
        self.db.test1.insert({"test": "unique"})
        self.db.drop_collection("test2")
        self.db.test2.insert({"test": "update"})
        self.db.test2.insert({"test": "unique"})

        self.db.test2.create_index("test", unique=True)
        self.db.test2.find_one()

        okay = Update(self.db.test1, 2000, False)
        error = Update(self.db.test2, 2000, True)

        error.start()
        okay.start()

        error.join()
        okay.join()

    def test_low_network_timeout(self):
        db = None
        i = 0
        n = 10
        while db is None and i < n:
            try:
                db = get_connection(network_timeout=0.0001).pymongo_test
            except AutoReconnect:
                i += 1
        if i == n:
            raise SkipTest()

        threads = []
        for _ in range(4):
            t = IgnoreAutoReconnect(db.test, 100)
            t.start()
            threads.append(t)

        for t in threads:
            t.join()


class TestAuthThreads(unittest.TestCase):

    def setUp(self):
        conn = get_connection()
        self.conn = conn

        # Setup auth users
        conn.admin.system.users.remove({})
        conn.admin.add_user("admin-user", "password")
        try:
            conn.admin.system.users.find_one()
            # If we reach here auth must be disabled in server
            self.tearDown()
            raise SkipTest()
        except OperationFailure:
            pass
        conn.admin.authenticate("admin-user", "password")
        conn.auth_test.system.users.remove({})
        conn.auth_test.add_user("test-user", "password")

    def tearDown(self):
        # Remove auth users from databases
        self.conn.admin.authenticate("admin-user", "password")
        self.conn.admin.system.users.remove({})
        self.conn.auth_test.system.users.remove({})

    def test_auto_auth_login(self):
        conn = get_connection()
        try:
            conn.auth_test.test.find_one()
            assert False  # Find should have failed
        except OperationFailure, e:
            pass

        # Admin auth
        conn = get_connection()
        conn.add_db_auth("admin", "admin-user", "password")

        threads = []
        for _ in range(10):
            t = AutoAuthenticateThreads(conn.auth_test.test, 100)
            t.start()
            threads.append(t)
        for t in threads:
            t.join()
            assert t.success

        # Database-specific auth
        conn = get_connection()
        conn.add_db_auth("auth_test", "test-user", "password")

        threads = []
        for _ in range(10):
            t = AutoAuthenticateThreads(conn.auth_test.test, 100)
            t.start()
            threads.append(t)
        for t in threads:
            t.join()
            assert t.success


if __name__ == "__main__":
    unittest.main()
