#!/usr/bin/env python

import datetime
import re
import simplejson
import urllib
import urllib2
import yaml

query = 'project:^stackforge/fuel-.* status:merged'

url = 'https://review.openstack.org/changes/?q=%s&n=500&o=MESSAGES' % urllib.quote(query)

CI_USER_REGEX = re.compile('(Jenkins|Fuel\sCI)')
CI_DONE_MESSAGE_REGEX = re.compile('^Patch\sSet\s(\d+):\s(-)?Verified(\+)?')
PATCHSET_UPLOAD_MESSAGE_REGEX = re.compile('^Uploaded patch set (\d+).$')

changes = []
i = 0
lastcount = 1
morechanges = True
lastelement = None

now = datetime.datetime.now()

projects = {}

def gerritdate2date(date):
    return datetime.datetime.strptime(date[:-3], '%Y-%m-%d %H:%M:%S.%f')

while morechanges:
    try:
        ua = urllib2.urlopen(url+'&S=%s' % int(i*100))
    except urllib2.HTTPError as e:
        if e.msg == 'Bad Request':
            ua = urllib2.urlopen(url+'&N=%s' % lastelement if lastelement else url)
        else:
            raise
    data = simplejson.loads(ua.read()[5:])
    for change in data:
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

                    if 'author' in message and re.search(CI_USER_REGEX, message['author']['name']) and re.search(CI_DONE_MESSAGE_REGEX, message['message']):
                        lags[revision]['end'] = gerritdate2date(message['date'])
                    elif re.search(PATCHSET_UPLOAD_MESSAGE_REGEX, message['message']):
                        lags[revision]['start'] = gerritdate2date(message['date'])

            if 'lags' not in projects[project]:
                projects[project]['lags'] = []
            else:
                for lag in lags:
                    if 'start' in lags[lag] and 'end' in lags[lag]:
                        res = (lags[lag]['end'] - lags[lag]['start']).total_seconds()
                        projects[project]['lags'].append(res)

    i+=1
    lastcount = len(data)
    try:
        morechanges = data[-1]['_more_changes']
        lastelement = data[-1]['_sortkey']
    except KeyError:
        morechanges = False

    print 'DEBUG: lastcount: %s ; lastelement: %s ; i: %s' % (
        lastcount, lastelement, i)

for project in projects.keys():
    if len(projects[project]['lags']) > 0:
        minv = int(min(projects[project]['lags']))
        maxv = int(max(projects[project]['lags']))
        avgv = int(reduce(lambda x, y: x + y, projects[project]['lags']) / len(projects[project]['lags']))
        del(projects[project]['lags'])
        projects[project]['lags'] = {
            'max': maxv,
            'min': minv,
            'avg': avgv,
        }

print yaml.dump(projects, default_flow_style=False)
