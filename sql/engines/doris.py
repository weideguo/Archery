# -*- coding: UTF-8 -*-
import re
import traceback
import logging

import sqlparse

from sql.engines.mysql import MysqlEngine
from .models import ResultSet, ReviewSet, ReviewResult
from sql.utils.sql_utils import get_syntax_type, split_sql

logger = logging.getLogger("default")


class DorisEngine(MysqlEngine):
    name = "Doris"
    info = "Doris engine"

    def __init__(self, instance=None):
        super().__init__(instance=instance)
        self.default_max_execution_time = 1000

    def processlist(self, command_type):
        # doris2.1.5已经支持查询 information_schema.processlist，可以不用再重写这个方法
        sql = "show processlist"
        command_type = self.escape_string(command_type)
        if not command_type:
            command_type = "Query"

        result_set = self.query("information_schema", sql)
        if result_set.rows and "Command" in result_set.column_list:
            command_index = result_set.column_list.index("Command")
            rows = []
            for row in result_set.rows:
                is_row_match = True
                if command_type == "Not Sleep":
                    is_row_match = row[command_index] != "Sleep"
                elif command_type == "Query":
                    is_row_match = row[command_index] == "Query"

                if is_row_match:
                    rows.append(row)
            result_set.rows = rows

        return result_set

    def get_kill_command(self, thread_ids):
        # doris2.1.5已经支持查询 information_schema.processlist，可以不用再重写这个方法
        if [i for i in thread_ids if not isinstance(i, int)]:
            return None
        kill_sql = ""
        for i in thread_ids:
            kill_sql = kill_sql + ("kill {};".format(i))
        return kill_sql

    def kill(self, thread_ids):
        # doris2.1.5已经支持查询 information_schema.processlist，可以不用再重写这个方法
        kill_sql = self.get_kill_command(thread_ids)
        if not kill_sql:
            return ResultSet(full_sql="")
        return self.execute("information_schema", kill_sql)

    @property
    def seconds_behind_master(self):
        return None

    def execute_check(self, db_name=None, sql=""):
        sql_list = split_sql(db_name, sql)

        check_result = ReviewSet(full_sql=sql)
        rowid = 0
        syntax_type_str = ""
        for statement in sql_list:
            rowid += 1
            # 获取语句类型，如果出现DDL，则认为工单是DDL
            if syntax_type_str != "DDL":
                syntax_type_str = get_syntax_type(
                    statement, parser=False, db_type="mysql"
                )

            (
                errlevel,
                stagestatus,
                errormessage,
                affected_rows,
                execute_time,
            ) = self.statement_audit(statement)
            check_result.rows.append(
                ReviewResult(
                    id=rowid,
                    errlevel=errlevel,
                    stagestatus=stagestatus,
                    errormessage=errormessage,
                    sql=statement,
                    affected_rows=affected_rows,
                    execute_time=execute_time,
                )
            )

        # 映射关系在 sql.models.SqlWorkflow syntax_type
        if syntax_type_str == "DDL":
            check_result.syntax_type = 1
        elif syntax_type_str == "DML":
            check_result.syntax_type = 2
        else:
            check_result.syntax_type = 0

        return self.execute_check_forbidden(check_result)

    def execute_workflow(self, workflow):
        return self.execute_workflow_native(workflow)

    def statement_audit(self, statement):
        """对单个语句进行审核"""
        errlevel = 0
        stagestatus = "Audit completed"
        errormessage = "None"
        affected_rows = 0
        execute_time = 0
        if re.match(r"^use\s+", statement.lower()):
            if not re.match(r"^use\s+\S+", statement.lower()):
                errlevel = 2
                stagestatus = "驳回未通过检查SQL"
                errormessage = "语法错误"

        elif re.match(r"^create\s+", statement.lower()):
            if not re.match(r"^create\s+table\s+(.+?)\s+", statement.lower()):
                errlevel = 2
                stagestatus = "驳回未通过检查SQL"
                errormessage = "语法错误"
            if errlevel == 2 and re.match(r"^create\s+view\s+(\s|\S)+\s+select\s+\S+", statement.lower()):
                errlevel = 0
                stagestatus = "Audit completed"
                errormessage = "None"

        elif re.match(r"^alter\s+", statement.lower()):
            if not re.match(r"^alter\s+table\s+", statement.lower()):
                errlevel = 2
                stagestatus = "驳回未通过检查SQL"
                errormessage = "语法错误"
            if errlevel == 2 and re.match(r"^alter\s+view\s+", statement.lower()):
                errlevel = 0
                stagestatus = "Audit completed"
                errormessage = "None"

        elif re.match(r"^insert\s", statement.lower()):
            if not re.match(r"^insert\s+into\s+(\S|\s)+\s+values\s*\((\s|\S)+\)", statement.lower()):
                errlevel = 2
                stagestatus = "驳回未通过检查SQL"
                errormessage = "语法错误"
            
            if errlevel == 2 and re.match(r"^insert\s+into\s+(\S|\s)+\s+select\s+\S+", statement.lower()):
                errlevel = 0
                stagestatus = "Audit completed"
                errormessage = "None"

        elif re.match(r"^delete\s+", statement.lower()):
            if not re.match(r"^delete\s+from\s+\S+\s+where\s+\S+", statement.lower()):
                errlevel = 2
                stagestatus = "驳回未通过检查SQL"
                errormessage = "应该带有where条件"

        elif re.match(r"^update\s+", statement.lower()):
            if not re.match(r"^update\s+(\S|\s)+\s+where\s+\S+", statement.lower()):
                errlevel = 2
                stagestatus = "驳回未通过检查SQL"
                errormessage = "应该带有where条件"

        elif re.match(r"^drop|^truncate", statement.lower()):
            # drop、truncate直接用统一配置的正则语句设置是否允许 
            pass

        else:
            errlevel = 2
            stagestatus = "驳回未支持语句"
            errormessage = "未支持语句"        

        return errlevel, stagestatus, errormessage, affected_rows, execute_time
