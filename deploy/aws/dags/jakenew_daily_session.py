"""Jakenew daily trading session on AWS MWAA.

Same schedule as the Windows task it replaces (Jakenew_DailyRun): every weekday at 08:10 America/Chicago
(09:10 ET, 20 min before the open), DST handled by the timezone-aware start_date. The DAG does not run the
strategy inside an Airflow worker: it launches the Jakenew image as an ECS Fargate task and waits (deferred, so
no worker slot is held for the ~7 h session). The container exits by itself after the close, at once on an
exchange holiday, and its exit code decides success.

Retries: a crashed session is relaunched up to twice; campaign-flow rebuilds the day from its observation log on
EFS (restart-safe by design). reattach=True plus the container's EFS lock make sure a retry never runs a second
copy beside a task that is still alive.

Configuration lives in one Airflow Variable, `jakenew_ecs` (JSON), printed by the CloudFormation stack output
`AirflowVariableJson`:
    {"cluster": "...", "task_definition": "jakenew", "subnets": ["subnet-..", "subnet-.."],
     "security_groups": ["sg-.."], "assign_public_ip": "ENABLED", "log_group": "/ecs/jakenew",
     "region": "us-east-1"}
"""
from datetime import timedelta

import pendulum
from airflow import DAG
from airflow.providers.amazon.aws.operators.ecs import EcsRunTaskOperator

CFG = 'var.json.jakenew_ecs'

with DAG(
    dag_id='jakenew_daily_session',
    description='Jakenew Mag 7 trading session (ECS Fargate), weekdays 08:10 CT',
    schedule='10 8 * * 1-5',
    start_date=pendulum.datetime(2026, 11, 2, tz='America/Chicago'),
    catchup=False,                      # never replay missed days: a late session would trade stale signals
    max_active_runs=1,
    dagrun_timeout=timedelta(hours=10),
    render_template_as_native_obj=True,  # subnet / security-group lists render as real lists
    tags=['jakenew', 'trading', 'ecs'],
    default_args={
        'owner': 'jakenew',
        'retries': 2,
        'retry_delay': timedelta(minutes=3),
        'execution_timeout': timedelta(hours=10),
    },
) as dag:
    EcsRunTaskOperator(
        task_id='run_session',
        cluster='{{ %s.cluster }}' % CFG,
        task_definition='{{ %s.task_definition }}' % CFG,
        launch_type='FARGATE',
        overrides={},
        network_configuration={'awsvpcConfiguration': {
            'subnets': '{{ %s.subnets }}' % CFG,
            'securityGroups': '{{ %s.security_groups }}' % CFG,
            'assignPublicIp': '{{ %s.assign_public_ip }}' % CFG,
        }},
        awslogs_group='{{ %s.log_group }}' % CFG,
        awslogs_region='{{ %s.region }}' % CFG,
        awslogs_stream_prefix='ecs/jakenew',
        propagate_tags='TASK_DEFINITION',
        reattach=True,
        deferrable=True,
        waiter_delay=60,
        waiter_max_attempts=600,        # 10 h of 60 s checks
    )
