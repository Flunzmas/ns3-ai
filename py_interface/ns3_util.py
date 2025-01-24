# -*- Mode: python; py-indent-offset: 4; indent-tabs-mode: nil; coding: utf-8; -*-
# Copyright (c) 2019 Huazhong University of Science and Technology, Dian Group
#
# This program is free software; you can redistribute it and/or modify
# it under the terms of the GNU General Public License version 2 as
# published by the Free Software Foundation;
#
# This program is distributed in the hope that it will be useful,
# but WITHOUT ANY WARRANTY; without even the implied warranty of
# MERCHANTABILITY or FITNESS FOR A PARTICULAR PURPOSE.  See the
# GNU General Public License for more details.
#
# You should have received a copy of the GNU General Public License
# along with this program; if not, write to the Free Software
# Foundation, Inc., 59 Temple Place, Suite 330, Boston, MA  02111-1307  USA
#
# Author: Pengyu Liu <eic_lpy@hust.edu.cn>
#         Hao Yin <haoyin@uw.edu>

import os
import signal
import subprocess
import time
from copy import copy
from pathlib import Path

import psutil
import shutil

try:
    from collections.abc import Iterable
except:
    pass
cpu_num = psutil.cpu_count()
try:
    devnull = subprocess.DEVNULL
except:
    devnull = open(os.devnull, 'w')
RESERVE_CPU = 4


class cder:
    '''
    Example:
        with cder('/path/to/use/'):
            pass
    '''

    def __init__(self, path):
        self.dir = path

    def __enter__(self):
        self.cwd = os.getcwd()
        os.chdir(self.dir)

    def __exit__(self, Type, value, traceback):
        os.chdir(self.cwd)


def get_free_cpu(perc=20):
    return sorted(filter(lambda x: x[1] < perc, zip(range(cpu_num), psutil.cpu_percent(interval=1, percpu=True))), key=lambda x: x[1])


def kill_proc_tree(p, timeout=None, on_terminate=None):
    if isinstance(p, int):
        p = psutil.Process(p)
    elif not isinstance(p, psutil.Process):
        p = psutil.Process(p.pid)
    ch = [p]+p.children(recursive=True)
    for c in ch:
        try:
            if "perf" in c.name():
                try:
                    print(f"Terminating `perf` process: PID={c.pid}")
                    c.send_signal(signal.SIGTERM)  # Graceful termination
                    c.wait(timeout=10)  # Wait for graceful termination
                    print(f"`perf` process (PID={c.pid}) terminated successfully.")
                except psutil.TimeoutExpired:
                    print(f"`perf` process (PID={c.pid}) did not terminate with SIGTERM.")
                    print(f"Sending SIGKILL to `perf` process: PID={c.pid}")
                    try:
                        c.kill()  # Forcefully terminate
                    except psutil.NoSuchProcess:
                        print(f"`perf` process (PID={c.pid}) no longer exists.")
                        continue
            else:
                c.kill()
        except psutil.NoSuchProcess:
            continue
    succ, err = psutil.wait_procs(ch, timeout=timeout,
                                  callback=on_terminate)
    return (succ, err)


def get_settings(setting_map):
    if not setting_map.keys():
        return [('', '')], ''
    key, value = setting_map.popitem()
    ret, file_name_format = get_settings(setting_map)
    file_name_format = file_name_format+'_'+key
    if not isinstance(value, Iterable):
        value = [value]
    newret = []
    for v in value:
        for precmd, prefn in ret:
            newret.append((precmd+' --{}={}'.format(key, v),
                           (prefn+'_{}'.format(v)).strip('_')))
    return newret, file_name_format.strip('_')


def get_setting(setting_map):
    ret = ''
    for key, value in setting_map.items():
        ret += ' --{}={}'.format(key, value)
    return ret


def build_ns3(path):
    print('=== NS3AI: BUILDING NS3 ===')
    proc = subprocess.Popen('./ns3 build', shell=True, stdout=subprocess.PIPE,
                            stderr=devnull, universal_newlines=True, cwd=path)
    proc.wait()

    ok = proc.returncode == 0
    return ok


def check_program_installed(program_name: str) -> str:
    program_path = shutil.which(program_name)
    if program_path is None:
        print("Executable '{program}' was not found".format(program=program_name.capitalize()))
        exit(-1)
    return program_path


def run_single_ns3(path, pname, setting=None, env=None, show_output=False, profile_ns3=False, build=True):
    if build and not build_ns3(path):
        raise RuntimeError("run_single_ns3(): requested to build ns3, but build failed!")
    if env:
        env.update(os.environ)
    env['LD_LIBRARY_PATH'] = os.path.abspath(os.path.join(path, 'build', 'lib'))
    exec_path = os.path.join(path, 'build', 'scratch')
    # TODO hotfix for cmake-built ns3: executable seems to be placed differently, so take 1st file from exec_path
    exec_name = [f for f in os.listdir(os.path.join(exec_path, pname)) if f.startswith("ns")][0]
    cmd: str = f'./{pname}/{exec_name}'
    if setting:
        cmd += get_setting(setting)
    if profile_ns3:
        perf_cmd = check_program_installed("perf")
        base_out_dir = str(setting["outDir"]) if (setting is not None and "outDir" in setting) else "."
        perf_out_fp = Path(base_out_dir) / "perf.data"
        perf_options = f"record -o {str(perf_out_fp.resolve())} -g -e cpu-cycles,context-switches"
        cmd = f"{perf_cmd} {perf_options} bash -c \'{cmd}\'"  # TODO (later): add option -a for run_bulk_ns3()
    if show_output:
        proc = subprocess.Popen(
            cmd, shell=True, universal_newlines=True, cwd=exec_path, env=env)
    else:
        proc = subprocess.Popen(cmd, shell=True, stdout=subprocess.PIPE,
                                stderr=devnull, universal_newlines=True, cwd=exec_path, env=env)
    return proc


def run_bulk_ns3(path, pname, commons, settings, debug=False):
    common_setting_param = get_setting(copy(commons))
    params, fname_format = [], []
    for smap in settings:
        p, f = get_settings(copy(smap))
        params.extend(p)
        fname_format.append(f)
    for args, fn in params:
        cpus = get_free_cpu()
        while len(cpus) < RESERVE_CPU:
            time.sleep(5)
        cmd = 'taskset -c {} nohup ./waf --run {}{}{} > {}&'.format(
            cpus[0][0], pname, common_setting_param, args, fn)
        os.system(cmd)


__all__ = ['cpu_num', 'cder', 'get_free_cpu', 'kill_proc_tree',
           'get_settings', 'get_setting', 'build_ns3', 'run_single_ns3']
