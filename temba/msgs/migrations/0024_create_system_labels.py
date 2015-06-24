# -*- coding: utf-8 -*-
from __future__ import unicode_literals

from django.db import models, migrations


def create_system_labels(apps, schema_editor):
    Org = apps.get_model('orgs', 'Org')
    Label = apps.get_model('msgs', 'Label')
    Msg = apps.get_model('msgs', 'Msg')

    def create_label(name, label_type, msg_filter):
        print " > creating system label: %s" % name

        label = Label.objects.create(org=org, name=name, label_type=label_type,
                                     created_by=org.created_by, modified_by=org.modified_by)
        if msg_filter:
            messages = Msg.objects.filter(org=org, contact__is_test=False).filter(**msg_filter)
            label.msgs.add(*messages)

    for org in Org.objects.all():
        print "Creating system labels for: %s" % org.name

        # use . prefix so system label names don't clash with user label names
        create_label(".Inbox", 'I', dict(direction='I', visibility='V', msg_type='I'))
        create_label(".Flow", 'W', dict(direction='I', visibility='V', msg_type='F'))
        create_label(".Archived", 'A', dict(direction='I', visibility='A'))
        create_label(".Outbox", 'O', dict(direction='O', status='Q'))
        create_label(".Sent", 'S', None)
        create_label(".Failed", 'X', dict(direction='O', status='F'))


class Migration(migrations.Migration):

    dependencies = [
        ('msgs', '0023_index_for_outbox'),
    ]

    operations = [
        migrations.RunPython(create_system_labels)
    ]
