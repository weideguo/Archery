# -*- coding: UTF-8 -*-
import re
import sys
import json
import time
import logging
import traceback
import subprocess
from copy import deepcopy

import MySQLdb
from rest_framework import views, generics, status, serializers
from rest_framework.response import Response
from drf_spectacular.utils import extend_schema, OpenApiParameter
from django.http import Http404,QueryDict
from django.db import transaction
from django.utils.translation import gettext as _
from django.contrib.auth.models import Group
from django_redis import get_redis_connection
from django_q.tasks import async_task

from .serializers import SysbenchWorkflowSerializer
from .pagination import CustomizedPagination
from .filters import SysbenchWorkflowFilter

from common.utils.const import WorkflowDict
from common.config import SysConfig
from sql.utils.workflow_audit import Audit
from sql.plugins.sysbench import Sysbench as SysbenchOperate
from sql.utils.tasks import add_sql_schedule, del_schedule
from sql.utils.resource_group import user_groups, auth_group_users
from sql.utils import sysbench_review
from sql.notify import notify_for_audit
from sql.models import Users,ResourceGroup,Instance,SysbenchWorkflow,SysbenchWorkflowContent


logger = logging.getLogger('default')
workflow_type = WorkflowDict.workflow_type['sysbench']

class Sysbench(generics.ListAPIView):

    filterset_class = SysbenchWorkflowFilter
    pagination_class = CustomizedPagination
    serializer_class = SysbenchWorkflowSerializer
    queryset = SysbenchWorkflow.objects.all().order_by('-id')

    @extend_schema(summary='获取sysbench压测申请列表',
                   description='获取sysbench压测申请列表')

    def get(self, request):
        sysbench_workflow = self.filter_queryset(self.queryset)
        page_ins = self.paginate_queryset(queryset=sysbench_workflow)
        serializer_obj = self.get_serializer(page_ins, many=True)
        data = {
            'data': serializer_obj.data
        }
        return self.get_paginated_response(data)

    @extend_schema(summary='创建sysbench压测申请',
                   description='创建sysbench压测申请')
    def post(self, request):
        if not request.user.has_perm('sql.sysbench_apply'):
            return Response({'status': 1, 'msg': '当前用户没有创建sysbench压测申请权限'})

        data = request.data
        data = ajax_request_transfer(data)
        data['sql_params'] = json.dumps(data['sql_params']) if isinstance(data['sql_params'], list) else data['sql_params']

        data['user_name'] = request.user.username
        data['user_display'] = request.user.display

        try:
            group_id = ResourceGroup.objects.get(group_name=data['resource_group']['group_name']).group_id
        except Exception as msg:
            return Response({'status':1, 'msg':str(msg)})
        
        audit_auth_groups = Audit.settings(group_id, workflow_type)
        if not audit_auth_groups:
            return Response({'status': 1, 'msg': '审批流程不能为空，请先配置审批流程', 'data': {}})
        
        group_name = data.pop("resource_group")['group_name']
        instance_name = data.pop("instance")['instance_name']

        try:
            with transaction.atomic():
                resource_group = ResourceGroup.objects.get(group_name=group_name)
                instance = Instance.objects.get(instance_name=instance_name)
                sw = SysbenchWorkflow.objects.create(resource_group=resource_group, instance=instance, **data)
                sysbench_id = sw.id
                audit_result = Audit.add(workflow_type, sysbench_id)
                return Response({'status':0, 'data': {'id':sysbench_id}})
        except Exception as msg:
            logger.error(f"创建压测工单报错，错误信息：{traceback.format_exc()}")
            return Response({'status':1, 'msg':111})


