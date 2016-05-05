from __future__ import unicode_literals

import math
import pytz
import random

from django.contrib.auth.models import User
from django.core.management.base import BaseCommand, CommandError
from django.utils.timezone import now
from temba.channels.models import Channel, ANDROID, NEXMO, TWITTER
from temba.contacts.models import Contact, ContactField, ContactGroup, ContactURN, URN, TEL_SCHEME, TWITTER_SCHEME
from temba.msgs.models import Label, Msg, FLOW, INBOX, INCOMING, HANDLED
from temba.orgs.models import Org
from temba.values.models import Value


DEFAULT_NUM_ORGS = 100
DEFAULT_NUM_CONTACTS = 2000000
DEFAULT_NUM_MESSAGES = 5000000

FIELDS_PER_ORG = 20
GROUPS_PER_ORG = 20
LABELS_PER_ORG = 10

# how much to bias to apply when allocating contacts, messages and runs. For 100 orgs, a bias of 5 gives the first org
# about 40% of the content.
ORG_BIAS = 5

USER_PASSWORD = "password"
CONTACT_NAMES = (None, "Jon", "Daenerys", "Melisandre", "Arya", "Sansa", "Tyrion", "Cersei", "Gregor", "Khal")
CONTACT_LANGS = (None, "eng", "fra", "kin")
CONTACT_HAS_TEL_PROB = 0.9  # 9/10 contacts have a phone number
CONTACT_HAS_TWITTER_PROB = 0.1  # 1/10 contacts have a twitter handle
CONTACT_IS_FAILED_PROB = 0.01  # 1/100 contacts are failed
CONTACT_IS_BLOCKED_PROB = 0.01  # 1/100 contacts are blocked
CONTACT_IS_DELETED_PROB = 0.005  # 1/200 contacts are deleted
CONTACT_FIELD_VALUES = ("yes", "no", "maybe", 1, 2, 3, 10, 100)
MESSAGE_TEXT_WORDS = ("snow", "throne", "has", "knight", "maybe", "wolf")
MESSAGE_IS_FLOW_PROB = 0.9  # 9/10 incoming messages are handled by a flow
MESSAGE_ARCHIVED_PROB = 0.5  # 1/2 non-flow incoming messages are archived (i.e. 5/100 of total incoming)
MESSAGE_LABELLED_PROB = 0.5  # 1/2 incoming messages are labelled


