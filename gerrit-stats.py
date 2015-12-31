#!/usr/bin/env python

import datetime
import logging
import re
import simplejson
import urllib
import urllib2
import yaml
import json

logging.basicConfig(level='CRITICAL', format='%(levelname)s %(message)s')

query = 'project:^openstack/fuel-.* -project:^openstack/fuel-plugin.* status:merged'

url = 'https://review.openstack.org/changes/?q=%s&n=500&o=MESSAGES' % urllib.quote(query)

CI_DONE_MESSAGE_REGEX = re.compile('^Patch\sSet\s(\d+):\s(-)?Verified.1')
PATCHSET_UPLOAD_MESSAGE_REGEX = re.compile('^(Uploaded patch set (\d+)\.|Patch Set (\d+)\: Commit message was updated)$')

changes = []
i = 0
lastcount = 1
morechanges = True
lastelement = None
gerritversion = None
now = datetime.datetime.now()

jenkins_id = 3
fuel_ci_id = 8971

projects = {}
drshn_bfr_mrg = dict()

def gerritdate2date(date):
    return datetime.datetime.strptime(date[:-3], '%Y-%m-%d %H:%M:%S.%f')

def pretty_duration(total_seconds):
       hours = total_seconds / 3600
       minutes = total_seconds % 3600 / 60
       seconds = total_seconds % 3600 % 60
       result = ""
       if hours:
            result += "%sh" % hours
       if minutes:
            result += "%sm" % minutes
       if seconds:
            result += "%ss" % seconds

       return  result

while morechanges:
    logging.info('Requesting changes from gerrit')
    if not gerritversion:
        try:
            furl = url+'&S=%s' % int(i*100)
            logging.debug('URL: %s' % furl)
            ua = urllib2.urlopen(furl)
            logging.info('Gerrit version is >= 2.9')
            gerritversion = '>=2.9'
        except urllib2.HTTPError as e:
            if e.msg == 'Bad Request':
                furl = url+'&N=%s' % lastelement if lastelement else url
                logging.debug('URL: %s' % furl)
                ua = urllib2.urlopen(furl)
                logging.info('Gerrit version is <= 2.8')
                gerritversion = '<=2.8'
            else:
                raise
    elif gerritversion == '<=2.8':
        furl = url+'&N=%s' % lastelement if lastelement else url
        logging.debug('URL: %s' % furl)
        ua = urllib2.urlopen(furl)
    elif gerritversion == '>=2.9':
        furl = url+'&S=%s' % int(i*100)
        logging.debug('URL: %s' % furl)
        ua = urllib2.urlopen(furl)
    else:
        raise Exception('Unknown gerrit version')

    data = simplejson.loads(ua.read()[5:])
    for change in data:
        #logging.info('Processing change %s into %s' % (change['_number'], change['project']))
        project = change['project']
        created = gerritdate2date(change['created'])
        if now - datetime.timedelta(days=7) < created:
            changes.append(change)
            if project not in projects:
                projects[project] = {}

            if 'commits' not in projects[project]:
                projects[project]['commits'] = 1
            else:
                projects[project]['commits'] += 1

            lags = {}
            if 'messages' in change:
                for message in change['messages']:
                    revision = message['_revision_number']
                    start = None
                    if revision not in lags:
                        lags[revision] = {}

                    if 'author' in message and (message['author']['_account_id'] == jenkins_id or message['author']['_account_id'] == fuel_ci_id ) and re.search(CI_DONE_MESSAGE_REGEX, message['message']):
                        lags[revision]['end'] = gerritdate2date(message['date'])
                        logging.info('END   %s change %s ; revision %s ; message: %s' % (message['date'], change['_number'], revision, message['message'].replace('\n',' ')))
                    elif re.search(PATCHSET_UPLOAD_MESSAGE_REGEX, message['message']):
                        lags[revision]['start'] = gerritdate2date(message['date'])
                        logging.info('START %s change %s ; revision %s ; message: %s' % (message['date'], change['_number'], revision, message['message'].replace('\n',' ')))

            if 'lags' not in projects[project]:
                projects[project]['lags'] = []
            else:
                for lag in lags:
                    if 'start' in lags[lag] and 'end' in lags[lag]:
                        res = (lags[lag]['end'] - lags[lag]['start']).total_seconds()
                        projects[project]['lags'].append(res)
                        logging.info('LAG DATA change %s: %s ; res %s' % (change['_number'], lags[lag], res))
                        drshn_bfr_mrg[res] = (change['_number'], res)
    i+=1
    lastcount = len(data)
    try:
        morechanges = data[-1]['_more_changes']
        lastelement = data[-1]['_sortkey']
    except KeyError:
        morechanges = False

    logging.debug('lastcount: %s ; lastelement: %s ; i: %s' % (
        lastcount, lastelement, i))

total_commits = 0
max_lag = 0
min_lag = 0
avg_lag = 0
for project in projects.keys():
    if len(projects[project]['lags']) > 0:
        minv = int(min(projects[project]['lags']))
        maxv = int(max(projects[project]['lags']))
        avgv = int(reduce(lambda x, y: x + y, projects[project]['lags']) / len(projects[project]['lags']))
        del(projects[project]['lags'])
        projects[project]['lags'] = {
            'max': pretty_duration(maxv),
            'min': pretty_duration(minv),
            'avg': pretty_duration(avgv),
        }

        total_commits += projects[project]['commits']
        max_lag += maxv
        min_lag += minv
        avg_lag += avgv

print yaml.dump(projects, default_flow_style=False)

print """
Overall commits: %s
Max lag: %s
Min lag: %s
Avg lag: %s
""" % (
    total_commits,
    pretty_duration(max_lag),
    pretty_duration(min_lag),
    pretty_duration(avg_lag))

output = ([
    ('Period', (datetime.datetime.strftime((datetime.datetime.now() - datetime.timedelta(days=7)), '%Y-%m-%d'), datetime.datetime.strftime(datetime.datetime.now(), '%Y-%m-%d'))),
    ('Commits merged in stackforge repos', ("", total_commits)),
    ('Time elapsed', ("Average", "Max")),
    ('From patchset created to CI finished',(pretty_duration(avg_lag), pretty_duration(int(drshn_bfr_mrg[max(drshn_bfr_mrg.keys())][1])), drshn_bfr_mrg[max(drshn_bfr_mrg.keys())][0]))
])
print output
with open('gr_metrics.json', 'w') as outfile:
    json.dump(output, outfile)