class SysbenchStatus(generics.ListAPIView):
    @extend_schema(parameters=[OpenApiParameter(name='workflow_id', description='工单id', required=True, type=int), 
                               OpenApiParameter(name='audit_remark', description='审核备注', type=str), 
                              ],
                   summary='sysbench工单状态修改',
                   description='sysbench工单状态审核、取消、执行')
    def post(self, request, opt):
        user = request.user
        data = request.data
        data = ajax_request_transfer(data)
        workflow_id = data['workflow_id']
        audit_remark = data.get('audit_remark', '')

        if opt == "passed":
            # 通过审核
            try:
                is_can_review = Audit.can_review(user, workflow_id, workflow_type)
            except Exception as _msg:
                msg = str(_msg)
                is_can_review = False
            if not is_can_review:
                msg = msg if msg else '当前用户没有权限审核工单'
                return Response({'status':1, 'msg':msg})

            try:
                with transaction.atomic():
                    # 调用工作流接口审核
                    audit_id = Audit.detail_by_workflow_id(workflow_id=workflow_id, workflow_type=workflow_type).audit_id
                    audit_result = Audit.audit(audit_id, WorkflowDict.workflow_status['audit_success'], user.username, audit_remark)
                    # 按照审核结果更新业务表审核状态
                    if audit_result['data']['workflow_status'] == WorkflowDict.workflow_status['audit_success']:
                        # 将流程状态修改为审核通过
                        SysbenchWorkflow(id=workflow_id, status='workflow_review_pass').save(update_fields=['status'])
            except Exception as msg:
                logger.error(f"审核压测工单报错，错误信息：{traceback.format_exc()}")
                return Response({'status':1, 'msg':str(msg)})
            # 后续处理通知
            ##else:
            ##    # 开启了Pass阶段通知参数才发送消息通知
            ##    sys_config = SysConfig()
            ##    is_notified = 'Pass' in sys_config.get('notify_phase_control').split(',') \
            ##        if sys_config.get('notify_phase_control') else True
            ##    if is_notified:
            ##        async_task(notify_for_audit, audit_id=audit_id, audit_remark=audit_remark, timeout=60,
            ##                   task_name=f'sysbench-pass-{workflow_id}')


            return Response({'status':0,'msg':'通过审核，进入下一级'})

        elif opt == 'cancel':
            # 取消工单
            is_can_cancel,msg = sysbench_review.can_cancel(user, workflow_id)
            if not is_can_cancel:
                msg = msg if msg else '当前用户没有权限终止工单'
                return Response({'status':1, 'msg':msg})
            

            workflow_detail = SysbenchWorkflow.objects.get(id=workflow_id)

            #if not workflow_detail.status or not workflow_detail.status in ['workflow_manreviewing','workflow_review_pass','workflow_timingtask','workflow_queuing']:
            #    return Response({'status':1,'msg':'当前工单不能终止，请刷新页面'})

            try:
                with transaction.atomic():
                    # 调用工作流接口取消或者驳回
                    audit_id = Audit.detail_by_workflow_id(workflow_id=workflow_id, workflow_type=workflow_type).audit_id
                    # 仅待审核的需要调用工作流，审核通过的不需要
                    if workflow_detail.status != 'workflow_manreviewing':
                        # 增加工单日志
                        if user.username == workflow_detail.user_name:
                            Audit.add_log(audit_id=audit_id,
                                          operation_type=3,
                                          operation_type_desc='取消执行',
                                          operation_info="取消原因：{}".format(audit_remark),
                                          operator=request.user.username,
                                          operator_display=request.user.display
                                          )
                        else:
                            Audit.add_log(audit_id=audit_id,
                                          operation_type=2,
                                          operation_type_desc='审批不通过',
                                          operation_info="审批备注：{}".format(audit_remark),
                                          operator=request.user.username,
                                          operator_display=request.user.display
                                          )
                    else:
                        if user.username == workflow_detail.user_name:
                            Audit.audit(audit_id,
                                        WorkflowDict.workflow_status['audit_abort'],
                                        user.username, audit_remark)
                        # 非提交人需要校验审核权限
                        elif user.has_perm('sql.sysbench_review'):
                            Audit.audit(audit_id,
                                        WorkflowDict.workflow_status['audit_reject'],
                                        user.username, audit_remark)
                        else:
                            return Response({'status':1,'msg':'您无权限进行该操作'})
        
                    # 删除定时执行task
                    if workflow_detail.status == 'workflow_timingtask':
                        schedule_name = f"sysbench-timing-{workflow_id}"
                        del_schedule(schedule_name)

                    # 删除排队
                    redis_conn = get_redis_connection('default')
                    lock_prefix = 'archery-sysbench-{}-'.format(str(workflow_detail.instance_id))
                    lock_name = '{}{}'.format(lock_prefix, str(workflow_id))   
                    redis_conn.delete(lock_name)

                    # 杀死在运行的sysbench进程
                    r = SysbenchWorkflowContent.objects.get(sysbench_workflow_id=workflow_id)
                    pid = r.pid
                    result = r.result
                    returncode = 0
                    if pid and not result:
                        cmd_args = f"kill -9 {pid}"
                        p = subprocess.Popen(cmd_args, shell=True, stdout=subprocess.PIPE, stderr=subprocess.PIPE, universal_newlines=True)
                        stdout = p.stdout.read()
                        stderr = p.stderr.read()

                        p.communicate()
                        returncode = p.returncode 

                    # 将流程状态修改为人工终止流程
                    workflow_detail.status = 'workflow_abort'
                    workflow_detail.save()

                    if returncode:
                        return Response({'status':1, 'msg':f'工单状态已经修改，但终止sysbench进程失败，请刷新页面\n{stdout}\n{stderr}'})

            except Exception as msg:
                logger.error(f"取消压测工单报错，错误信息：{traceback.format_exc()}")
                return Response({'status':1, 'msg':str(msg)})
            #else:
            #    # 发送取消、驳回通知，开启了Cancel阶段通知参数才发送消息通知
            #    sys_config = SysConfig()
            #    is_notified = 'Cancel' in sys_config.get('notify_phase_control').split(',') \
            #        if sys_config.get('notify_phase_control') else True
            #    if is_notified:
            #        audit_detail = Audit.detail_by_workflow_id(workflow_id=workflow_id, workflow_type=workflow_type)
            #        if audit_detail.current_status in (
            #                WorkflowDict.workflow_status['audit_abort'], WorkflowDict.workflow_status['audit_reject']):
            #            async_task(notify_for_audit, audit_id=audit_detail.audit_id, audit_remark=audit_remark, timeout=60,
            #                       task_name=f'sysbench-cancel-{workflow_id}')
            return Response({'status':0,'msg':'压测工单已经被取消'})
            
        if opt == "execute":
            # 执行工单
            is_can_execute,msg = sysbench_review.can_execute(user, workflow_id)
            if not is_can_execute:
                msg = msg if msg else '当前用户没有权限执行工单'
                return Response({'status':1, 'msg':msg})
    
            audit_id = Audit.detail_by_workflow_id(workflow_id=workflow_id, workflow_type=workflow_type).audit_id
            workflow_detail = SysbenchWorkflow.objects.get(id=workflow_id)
            if workflow_detail.status != 'workflow_review_pass':
                return Response({'status':1,'msg':'当前工单不在审核通过状态，不能执行，请刷新页面'})
    
            # 删除定时执行任务
            schedule_name = f"sysbench-timing-{workflow_id}"
            del_schedule(schedule_name)
            # 加入执行队列
            async_task('sql_api.api_sysbench.sysbench_execute', workflow_id, request.user,
                       hook='sql_api.api_sysbench.sysbench_execute_callback',
                       timeout=-1, task_name=f'sysbench-execute-{workflow_id}')
            # 增加工单日志
            Audit.add_log(audit_id=audit_id,
                          operation_type=5,
                          operation_type_desc='执行工单',
                          operation_info='工单执行排队中',
                          operator=request.user.username,
                          operator_display=request.user.display)
            SysbenchWorkflow.objects.filter(id=workflow_id).update(status='workflow_queuing')
    
            return Response({'status':0,'msg':'工单已经进入执行队列'})

        else:
            return Response({'status':1,'msg':'不支持该参数'}, status=status.HTTP_404_NOT_FOUND)


