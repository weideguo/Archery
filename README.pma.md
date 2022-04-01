
集成phpmyadmin时


# 配置设置
修改pma配置以支持其他页面通过iframe嵌入
``` php
// cat /etc/phpmyadmin/config.user.inc.php
<?php
$cfg['AllowThirdPartyFraming'] = true;
```

修改页面属性（似乎没有必要）
``` js
// js/src/cross_framing_protection.js 
if (self == top) {document.documentElement.style.display = 'block';} else {document.documentElement.style.display = 'block';}
```

在nginx配置文件中设置pma的登陆页跟当前站点处于同一源站
```
# pma的设置
server{
    # 当前站点的其他配置 
    #
    location /pma/ {
      proxy_pass http://10.101.6.17:9235/;
    }
    # pma退出页
    location /index.php {
      rewrite ^/(.*) http://10.101.6.17:9235/ permanent;  
    }
}
```


# 注意事项

* 因为pma的登陆状态使用cookie保持，直接关闭浏览器的tab页面不会导致cookie被清除，因此如果要退出登陆，必须手动点击pma的退出按钮，否则不能切换登陆其他的实例。
