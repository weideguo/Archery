# -*- coding: UTF-8 -*-

import simplejson as json

from django.http import HttpResponse

from common.config import SysConfig


def opt_limit_host_check(allow_hosts=[], allow_hosts_parameter=""):              
    def _decorator(func):            
        def _wrapper(request):
            # do something here
            result = {'status': 0, 'msg': 'ok', 'data': {}}
            
            #超级管理员可以在任意位置查询
            if not request.user.is_superuser:
                #如果使用nginx，配置以下确保获取到原始请求ip
                #proxy_set_header X-Real-IP $remote_addr;
                
                if 'HTTP_X_REAL_IP' in request.META:
                    from_host=str(request.META['HTTP_X_REAL_IP'])
                else:
                    from_host=str(request.META['REMOTE_ADDR'])
                
                if allow_hosts:
                    _allow_hosts = allow_hosts
                else:
                    _allow_hosts = SysConfig().get(allow_hosts_parameter)  #可能为None
                    if _allow_hosts:
                       _allow_hosts = _allow_hosts.strip().split(',')

                if _allow_hosts and from_host not in _allow_hosts:
                    result['status'] = 1
                    result['msg'] = '操作的主机 %s 必须在指定的ip中 %s' % (from_host,_allow_hosts)
                    return HttpResponse(json.dumps(result), content_type='application/json') 
            
            return func(request)
        return _wrapper
    return _decorator