class SysbenchDetail(generics.ListAPIView):
    @extend_schema(parameters=[OpenApiParameter(name='id', description='工单id', required=True, type=int), ],
                   summary='sysbench工单状态获取',
                   description='获取sysbench工单审批人、是否可审核、是否可执行、是否可取消、操作信息')
    def get(self, request):
        id = int(request.GET['id'])
        user = request.user
        audit_auth_group, current_audit_auth_group = Audit.review_info(id, workflow_type)
        try:
            is_can_review = Audit.can_review(user, id, workflow_type)
        except Exception as msg:
            is_can_review = False
        is_can_execute,_ = sysbench_review.can_execute(user, id)
        is_can_cancel,_ = sysbench_review.can_cancel(user, id)

        sysbench_workflow = SysbenchWorkflow.objects.get(pk=id)
        try:
            audit_detail = Audit.detail_by_workflow_id(workflow_id=id, workflow_type=workflow_type)
            audit_id = audit_detail.audit_id
            last_operation_info = Audit.logs(audit_id=audit_id).latest('id').operation_info
            if sysbench_workflow.status == 'workflow_manreviewing':
                current_audit_users = auth_group_users([current_audit_auth_group], audit_detail.group_id)
                current_audit_users_display = [audit_user.display for audit_user in current_audit_users]
                last_operation_info += '，当前审批人：' + ','.join(current_audit_users_display)
        except Exception as e:
            logger.debug(f'压测工单{id}无审核日志记录，错误信息{e}')
            last_operation_info = ''

        return Response({'status':0, 'data': {'audit_auth_group': audit_auth_group,'current_audit_auth_group': current_audit_auth_group,
                         'is_can_review': is_can_review, 'is_can_execute':is_can_execute, 'is_can_cancel':is_can_cancel,
                         'last_operation_info':last_operation_info}})


