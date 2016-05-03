from __future__ import unicode_literals

from django.contrib.auth.models import User
from django.core.management.base import BaseCommand, CommandError
from random import random
from temba.contacts.models import Contact, ContactField, ContactURN
from temba.orgs.models import Org


TOTAL_ORGS = 10
TOTAL_CONTACTS = 100000

FIELDS_PER_ORG = 20
GROUPS_PER_ORG = 20


class Command(BaseCommand):
    help = "Installs a database suitable for performance testing"

    def handle(self, *args, **options):
        try:
            num_orgs = Org.objects.exists()
        except Exception:
            raise CommandError("Run migrate command first to create database tables")
        if num_orgs > 0:
            raise CommandError("Can only be run on an empty database")

        superuser = User.objects.create_superuser("root", "root@example.com", "password")

        orgs = self.create_orgs(superuser)
        fields = self.create_fields(orgs)
        contacts = self.create_contacts(orgs)

    def random_org(self, orgs):
        """
        Returns random org using the org weights, so some orgs are retuned more frequently than others
        """
        rnd = random()
        weight_sum = 0
        for org in orgs:
            weight_sum += org._weight
            if rnd <= weight_sum:
                return org

        return orgs[len(orgs) - 1]

    def create_orgs(self, superuser):
        last_org_weight = 1.0
        orgs = []
        for o in range(TOTAL_ORGS):
            org = Org.objects.create(name="Org #%d" % (o + 1), timezone="Africa/Kigali", brand='rapidpro.io',
                                     created_by=superuser, modified_by=superuser)
            org.initialize()
            orgs.append(org)

            admin = User.objects.create_user("admin%d" % (o + 1), "admin%d@example.com" % (o + 1), "password")
            org._admin = admin
            org.administrators.add(admin)

            org._weight = last_org_weight / 2.0
            last_org_weight = org._weight

        self.stdout.write("Created %d orgs" % len(orgs))

        # normalize the org weights so their sum is exactly 1
        weight_sum = sum([o._weight for o in orgs])
        for org in orgs:
            org._weight /= weight_sum

        return orgs

    def create_fields(self, orgs):
        fields = []
        for f in range(len(orgs) * FIELDS_PER_ORG):
            org = orgs[f % len(orgs)]
            field = ContactField.objects.create(org=org, key='field%d' % (f + 1), label="Field #%d" % (f + 1),
                                                value_type='T', created_by=org._admin, modified_by=org._admin)
            fields.append(field)

        self.stdout.write("Created %d fields" % len(fields))
        return fields

    def create_contacts(self, orgs):
        contacts = []
        for c in range(TOTAL_CONTACTS):
            org = self.random_org(orgs)
            contact = Contact.objects.create(org=org, name="Contact #%d" % (c + 1),
                                             created_by=org._admin, modified_by=org._admin)
            contacts.append(contact)

            handle = 'tweep%d' % (c + 1)
            ContactURN.objects.create(org=org, contact=contact, priority=50,
                                      scheme='twitter', path=handle, urn='twitter:%s' % handle)

        self.stdout.write("Created %d contacts" % len(contacts))
        return contacts
