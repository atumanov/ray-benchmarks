import argparse
import base64
import json
import re
import os
from subprocess import Popen, PIPE

import event_stats

class ClusterControl(object):
    def __init__(self, master_node, worker_nodes):
        self.master_node = master_node
        self.worker_nodes = worker_nodes
        self.all_nodes = [master_node] + worker_nodes
        self.username = 'ubuntu'

        self._reset_config()

    def _reset_config(self):
        self.num_nodes_started = None
        self.num_workers_started = None
        self.redis_address = None

    def initialize(self, num_nodes, num_workers_per_node):
        self._stop_ray(self.all_nodes)
        redis_address = self._start_ray_master_node(master_ip, num_workers_per_node)
        if num_nodes > 1:
            self._start_ray_worker_node(self.worker_nodes[:(num_nodes-1)], num_workers_per_node, redis_address)
        self.num_nodes_started = num_nodes
        self.num_workers_started = num_nodes * num_workers_per_node
        self.redis_address = redis_address
        return redis_address

    def run_benchmark(self, benchmark_script, config):
        # TODO put benchmark script in the right place on the destination host
        self._scp_upload(self.master_node, [ "event_stats.py", "lear.txt", "benchmarkstats.py", benchmark_script])

        benchmark_command = "export PATH=/home/ubuntu/anaconda2/bin/:$PATH && source activate raydev && export RAY_REDIS_ADDRESS={} && export RAY_NUM_WORKERS={} && python {}".format(self.redis_address, self.num_workers_started, benchmark_script)
        self._pssh_command(self.master_node, benchmark_command)

        config_str = base64.b64encode(json.dumps(config))
        benchmark_stats_command = "export PATH=/home/ubuntu/anaconda2/bin/:$PATH && source activate raydev && export RAY_REDIS_ADDRESS={} && python benchmarkstats.py --config=\"{}\"".format(self.redis_address, config_str)
        self._pssh_command(self.master_node, benchmark_stats_command)

    def download_stats(self, filename):
        self._scp_download(self.master_node, "benchmark_log.json.gz", filename)

    def _scp_upload(self, host, src, dst=""):
        if not isinstance(src, list):
            src = [src]
        args = ["scp"] + src + ["{}@{}:{}".format(self.username, host, dst)]
        proc = Popen(args, stdin=PIPE, stdout=PIPE, stderr=PIPE)
        (stdout, stderr) = proc.communicate()
        print "STDOUT"
        print stdout
        print "STDERR"
        print stderr

    def _scp_download(self, host, src, dst):
        args = ["scp", "{}@{}:{}".format(self.username, host, src), dst]
        proc = Popen(args, stdin=PIPE, stdout=PIPE, stderr=PIPE)
        (stdout, stderr) = proc.communicate()
        print "STDOUT"
        print stdout
        print "STDERR"
        print stderr

    def _pssh_command(self, hosts, command):
        if isinstance(hosts, list):
            host_args = []
            for host in hosts:
                host_args += ['--host', host]
        else:
                host_args = ['--host', hosts]
        args = ['pssh', '-l', self.username] + host_args + ['-t', '60', '-I', '-P']
        print hosts, ":", command
        proc = Popen(args, stdin=PIPE, stdout=PIPE, stderr=PIPE)
        (stdout, stderr) = proc.communicate(input=command)
        print "STDOUT"
        print stdout
        print "STDERR"
        print stderr
        return stdout, stderr

    def _stop_ray(self, hosts):
        print "stop ray on host", hosts
        self._reset_config()
        self._pssh_command(hosts, 'ray/scripts/stop_ray.sh')

    def _start_ray_master_node(self, host, num_workers):
        print "starting master on {}".format(host)
        script = 'export PATH=/home/ubuntu/anaconda2/bin/:$PATH && source activate raydev && rm -f dump.rdb ray-benchmarks/dump.rdb benchmark_log.json.gz && ray/scripts/start_ray.sh --head --num-workers {}'.format(num_workers)
        stdout, stderr = self._pssh_command(host, script)
        m = re.search("([0-9\.]+:[0-9]+)'", stdout)
        redis_address = m.group(1)
        self.redis_address = redis_address
        return redis_address

    def _start_ray_worker_node(self, hosts, num_workers, redis_address):
        print "starting workers on {}".format(hosts)
        script = 'export PATH=/home/ubuntu/anaconda2/bin/:$PATH && source activate raydev && ray/scripts/start_ray.sh --num-workers {} --redis-address {}'.format(num_workers, redis_address)
        stdout, stderr = self._pssh_command(hosts, script)


def get_all_ips():
    with open("host_ips.txt") as f:
        return list([line.strip() for line in f.readlines()])

def get_ips(num_nodes=None):
    ips = get_all_ips()
    master_ip = ips[0]
    if num_nodes is not None:
        if len(all_ips) < num_nodes:
            raise RuntimeError("not enough nodes available")
        other_ips = ips[1:num_nodes]
    else:
        other_ips = ips[1:]
    return master_ip, other_ips

if __name__ == "__main__":
    parser = argparse.ArgumentParser(description="Benchmark Ray workloads across a range of cluster sizes")
    parser.add_argument("--workload", required=True, help="benchmark workload script")
    parser.add_argument("--output", required=True, help="output directory")
    parser.add_argument("--sweep-workers-arithmetic", help="sweep arithmetic: start:end:step")
    parser.add_argument("--workers-per-node", type=int, default=4, help="number of workers per node")
    # parser.add_argument("--local", help="run locally")
    args = parser.parse_args()

    # create the output directory
    output_dir = args.output
    if not os.path.exists(output_dir):
        os.makedirs(output_dir)

    if args.workload.endswith(".py"):
        workload_name = args.workload[:-3]
    else:
        workload_name = args.workload

    if args.sweep_workers_arithmetic:
        m = re.search("^([0-9]+):([0-9]+):([0-9]+)$", args.sweep_workers_arithmetic)
        sweep_start = int(m.group(1))
        sweep_end = int(m.group(2))
        sweep_step = int(m.group(3))
    else:
        raise RuntimeError("sweep not found")

    (master_ip, other_ips) = get_ips()
    print master_ip, other_ips
    cc = ClusterControl(master_ip, other_ips)
    num_workers_per_node = args.workers_per_node
    for num_nodes in range(sweep_start, sweep_end + 1, sweep_step):
        config_info = {
            "num_nodes" : num_nodes,
            "num_workers" : num_nodes * num_workers_per_node,
            "workload" : workload_name }
        cc.initialize(num_nodes, num_workers_per_node)
        cc.run_benchmark(args.workload, config_info)
        cc.download_stats("{}/{}_{}_{}.json.gz".format(output_dir, workload_name, num_nodes, num_workers_per_node))