class SysbenchResult(generics.ListAPIView):
    @extend_schema(parameters=[OpenApiParameter(name='id', description='工单id', required=True, type=int), ],
                   summary='sysbench结果',
                   description='sysbench结果执行结果')
    def get(self, request):
        user = request.user
        workflow_id = int(request.GET['id'])
        try:
            _result = SysbenchWorkflowContent.objects.filter(sysbench_workflow_id=workflow_id).values('result')
            if len(_result) and 'result' in _result[0] and _result[0]["result"]:
                result = json.loads(_result[0]["result"])
            else:
                result = {}

            return Response({'status':0,'result':result})
        except Exception as msg:
                logger.error(f'获取压测结果报错，错误信息：{traceback.format_exc()}')
                return Response({'status':1, 'msg':str(msg)})


def sysbench_execute(workflow_id, user):
    """
    实现排队执行策略
    """
    audit_id = Audit.detail_by_workflow_id(workflow_id=workflow_id, workflow_type=workflow_type).audit_id

    sysbench_workflow = SysbenchWorkflow.objects.get(id=workflow_id)
    instance_id = sysbench_workflow.instance_id
    instance = Instance.objects.get(id=instance_id)

    sql_content = sysbench_workflow.sql_content
    sql_params = sysbench_workflow.sql_params
    param_spliter = sysbench_workflow.param_spliter
    params_sync = sysbench_workflow.params_sync


    redis_conn = get_redis_connection('default')

    lock_prefix = 'archery-sysbench-{}-'.format(str(instance_id))
    lock_name = '{}{}'.format(lock_prefix, str(workflow_id))   
    # key要设置过期时间，以实现超时退出
    is_set_success = redis_conn.set(lock_name,'',ex=86400, nx=True)    
    if not is_set_success:
        return -1, 'workflow_exception', '工单已经存在排队，不能再排队', {}

    def _get_workflow_id(elem):
        return int(elem.replace(lock_prefix,''))

    is_next = False
    gap = 1
    while redis_conn.exists(lock_name):
        _keys = redis_conn.keys(lock_prefix+'*')        #keys 可能存在风险，因为可能被屏蔽
        
        keys = [k.decode('utf8') for k in _keys]
        keys.sort(key=_get_workflow_id)
        if len(keys) and lock_name in keys and lock_name == keys[0]:
            # 如果最小的工单号为自己，则获得到锁，因此进行下一步
            is_next = True
            break
        else:
            time.sleep(gap)

    if not is_next:
        if SysbenchWorkflow.objects.get(id=workflow_id).status != 'workflow_abort':
            return -1, 'workflow_queue_timeout', '排队退出，排队超时', {}
        else:
            return -1, 'workflow_abort', '排队终止', {}

    
    # 在此之后进入运行状态，不能再终止
    execute_status = 'workflow_executing'
    SysbenchWorkflow.objects.filter(id=workflow_id).update(status=execute_status)
    Audit.add_log(audit_id=audit_id,
                  operation_type=5,
                  operation_type_desc='执行工单',
                  operation_info='工单开始执行' if user else '系统定时执行工单',
                  operator=user.username if user else '',
                  operator_display=user.display if user else '系统'
                  )

    sysbench = SysbenchOperate()
    # 进行拼接生成一个lua文件，使用tmp目录，让系统自动清理
    lua_file = '/tmp/{}_{}.lua'.format(sysbench_workflow.db_name, str(time.time()))
    sql_params = json.loads(sql_params)
    sysbench.generate_lua_file(sql_content, sql_params, param_spliter, params_sync, lua_file)

    args = {
                'lua_file': lua_file,
                'threads': sysbench_workflow.threads,
                'time': sysbench_workflow.duration,
                'mysql-db': sysbench_workflow.db_name,
                'mysql-user': instance.user,
                'mysql-password': instance.password,
                'mysql-host': instance.host,
                'mysql-port': instance.port
            }

    
    args_check_result = sysbench.check_args(args)
    cmd_args = sysbench.generate_args2cmd(args, shell=True)
    p = sysbench.execute_cmd(cmd_args, shell=True)

    logger.debug(cmd_args)
    # cmd_args 插入数据库？

    pid = p.pid
    SysbenchWorkflowContent(sysbench_workflow_id=workflow_id, pid=pid).save()


    stdout = p.stdout.read()
    stderr = p.stderr.read()

    p.communicate()
    returncode = p.returncode  
    sysbench_content = { 
        'returncode': returncode,
        'stdout': stdout,
        'stderr': stderr
    }

    # sysbench 运行结束才释放锁
    redis_conn.delete(lock_name)

    if returncode == 0:
        # 只有执行正常才进行解析
        for l in stdout.split('\n'):
            for field in ['min','avg','max','95th percentile']:
                if not field in sysbench_content:
                    filed_match = re.match(field+':\s+\d+\.\d+',l.strip())
                    if filed_match:
                        sysbench_content[field] = filed_match.group().split(":")[1].strip()
        execute_status = 'workflow_finish'
    else:
        execute_status = 'workflow_exception'

    operation_info='执行结果：{}'.format( _(execute_status) )
    return returncode, execute_status, operation_info, sysbench_content


