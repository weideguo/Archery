# -*- coding: UTF-8 -*-
import shlex

from jinja2 import Template

from common.config import SysConfig
from sql.plugins.plugin import Plugin



class Sysbench(Plugin):
    """
    sysbench进行压测
    sysbench {{global.lua_file}} --threads={{session.threads}} --time={{session.time}} --mysql-db={{session.database}} --mysql-user={{const_mysql_sysbench.username}} --mysql-password={{const_mysql_sysbench.password}} --mysql-host={{global.host}} --mysql-port=3306 run
    """

    def __init__(self):
        self.path = SysConfig().get('sysbench') or 'sysbench'
        self.required_args = ['threads','time','mysql-db','mysql-user','mysql-password','mysql-host','mysql-port']
        self.disable_args = ['']
        super(Plugin, self).__init__()

    def generate_args2cmd(self, args, shell):
        """
        转换请求参数为命令行
        :param args:
        :param shell:
        :return:
        """

        lua_file_options = ['lua_file']
        args_options = ['threads','time','mysql-db','mysql-user','mysql-password','mysql-host','mysql-port']

        if shell:
            cmd_args = f'{shlex.quote(str(self.path))}' if self.path else ''
            for name, value in args.items():
                if name in lua_file_options:
                    cmd_args += f' {value}'
                elif name in args_options and value:
                    cmd_args += f' --{name}={shlex.quote(str(value))}'

            cmd_args += f' run'    
        else:
            cmd_args = [self.path]
            for name, value in args.items():
                if name in lua_file_options:
                    cmd_args.append(f'{value}')
                elif name in args_options:
                    cmd_args.append(f'--{name}')
                    cmd_args.append(f'{value}')
            cmd_args.append('run')
        return cmd_args

    def params_tranfer(self, sql_params, param_spliter):
        """
        格式化处理字符串格式的sql参数
        sql_params    ['111,22,333,44','aaa,bbb,ccc']
        param_spliter ,
        """
        #sql_params = json.loads(sql_params)
        
        sql_params_ex = []      #[(['111','222'],'string'),()]
        for sql_param in sql_params:
            
            param_type = 'int'   #默认把所有参数当成数字
            _sql_params = sql_param.split(param_spliter)
            for _sql_param in _sql_params:
                try:
                    int(_sql_param)
                except:
                    param_type = 'string'
                    break
        
            if param_type == 'int':
                __sql_params = [int(s) for s in _sql_params]
            else:
                __sql_params = []
                for _sql_param in _sql_params:
                    if (_sql_param[0] == '\'' and _sql_param[-1] == '\'' ) or (_sql_param[0] == '"' and _sql_param[-1] == '"' ):
                        __sql_params.append(_sql_param[1:-1])
                    else:
                        __sql_params.append(_sql_param)
            
            sql_params_ex.append((__sql_params, param_type))
        return sql_params_ex
    
    
    def generate_lua_file(self, sql_content, sql_params, param_spliter, params_sync, lua_file):   
        """
        由传入的带占位符的sql以及参数列表，生成一个lua文件
        返回文件全路径
        """
        sql_params_ex = self.params_tranfer(sql_params, param_spliter)
    
        lua_tmpl = '''
        -- 用于sysbench
        local t = sysbench.sql.type
        local stmt_def = { {{SQL_TMPL}} }
        
        function thread_init(thread_id)
            drv = sysbench.sql.driver()
            con = drv:connect()
            
            stmt0 = con:prepare("set session query_cache_type=off;")
            stmt0 = stmt0:execute()
    
            stmt = {}
            param = {}
    
            stmt = con:prepare(stmt_def[1])
            
            local nparam = #stmt_def - 1
            
            if nparam > 0 then
                param = {}
            end
            
            for p = 1, nparam do
                local btype = stmt_def[p+1]
                local len
            
                if type(btype) == "table" then
                    len = btype[2]
                    btype = btype[1]
                end
                if btype == sysbench.sql.type.VARCHAR or
                    btype == sysbench.sql.type.CHAR then
                        param[p] = stmt:bind_create(btype, len)
                else
                    param[p] = stmt:bind_create(btype)
                end
            end
            
            if nparam > 0 then
                stmt:bind_param(unpack(param))
            end
        end
        
        local function get_id()
            return sysbench.rand.default(1, 1000)
        end
        
        local r = {}
        local function get_string(r, i)
            if i == nil then
                x = math.random(1,#r)
            else
                x = i
            end
            return r[x]
        end
        
        {{PARAM_TABLE}}
        
        function event(thread_id)
            {{PARAM_SET}}
            stmt:execute()
        end
        '''
    
        data = {}
        sql_tmpl = f'''[[{sql_content}]]'''
        param_table = ''
        param_set = ''
        
        if sql_params_ex:
            if params_sync:
                param_set = 'ii = math.random(1,#p1)\n        '
            else:
                param_set = 'ii =  nil\n        '   
    
        i = 1
        for sql_params_pair in sql_params_ex:
            if sql_params_pair[1] == 'int':
                sql_tmpl += ', t.INT'
            else:
                sql_tmpl += ', {t.CHAR, 120}'
            param_table += 'local p%d = { %s }\n    ' % (i, str(sql_params_pair[0])[1:-1])
            param_set += 'param[%s]:set(get_string(p%s,ii))\n        ' % (i,i)
            i += 1
    
        data['SQL_TMPL'] = sql_tmpl
        data['PARAM_TABLE'] = param_table
        data['PARAM_SET'] = param_set
    
        with open(lua_file,'w') as f: 
            f.write(Template(lua_tmpl).render(data))
    
        return lua_file 
