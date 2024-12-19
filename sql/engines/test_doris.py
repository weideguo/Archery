from unittest.mock import patch

from django.test import TestCase

from sql.engines import ResultSet, ReviewSet
from sql.engines.models import ReviewResult
from sql.engines.doris import DorisEngine
from sql.models import Instance


class TestDoris(TestCase):
    def setUp(self):
        self.ins1 = Instance(
            instance_name="some_ins",
            type="slave",
            db_type="doris",
            host="some_host",
            port=1366,
            user="ins_user",
            password="some_str",
        )
        self.ins1.save()

    def tearDown(self):
        self.ins1.delete()

    @patch.object(DorisEngine, "query")
    def test_processlist(self, _query):
        new_engine = DorisEngine(instance=self.ins1)
        _query.return_value = ResultSet()
        _query.return_value.column_list = [
            "CurrentConnected",
            "Id",
            "User",
            "Host",
            "LoginTime",
            "Catalog",
            "Db",
            "Command",
            "Time",
            "State",
            "QueryId",
            "Info",
        ]
        rows = (
            (
                "",
                "1105809",
                "test",
                "10.0.0.1:1234",
                "2024-03-1415:36:16",
                "internal",
                "test_db",
                "Query",
                "54",
                "EOF",
                "aaaaaaaaaaaaaaaa-bbbbbbbbbbbbbbb1",
                "SELECT@@session.transaction_read_only",
            ),
            (
                "Yes",
                "1105820",
                "root",
                "127.0.0.1:5436",
                "2024-03-1415:37:07",
                "internal",
                "",
                "Sleep",
                "0",
                "OK",
                "aaaaaaaaaaaaaaaa-bbbbbbbbbbbbbbb2",
                "showprocesslist",
            ),
            (
                "",
                "1105821",
                "root",
                "127.0.0.1:5437",
                "2024-03-1415:37:07",
                "internal",
                "",
                "Query",
                "0",
                "OK",
                "aaaaaaaaaaaaaaaa-bbbbbbbbbbbbbbb3",
                "showprocesslist",
            ),
        )

        for command_type in ["Query", "All", "Not Sleep"]:
            r = new_engine.processlist(command_type)
            self.assertIsInstance(r, ResultSet)
        _query.return_value.rows = rows
        self.assertEqual(len(new_engine.processlist("Query").rows), 2)
        _query.return_value.rows = rows
        self.assertEqual(len(new_engine.processlist("All").rows), 3)
        _query.return_value.rows = rows
        self.assertEqual(len(new_engine.processlist("Not Sleep").rows), 2)

    def test_execute_check(self):
        sql = "update user set id=1"
        row = ReviewResult(
            id=2,
            errlevel=0,
            stagestatus="Audit completed",
            errormessage="None",
            sql=sql,
            affected_rows=0,
            execute_time=0,
        )
        new_engine = DorisEngine(instance=self.ins1)
        check_result = new_engine.execute_check(db_name="archery_new", sql=sql)
        self.assertIsInstance(check_result, ReviewSet)
        self.assertEqual(check_result.rows[1].__dict__, row.__dict__)