def sysbench_execute_callback(task):

    execute_status = task.result[1] 
    operation_info = task.result[2] 
    sysbench_content = task.result[3]       
    workflow_id = task.args[0]
    # 可能存在人工终止，则不再更改状态
    if SysbenchWorkflow.objects.get(id=workflow_id).status not in ['workflow_abort']:         
        with transaction.atomic():
            # 插入执行结果 更改执行状态
            SysbenchWorkflow.objects.filter(id=workflow_id).update(status=execute_status, finish_time=task.stopped )
            if sysbench_content:
                SysbenchWorkflowContent.objects.filter(sysbench_workflow_id=workflow_id).update(result=json.dumps(sysbench_content))            
        
        audit_id = Audit.detail_by_workflow_id(workflow_id=workflow_id, workflow_type=workflow_type).audit_id
        Audit.add_log(audit_id=audit_id,
                        operation_type=6,
                        operation_type_desc='执行结束',
                        operation_info=operation_info,
                        operator='',
                        operator_display='系统'
                    )


def ajax_request_transfer(data):
    """
    兼容jquery ajax请求，在此进行一些转置成字典类型
    """

    _data = deepcopy(data)
    if isinstance(data, QueryDict):
        _data = data.dict()
        __data = data.dict()
        for k in __data:
            #list类型转换
            if k[-2:] == '[]':
                sub_data = data.getlist(k)
                _data.pop(k)
                sub_k = k[:-2]
                _data[sub_k] = sub_data
    
                # 在此必须要求数据按照 [0][]、[1][]、[2][]类似提升式迭代
                while re.match('\[\d+\]', sub_k[-3:]):
                    _data.pop(sub_k)
                    sub_k = sub_k[:-3]
                    if sub_k not in _data:
                        _data[sub_k]=[]
                    _data[sub_k].append(sub_data)
            #dict类型转换
            elif re.findall('(?<=\[).*?(?=\])',k):
                field = re.findall("(?<=\[).*?(?=\])",k)[0]
                _field = k.replace('['+field+']','')
                if not _field in _data:
                    _data[_field] = {}
                _data[_field][field] = data.get(k)
                _data.pop(k)

    return _data

