import sys
import gzip
import json
import re

from collections import defaultdict

import matplotlib.pyplot as plt
from matplotlib.backends.backend_pdf import PdfPages

class DistributionStats(object):
    def __init__(self):
        self._gettime = lambda: self._timestamp - self._timestamp_offset
        self._worker_activity = self.ResourceStateTimeseries('worker state', self._gettime)
        self._timestamp_offset = 0
        self._timestamp = None
        
    class ResourceStateTimeseries(object):
        def __init__(self, name, system_time):
            self._name = name
            self._system_time = system_time
            self.state_log = defaultdict(list)

        def update(self, resource, state):
            self.state_log[resource].append((self._system_time(), state))

    def _advance(self, timestamp):
        if self._timestamp is None:
            self._timestamp = timestamp
            self._timestamp_offset = timestamp
            # print "starting timestamp is ", timestamp
        else:
            # print "timestamp is now", timestamp
            if timestamp < self._timestamp:
                raise RuntimeError("Decreasing timestamp")
            else:
                self._timestamp = timestamp

    def add_event(self, e):
        self._advance(e['timestamp'])
        if e['status'] == 1:
            self._worker_activity.update(e['worker_id'], (e['task_id'], e['event_type'], 'start'))
        elif e['status'] == 2:
            self._worker_activity.update(e['worker_id'], (e['task_id'], e['event_type'], 'end'))


    def get_stats(self):
        stats = {}
        stats['worker_activity'] = self._worker_activity.state_log
        return stats

def plot_worker_activity(data, title, pdf):
    workers = sorted(data.keys())

    width = .8
    padding = .2

    baseline = padding / 2


    fig = plt.figure()
    ax = fig.add_subplot(111)

    active_ranges_benchmark = defaultdict(list)

    for worker in workers:
        last_started = {}
        for (timestamp, (task_id, event_type, status)) in data[worker]:
            if event_type.startswith('benchmark:'):
                # print data[worker]
                if status == 'start':
                    last_started[event_type] = timestamp
                elif status == 'end':
                    active_ranges_benchmark[event_type].append((last_started[event_type], timestamp - last_started[event_type]))
                    del last_started[event_type]
    if not active_ranges_benchmark['benchmark:measure']:
        print "no benchmark interval measurement found"
    plt.broken_barh(active_ranges_benchmark['benchmark:measure'], (0, len(workers)), color='#ffcce6')

    ignored_event_types = frozenset(['ray:get_task'])
    for worker in workers:
        last_started = {}
        active_ranges = defaultdict(list)
        for (timestamp, (task_id, event_type, status)) in data[worker]:
            if event_type in ignored_event_types:
                continue
            if status == 'start':
                last_started[event_type] = timestamp
            elif status == 'end':
                active_ranges[event_type].append((last_started[event_type], timestamp - last_started[event_type]))
                del last_started[event_type]
        plot_bars = [
            ('ray:task', 'gray'),
            ('ray:task:execute', '#33cc33'),
            ('ray:task:get_arguments', '#ff5252'),
            ('ray:task:store_outputs', '#ff7d52'),
            ('ray:put', '#9933ff'),
            ('ray:get', '#cc0099'),
            ('ray:wait', '#808080'),
            ('ray:wait_for_import_counter', '#000000'),
            ('ray:submit_task', '#00ffff'),
            ('ray:task:reinitialize_reusables', '#000000'),
            ('ray:acquire_lock', '#ff0000')]
        for event_type, color in plot_bars:
            plt.broken_barh(active_ranges[event_type], (baseline, width), color=color)
        baseline += width + padding

        plotted_keys = set([p[0] for p in plot_bars])
        remaining_keys = set(k for k in active_ranges.keys() if k.startswith('ray:')) - plotted_keys
        if remaining_keys:
            print "still have keys left", remaining_keys

    ax.set_ylabel('Worker ID')
    ax.set_yticks(list(0.5 + x for x in range(len(workers))))
    ax.set_yticklabels(map(lambda x: str(x)[:8], workers))
    ax.set_xlabel('Time [seconds]')

    ax.set_title(title)

    pdf.savefig(fig)
    plt.close(fig)

def get_title(filename):
    m = re.search('^(.*/)?(.*).json.gz$', filename)
    return m.group(2)

if __name__ == '__main__':
    if len(sys.argv) != 3:
        print "Usage: plot_worker_activity.py input_events.json.gz output.pdf"
        sys.exit(1)
    input_file = sys.argv[1]
    output_filename = sys.argv[2]
    with gzip.open(input_file) as f:
        all_events = json.load(f)
    ds = DistributionStats()
    for e in all_events:
        ds.add_event(e)
    stats = ds.get_stats()

    with PdfPages(output_filename) as pdf:
        plot_worker_activity(stats['worker_activity'], get_title(input_file), pdf)