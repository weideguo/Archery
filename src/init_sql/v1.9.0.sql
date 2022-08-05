alter table sql_config add unique index uniq_item(item),drop primary key,
    add id bigint unsigned not null auto_increment primary key first ;
    
-- sysbench
set @content_type_id=(select id from django_content_type where app_label='sql' and model='permission');
insert IGNORE INTO auth_permission (name, content_type_id, codename) VALUES
('菜单 sysbench', @content_type_id, 'menu_sysbench');

set @content_type_id=(select id from django_content_type where app_label='sql' and model='permission');
insert IGNORE INTO auth_permission (name, content_type_id, codename) VALUES
('提交压测申请', @content_type_id, 'sysbench_apply');

set @content_type_id=(select id from django_content_type where app_label='sql' and model='permission');
insert IGNORE INTO auth_permission (name, content_type_id, codename) VALUES
('审核压测申请', @content_type_id, 'sysbench_review');


CREATE TABLE `sysbench_workflow` (
  `id` int(11) NOT NULL AUTO_INCREMENT COMMENT '工单id',
  `title` varchar(50) NOT NULL COMMENT 'sysbench工单名',
  `resource_group_id` int(11) NOT NULL COMMENT '资源组id',
  `audit_auth_groups` varchar(255) NOT NULL COMMENT '审批权限组列表',
  `instance_id` int(11) NOT NULL COMMENT '实例id',
  `db_name` varchar(64) NOT NULL COMMENT '数据库',
  `sql_content` longtext NOT NULL COMMENT '压测的sql',
  `threads` smallint(6) NOT NULL COMMENT '并发数',
  `duration` smallint(6) NOT NULL COMMENT '压测持续时间',
  `sql_params` longtext DEFAULT NULL COMMENT '压测sql的参数',
  `param_spliter` varchar(5) DEFAULT ',' COMMENT '参数分割符',
  `params_sync` smallint(6) NOT NULL COMMENT '压测时sql参数是否同步变化',
  `status` varchar(50) NOT NULL COMMENT '状态',
  `user_name` varchar(30) NOT NULL COMMENT '发起人',
  `user_display` varchar(50) NOT NULL COMMENT '发起人显示名',
  `create_time` datetime(6) NOT NULL COMMENT '创建时间',
  `finish_time` datetime(6) DEFAULT NULL COMMENT '结束时间',
  PRIMARY KEY (`id`),
  KEY `resource_group_id` (`resource_group_id`),
  KEY `instance_id` (`instance_id`),
  CONSTRAINT FOREIGN KEY (`resource_group_id`) REFERENCES `resource_group` (`group_id`),
  CONSTRAINT FOREIGN KEY (`instance_id`) REFERENCES `sql_instance` (`id`)
) ENGINE=InnoDB DEFAULT CHARSET=utf8mb4 COMMENT 'sysbench压测配置表';


CREATE TABLE `sysbench_workflow_content` (
  `sysbench_workflow_id` int(11) NOT NULL COMMENT '工单id',
  `pid` int(11) NOT NULL COMMENT 'pid',
  `result` longtext NOT NULL COMMENT '执行结果的JSON格式',
  PRIMARY KEY (`sysbench_workflow_id`),
  CONSTRAINT FOREIGN KEY (`sysbench_workflow_id`) REFERENCES `sysbench_workflow` (`id`)
) ENGINE=InnoDB DEFAULT CHARSET=utf8mb4 COMMENT '压测申请表';


INSERT INTO sql_instance_tag (tag_code, tag_name, active, create_time) VALUES ('can_sysbench', '支持压测', 1, now());
