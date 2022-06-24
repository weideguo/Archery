from django.db import transaction

from sql.utils.workflow_audit import Audit
from common.utils.const import WorkflowDict
from sql.models import SysbenchWorkflow,WorkflowAudit
from sql.utils.resource_group import user_groups, auth_group_users

workflow_type = WorkflowDict.workflow_type['sysbench']

def can_execute(user, workflow_id):
    """
    判断用户当前是否可执行
    1.并且为组内用户，且有审核权限
    2.为提交人，且拥有提交权限
    :param user:
    :param workflow_id:
    :return:
    """
    result = False
    workflow_detail = SysbenchWorkflow.objects.get(id=workflow_id)
    if not workflow_detail.status in ['workflow_review_pass', 'workflow_timingtask']:
        return False, '当前状态不在可执行状态'

    # 当前登录用户有资源组粒度执行权限，并且为组内用户
    group_ids = [group.group_id for group in user_groups(user)]
    if workflow_detail.resource_group_id in group_ids and user.has_perm('sql.sysbench_review'):
        result = True
    # 当前登录用户为提交人, 且拥有提交权限
    if workflow_detail.user_name == user.username and user.has_perm('sql.sysbench_apply'):
        result = True
    return result, ''


def can_cancel(user, workflow_id):
    """
    判断用户当前是否是可终止
    1.并且为组内用户，且有审核权限
    2.为提交人，且拥有提交权限
    :param user:
    :param workflow_id:
    :return:
    """
    result = False
    workflow_detail = SysbenchWorkflow.objects.get(id=workflow_id)
    if workflow_detail.status in ['workflow_abort','workflow_finish','workflow_exception','workflow_executing','workflow_queue_timeout']:
        return False, '当前工单不在可取消状态'

    group_ids = [group.group_id for group in user_groups(user)]
    if workflow_detail.resource_group_id in group_ids and user.has_perm('sql.sysbench_review'):
        result = True
    if workflow_detail.user_name == user.username and user.has_perm('sql.sysbench_apply'):
        result = True
    return result, ''
