import os
import sys
import regex
import json
import time
from uuid import uuid4
from django.core.management.base import BaseCommand, CommandError
from temba.orgs.models import Org
from temba.flows.models import Flow, FlowRun, FlowStep, RuleSet, RULE_SET
from temba.contacts.models import Contact, TEL_SCHEME
from temba.msgs.models import Msg, HANDLED
from temba.utils import json_date_to_datetime
from temba.channels.models import SEND

class Command(BaseCommand): # pragma: no cover
    help = 'Import the flow and runs contained in the passed in json file to the org with the passed id'
    missing_args_message = 'org_id file1.json [file2.json]'

    def add_arguments(self, parser):
        # Positional arguments
        parser.add_argument('org', type=int,
                            help="The id of the organization the flow will be imported into")
        parser.add_argument('files', nargs='+',
                            help="The files to import")
        parser.add_argument('--overwrite', dest='overwrite',
                            action='store_const', const=True, default=False,
                            help='Whether to overwrite already existing flows')

    def insert_empty_runs(self, flow, ruleset, start_date, empty_runs):
        # do a batch insert of the flow runs
        batch_runs = []
        contacts = []

        for empty in empty_runs:
            contact = Contact.objects.filter(org=self.org, uuid=empty['contact_uuid']).first()
            run = FlowRun(org=self.org, flow=flow,
                          contact=contact,
                          is_active=False,
                          created_on=start_date,
                          expires_on=start_date,
                          exited_on=start_date,
                          exit_type=FlowRun.EXIT_TYPE_EXPIRED,
                          modified_on=start_date)

            batch_runs.append(run)
            contacts.append(contact)

        # insert them
        FlowRun.objects.bulk_create(batch_runs)

        # select the flow run ids back out
        runs = FlowRun.objects.filter(flow=flow,
                                      contact__in=contacts).select_related('contact')

        # for each run, create our step
        batch_steps = []
        for run in runs:
            step = FlowStep(run=run,
                            contact=run.contact,
                            step_type=RULE_SET,
                            step_uuid=ruleset.uuid,
                            arrived_on=start_date)
            batch_steps.append(step)

        FlowStep.objects.bulk_create(batch_steps)

    def insert_completed_runs(self, flow, ruleset, category_to_rule, start_date, completed_runs):
        # do a batch insert of the flow runs
        batch_runs = []
        contacts = []
        for completed in completed_runs:
            contact = Contact.objects.get(org=self.org, uuid=completed['contact_uuid'])

            run = FlowRun(org=self.org, flow=flow,
                          contact=contact,
                          is_active=False,
                          created_on=start_date,
                          expires_on=start_date,
                          exited_on=start_date,
                          exit_type=FlowRun.EXIT_TYPE_COMPLETED,
                          modified_on=start_date)

            batch_runs.append(run)
            contacts.append(contact)

        # insert them
        FlowRun.objects.bulk_create(batch_runs)

        # select the flow run ids back out
        runs = FlowRun.objects.filter(flow=flow,
                                      contact__in=contacts).select_related('contact')

        # map from the contact uuid to to the run
        contact_to_run = dict()
        for run in runs:
            contact_to_run[run.contact.uuid] = run

        # for each run, create our step
        for completed in completed_runs:
            run = contact_to_run[completed['contact_uuid']]
            rule = category_to_rule[completed.get('category', "All Responses").lower()]
            left_on = json_date_to_datetime(completed['send_date'])

            step = FlowStep.objects.create(run=run,
                                           contact=run.contact,
                                           step_type=RULE_SET,
                                           step_uuid=ruleset.uuid,
                                           arrived_on=start_date,
                                           rule_uuid=rule.uuid,
                                           rule_category=rule.get_category_name('eng'),
                                           rule_value=completed['message'][:640])


            # create the incoming message for this step
            msg = Msg.create_incoming(self.channel, None, completed['message'],
                                      user=self.user, date=left_on, org=self.org, contact=run.contact,
                                      status=HANDLED)
            step.messages.add(msg)

    def import_file(self, filename, overwrite=False):
        print "*** Importing %s" % filename

        # read the file in
        with open(filename) as import_file:
            data = json.load(import_file)

            # read our flow
            flow_definition = data['poll_definition']
            name = flow_definition['metadata']['name']

            print "  === %s" % name

            # check if the flow exists
            flow = Flow.objects.filter(org=self.org, name=name, is_active=True).first()
            if flow:
                if overwrite:
                    print "  !!! Flow exists [%d], deleting" % flow.id
                    flow.release()
                else:
                    print "  !!! Flow exists [%d], ignoring" % flow.id
                    return

            # update our ruleset uuid
            ruleset_uuid = str(uuid4())
            flow_definition['entry'] = ruleset_uuid
            flow_definition['rule_sets'][0]['uuid'] = ruleset_uuid
            flow_definition['rule_sets'][0]['y'] = 250
            for rule in flow_definition['rule_sets'][0]['rules']:
                rule['uuid'] = str(uuid4())

            # remove any actionsets
            actionset = flow_definition['action_sets'][0]
            flow_definition['action_sets'] = []

            # add a note instead
            flow_definition['metadata']['notes'] = [dict(x=actionset['x'], y=actionset['y'],
                                                         title=name,
                                                         body=actionset['actions'][0]['msg']['eng']),
                                                    dict(x=500, y=0,
                                                         title="Filename", body=os.path.basename(filename))]

            flow = Flow.create(self.org, self.user, name, Flow.FLOW)
            flow.update(flow_definition, self.user, force=True)
            print "  --- Flow definition imported [%d] (%s)" % (flow.id, flow.uuid)

            # the date this poll started "2015-04-21T15:05:36.045Z"
            start_date = json_date_to_datetime(data['start_date'])

            flow.created_on = start_date
            flow.is_archived = True
            flow.save()

            # get the ruleset uuid for this flow, we need this when creating steps
            ruleset = RuleSet.objects.get(flow=flow)

            # build our mapping of category to rule uuid
            category_to_rule = dict()
            for rule in ruleset.get_rules():
                category_to_rule[rule.get_category_name('eng').lower()] = rule

            # now create the runs
            empty_runs = []
            completed_runs = []
            missing = 0

            total_runs = len(data['response'])
            current_run = 0
            start = time.time()

            for response in data['response']:
                if not Contact.objects.filter(org=self.org, uuid=response['contact_uuid']).first():
                    missing += 1

                elif not response['has_replied']:
                    empty_runs.append(response)

                    if len(empty_runs) >= 1000:
                        self.insert_empty_runs(flow, ruleset, start_date, empty_runs)

                        # reset our empty runs
                        empty_runs = []

                else:
                    completed_runs.append(response)

                    if len(completed_runs) >= 1000:
                        self.insert_completed_runs(flow, ruleset, category_to_rule, start_date, completed_runs)

                        # reset our completed runs
                        completed_runs = []

                current_run += 1
                if current_run % 1000 == 0:
                    estimated = (time.time() - start) / (current_run / float(total_runs)) / 60
                    print "  +++ processed %d of %d responses (%.2fs) (%.2fm est)" % \
                          (current_run, total_runs, time.time() - start, estimated)

            if empty_runs:
                self.insert_empty_runs(flow, ruleset, start_date, empty_runs)

            if completed_runs:
                self.insert_completed_runs(flow, ruleset, category_to_rule, start_date, completed_runs)

            print "  ^^^ %d responses imported (%.2fs)" % (current_run, time.time() - start)
            print "  --- %d missing contacts" % missing

            # calculate our flow stats
            print "  --- Calculating flow stats"
            flow.do_calculate_flow_stats()
            print "  +++ Flow stats calculated"

    def handle(self, *args, **options):
        self.org = Org.objects.filter(id=options['org']).first()
        if not self.org:
            print "No organization found with id %d" % options['org']
            sys.exit(1)

        self.user = self.org.administrators.all().first()
        self.channel = self.org.get_channel(TEL_SCHEME, SEND)

        for file in options['files']:
            self.import_file(file, options['overwrite'])

