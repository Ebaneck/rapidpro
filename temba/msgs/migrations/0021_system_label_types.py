# -*- coding: utf-8 -*-
from __future__ import unicode_literals

from django.db import models, migrations


class Migration(migrations.Migration):

    dependencies = [
        ('msgs', '0020_update_label_triggers'),
    ]

    operations = [
        migrations.AlterField(
            model_name='label',
            name='label_type',
            field=models.CharField(default='L', help_text='Label type', max_length=1, choices=[('I', 'Inbox'), ('W', 'Flows'), ('A', 'Archived'), ('O', 'Outbox'), ('S', 'Sent'), ('X', 'Failed'), ('F', 'User Defined Folder'), ('L', 'User Defined Label')]),
            preserve_default=True,
        ),
        migrations.AddField(
            model_name='label',
            name='count',
            field=models.PositiveIntegerField(default=0, help_text='Total number of messages with this label'),
            preserve_default=True,
        ),
    ]
