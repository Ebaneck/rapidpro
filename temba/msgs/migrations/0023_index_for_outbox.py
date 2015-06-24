# -*- coding: utf-8 -*-
from __future__ import unicode_literals

from django.db import models, migrations


class Migration(migrations.Migration):

    dependencies = [
        ('msgs', '0022_update_label_triggers'),
    ]

    operations = [
        # for fast lookup of outbox messages
        migrations.RunSQL("CREATE INDEX msgs_msg_outbox ON "
                          "msgs_msg(org_id, created_on DESC) "
                          "WHERE direction = 'O' AND status = 'Q';",
                          "DROP INDEX msgs_msg_outbox;")
    ]