class Command(BaseCommand):
    help = "Installs a database suitable for testing"

    def add_arguments(self, parser):
        parser.add_argument('--num-orgs', type=int, action='store', dest='num_orgs', default=DEFAULT_NUM_ORGS)
        parser.add_argument('--num-contacts', type=int, action='store', dest='num_contacts', default=DEFAULT_NUM_CONTACTS)
        parser.add_argument('--num-messages', type=int, action='store', dest='num_messages', default=DEFAULT_NUM_MESSAGES)

    def handle(self, num_orgs, num_contacts, num_messages, **kwargs):
        self.check_db_state()

        superuser = User.objects.create_superuser("root", "root@example.com", "password")

        orgs = self.create_orgs(superuser, num_orgs)
        self.create_fields(orgs, FIELDS_PER_ORG)
        self.create_groups(orgs, GROUPS_PER_ORG)
        self.create_labels(orgs, LABELS_PER_ORG)
        self.create_contacts(orgs, num_contacts)
        self.create_incoming_messages(orgs, num_messages)

    def check_db_state(self):
        """
        Checks whether database is in correct state before continuing
        """
        try:
            has_data = Org.objects.exists()
        except Exception:  # pragma: no cover
            raise CommandError("Run migrate command first to create database tables")
        if has_data:
            raise CommandError("Can only be run on an empty database")

    def random_org(self, orgs):
        """
        Returns a random org with bias toward the orgs with the lowest indexes
        """
        return random_choice(orgs, bias=ORG_BIAS)

    def create_orgs(self, superuser, num_total):
        orgs = []
        for o in range(num_total):
            org = Org.objects.create(name="Org #%d" % (o + 1), timezone=random.choice(pytz.all_timezones),
                                     brand='rapidpro.io', created_by=superuser, modified_by=superuser)
            org.initialize()
            orgs.append(org)

            # each org has a user of every type
            admin = User.objects.create_user("admin%d" % (o + 1), "org%d_admin@example.com" % (o + 1), USER_PASSWORD)
            org._admin = admin
            org.administrators.add(admin)

            editor = User.objects.create_user("editor%d" % (o + 1), "org%d_editor@example.com" % (o + 1), USER_PASSWORD)
            org.editors.add(editor)

            viewer = User.objects.create_user("viewer%d" % (o + 1), "org%d_viewer@example.com" % (o + 1), USER_PASSWORD)
            org.viewers.add(viewer)

            surveyor = User.objects.create_user("surveyor%d" % (o + 1), "org%d_surveyor@example.com" % (o + 1), USER_PASSWORD)
            org.surveyors.add(surveyor)

            # each org has 3 channels
            android = Channel.objects.create(org=org, name="Android", channel_type=ANDROID,
                                             address='1234', scheme='tel',
                                             created_by=superuser, modified_by=superuser)
            bulk_tel = Channel.objects.create(org=org, name="Nexmo", channel_type=NEXMO,
                                              address='2345', scheme='tel', parent=android,
                                              created_by=superuser, modified_by=superuser)
            twitter = Channel.objects.create(org=org, name="Twitter", channel_type=TWITTER,
                                             address='org%d' % o, scheme='twitter',
                                             created_by=superuser, modified_by=superuser)

            # we'll cache some metadata on the org object to speed up creation of contacts etc
            org._fields = []
            org._groups = []
            org._contacts = []
            org._labels = []
            org._channels_by_scheme = {TEL_SCHEME: [android, bulk_tel], TWITTER_SCHEME: [twitter]}

        self.stdout.write("Created %d orgs" % len(orgs))
        return orgs

    def create_fields(self, orgs, num_per_org):
        total_fields = len(orgs) * num_per_org
        for f in range(total_fields):
            org = orgs[f % len(orgs)]
            field = ContactField.objects.create(org=org, key='field%d' % (f + 1), label="Field #%d" % (f + 1),
                                                value_type='T', created_by=org._admin, modified_by=org._admin)
            org._fields.append(field)

        self.stdout.write("Created %d fields (%d per org)" % (total_fields, num_per_org))

    def create_groups(self, orgs, num_per_org):
        total_groups = len(orgs) * num_per_org
        for g in range(total_groups):
            org = orgs[g % len(orgs)]
            group = ContactGroup.user_groups.create(org=org, name="Group #%d" % (g + 1),
                                                    created_by=org._admin, modified_by=org._admin)
            org._groups.append(group)

        self.stdout.write("Created %d groups (%d per org)" % (total_groups, num_per_org))

    def create_contacts(self, orgs, num_total):
        self.stdout.write("Creating contacts...")

        for c in range(num_total):
            org = orgs[c] if c < len(orgs) else self.random_org(orgs)  # ensure every org gets at least one contact
            name = random_choice(CONTACT_NAMES)

            contact = Contact.objects.create(org=org,
                                             name=name,
                                             language=random_choice(CONTACT_LANGS),
                                             is_failed=probability(CONTACT_IS_FAILED_PROB),
                                             is_blocked=probability(CONTACT_IS_BLOCKED_PROB),
                                             is_active=probability(1 - CONTACT_IS_DELETED_PROB),
                                             created_by=org._admin, modified_by=org._admin)

            # maybe give the contact some URNs
            contact._urns = []

            if probability(CONTACT_HAS_TEL_PROB):
                phone = '+2507%08d' % c
                contact._urns.append(ContactURN.objects.create(org=org, contact=contact, priority=50,
                                                               scheme=TEL_SCHEME, path=phone, urn=URN.from_tel(phone)))
            if probability(CONTACT_HAS_TWITTER_PROB):
                handle = '%s%d' % (name.lower() if name else 'tweep', c)
                contact._urns.append(ContactURN.objects.create(org=org, contact=contact, priority=50,
                                                               scheme=TWITTER_SCHEME, path=handle, urn=URN.from_twitter(handle)))

            # give contact values for random sample of their org's fields
            contact_fields = random.sample(org._fields, random.randrange(len(org._fields)))
            contact_values = []
            for field in contact_fields:
                val = random_choice(CONTACT_FIELD_VALUES)
                contact_values.append(Value(org=org, contact=contact, contact_field=field, string_value=str(val)))
            Value.objects.bulk_create(contact_values)

            # place the contact in a biased sample of up to half of their org's groups
            for g in range(random.randrange(len(org._groups) / 2)):
                group = random_choice(org._groups, 3)
                group.contacts.add(contact)

            org._contacts.append(contact)

            if (c + 1) % 1000 == 0 or c == (num_total - 1):
                self.stdout.write(" > Created %d of %d contacts" % (c + 1, num_total))

    def create_labels(self, orgs, num_per_org):
        total_labels = len(orgs) * num_per_org
        for l in range(total_labels):
            org = orgs[l % len(orgs)]
            group = Label.label_objects.create(org=org, name="Label #%d" % (l + 1),
                                               created_by=org._admin, modified_by=org._admin)
            org._labels.append(group)

        self.stdout.write("Created %d labels (%d per org)" % (total_labels, num_per_org))

    def create_incoming_messages(self, orgs, num_total):
        self.stdout.write("Creating incoming messages...")

        for m in range(num_total):
            org = self.random_org(orgs)
            contact = random_choice(org._contacts)
            contact_urn = random_choice(contact._urns) if contact._urns else None
            channel = random_choice(org._channels_by_scheme[contact_urn.scheme]) if contact_urn else None
            text = " ".join(random.sample(MESSAGE_TEXT_WORDS, 3))
            msg_type = FLOW if probability(MESSAGE_IS_FLOW_PROB) else INBOX
            archived = msg_type == INBOX and probability(MESSAGE_ARCHIVED_PROB)
            visibility = Msg.VISIBILITY_ARCHIVED if archived else Msg.VISIBILITY_VISIBLE

            msg = Msg.all_messages.create(org=org, contact=contact, contact_urn=contact_urn, channel=channel,
                                          text=text, visibility=visibility, msg_type=msg_type,
                                          direction=INCOMING, status=HANDLED,
                                          created_on=now(), modified_on=now())

            # give some messages a random label with bias toward first labels
            if probability(MESSAGE_LABELLED_PROB):
                msg.labels.add(random_choice(org._labels, bias=3))

            if (m + 1) % 1000 == 0 or m == (num_total - 1):
                self.stdout.write(" > Created %d of %d messages" % (m + 1, num_total))


def probability(prob):
    return random.random() < prob


def random_choice(seq, bias=1):
    return seq[int(math.pow(random.random(), bias) * len(seq))]
