# -*- coding: UTF-8 -*-
import time

import simplejson as json
from django.contrib.auth.decorators import permission_required,login_required
from django.http import HttpResponse

from common.utils.extend_json_encoder import ExtendJSONEncoder
from .models import Audit



@login_required
def audit(request):
    """获取用户提交的操作信息"""
    result = {}
    opt_type = request.POST.get('opt_type')

    result['opt_username'] = request.user.username
    result['opt_display'] = request.user.display
    result['opt_type'] = opt_type 
    # result['opt_date'] = time.strftime('%Y-%m-%d %H:%M:%S',time.localtime())   # 由orm自行生成

    audit = Audit(**result)
    audit.save()

    return HttpResponse(json.dumps(result, cls=ExtendJSONEncoder, bigint_as_string=True),
                        content_type='application/json')


