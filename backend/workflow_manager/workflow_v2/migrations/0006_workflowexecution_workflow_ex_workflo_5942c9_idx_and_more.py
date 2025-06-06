# Generated by Django 4.2.1 on 2025-02-04 04:12

from django.db import migrations, models


class Migration(migrations.Migration):
    dependencies = [
        ("workflow_v2", "0005_workflowexecution_tags"),
    ]

    operations = [
        migrations.AddIndex(
            model_name="workflowexecution",
            index=models.Index(
                fields=["workflow_id", "-created_at"],
                name="workflow_ex_workflo_5942c9_idx",
            ),
        ),
        migrations.AddIndex(
            model_name="workflowexecution",
            index=models.Index(
                fields=["pipeline_id", "-created_at"],
                name="workflow_ex_pipelin_126dbf_idx",
            ),
        ),
    ]
