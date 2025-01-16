import sys, getopt, re, time
import subprocess as sp
from os import listdir
from os.path import isfile, join, exists
import pyipmi
import pyipmi.interfaces

SMI_QUERY       = ['index','utilization.gpu','temperature.gpu','pstate','clocks.current.graphics','clocks.current.sm','clocks.current.memory','clocks.current.video','utilization.memory','memory.used','memory.free','memory.total','power.draw','power.max_limit','fan.speed']
SMI_QUERY_FLAT  = ','.join(SMI_QUERY)
OUTPUT_FILE     = 'measures.csv'
OUTPUT_HEADER   = 'timestamp,domain,metric,measure'
OUTPUT_NL       = '\n'
DELAY_S         = 5
PRECISION       = 2
LIVE_DISPLAY    = False
IPMI_URL        = "172.17.53.1"
IPMI_PORT       = 623
IPMI_USER       = "ipmireader"
IPMI_PASSWORD   = "ipmireader"
DCGM_EXPORT_URL = "http://localhost:9400/metrics"
SUDO_COMMAND    = "sudo-g5k" # Adapted for Grid5000

def print_usage():
    print('python3 ipmi-reader.py [--help] [--live] [--output=' + OUTPUT_FILE + '] [--delay=' + str(DELAY_S) + ' (in sec)] [--precision=' + str(PRECISION) + ' (number of decimal)]')

###########################################
# Read IPMI
###########################################

# I don't use the IPMI lan interface due to inconsistency between g5k hosts (see fallback)
def connect_ipmi_session():
    interface = pyipmi.interfaces.create_interface('ipmitool',  interface_type='lan')
    ipmi = pyipmi.create_connection(interface)

    ipmi.session.set_session_type_rmcp(host=IPMI_URL, port=IPMI_PORT)
    ipmi.session.set_auth_type_user(username=IPMI_USER, password=IPMI_PASSWORD)
    #ipmi.session.set_priv_level("ADMINISTRATOR")

    ipmi.session.establish()

    return ipmi

def disconnect_ipmi_session(ipmi):
    ipmi.session.close()

def discover_ipmi_addresses():
    cmd = SUDO_COMMAND + " ipmitool sdr type temperature"
    result = sp.run(cmd, shell=True, capture_output=True, text=True)

    # Check for errors
    if result.returncode != 0:
        print("Command failed:", result.stderr)
        exit(1)

    # Extract label and address using regex
    output = result.stdout.strip().splitlines()
    sensors_dict = {}
    gpu_found = 0
    for line in output:
        if 'Disabled' in line: continue
        match = re.match(r'(\S.+?)\s+\| ([0-9A-Fa-f]+h)', line)
        if match:
            label, address = match.groups()
            label = label.strip()

            # Check label consistency and unicity
            domain = 'global'
            if 'GPU' in label:
                domain = 'GPU' + str(gpu_found)
                gpu_found+=1

            uniqueness_count = 0
            while label in sensors_dict.keys():
                uniqueness_count+=1
                if '(' in label and ')' in label:
                    label = re.sub('(.*?)', '', label)
                label+='(' + str(uniqueness_count) +  ')'

            sensors_dict[address.strip()] = (domain.strip(), label.strip())

    return sensors_dict

def query_ipmi_metrics_from_fallback(sensors_dict):
    cmd = SUDO_COMMAND + " ipmitool sdr type temperature"
    result = sp.run(cmd, shell=True, capture_output=True, text=True)

    # Check for errors
    if result.returncode != 0:
        print("Command failed:", result.stderr)
        exit(1)

    ipmi_measures = {}
    for line in result.stdout.strip().splitlines():
        if 'Disabled' in line: continue
        match = re.match(r"(.+?)\s+\|\s+([0-9A-Fa-f]{2}h)\s+\|\s+\w+\s+\|\s+[\d.]+\s+\|\s+(.+)", line)
        if match:
            label = match.group(1).strip()
            address = match.group(2).strip()
            value = match.group(3).strip()

            (domain, label) = sensors_dict[address]
            if domain not in ipmi_measures:
                ipmi_measures[domain] = {}
            ipmi_measures[domain][label]=value

    print(ipmi_measures)
    return ipmi_measures

def query_ipmi_metrics_from_lan(ipmi, sensors_dict):
    ipmi_measures = {}
    for sensor_address, (domain, sensor_label) in sensors_dict.items():
        reading, states = ipmi.get_sensor_reading(sensor_number='0x'+str(sensor_address))
        if domain not in ipmi_measures:
            ipmi_measures[domain] = {}
        ipmi_measures[domain][sensor_label]=reading
    return ipmi_measures

###########################################
# Read DCGM exporter
###########################################

def query_dcgm_metrics():
    try:
        # Run the curl command and capture the output
        cmd = "curl -s " + DCGM_EXPORT_URL
        result = sp.run(cmd, shell=True, text=True, capture_output=True, check=True)
        output = result.stdout

        dcgm_measures = {}
        for line in output.splitlines():
            # Skip comments and empty lines
            if line.startswith('#') or not line.strip():
                continue

            # Match metric name, labels, and value
            match = re.match(r'^([\w:]+)(\{.*\})?\s+([\d.]+)', line)
            if match:
                metric_name = match.group(1)
                labels = match.group(2)  # e.g., {gpu="0"}
                value = match.group(3)

                # Parse labels if present
                label_dict = {}
                if labels: # Remove the surrounding braces and split into key-value pairs
                    label_pairs = labels.strip('{}').split(',')
                    for pair in label_pairs:
                        key, val = pair.split('=')
                        label_dict[key.strip()] = val.strip('"')

                if label_dict:
                    domain = 'GPU' + str(label_dict["gpu"])
                    if domain not in dcgm_measures:
                        dcgm_measures[domain] = {}
                    try:
                        dcgm_measures[domain][metric_name] = float(value)
                    except ValueError:
                        dcgm_measures[domain][metric_name] = value  # Keep as string if not a float

        return dcgm_measures
    except sp.CalledProcessError as e:
        print(f"DCGM parsing failed with error: {e.stderr}")
        return {}

###########################################
# Read NVIDIA SMI
###########################################
##########
# nvidia-smi -L
# nvidia-smi --help-query-gpu

#"utilization.gpu"
#Percent of time over the past sample period during which one or more kernels was executing on the GPU.
#The sample period may be between 1 second and 1/6 second depending on the product.

#"utilization.memory"
#Percent of time over the past sample period during which global (device) memory was being read or written.
#The sample period may be between 1 second and 1/6 second depending on the product.
##########

def __generic_smi(command : str):
    try:
        csv_like_data = sp.check_output(command.split(),stderr=sp.STDOUT).decode('ascii').split('\n')
        smi_data = [cg_data.split(',') for cg_data in csv_like_data[:-1]] # end with ''
    except sp.CalledProcessError as e:
        raise RuntimeError("command '{}' return with error (code {}): {}".format(e.cmd, e.returncode, e.output))
    return smi_data

def discover_smi():
    COMMAND = "nvidia-smi -L"
    return __generic_smi(COMMAND)

def __convert_cg_to_dict(header : list, data_single_gc : list):
    gpu_index = None
    gpu_data = {}
    for position, query in enumerate(SMI_QUERY):
        if 'N/A' in data_single_gc[position]:
            value = 'NA'
        elif '[' in header[position]: # if a unit is written, like [MiB], we have to strip it from value
            value = float(re.sub(r"[^\d\.]", "", data_single_gc[position]))
        else:
            value = data_single_gc[position].strip()
        if query == 'index':
            gpu_index = 'GPU' + str(value)
            continue
        gpu_data[query] = value
    return gpu_index, gpu_data

def query_smi():
    COMMAND = "nvidia-smi --query-gpu=" + SMI_QUERY_FLAT + " --format=csv"
    smi_data = __generic_smi(COMMAND)
    header = smi_data[0]
    data   = smi_data[1:]
    smi_measures = {}
    for data_single_gc in data:
        gpu_index, gpu_data = __convert_cg_to_dict(header, data_single_gc)
        smi_measures[gpu_index] = gpu_data
    return smi_measures

###########################################
# Main loop, read periodically
###########################################
def loop_read(ipmi, ipmi_addresses):

    launch_at = time.time_ns()
    while True:
        time_begin = time.time_ns()

        ipmi_measures = query_ipmi_metrics_from_fallback(ipmi_addresses)
        smi_measures  = query_smi()
        dcgm_measures = query_dcgm_metrics()

        output(ipmi_measures=ipmi_measures, dcgm_measures=dcgm_measures, smi_measures=smi_measures, time_since_launch=int((time_begin-launch_at)/(10**9)))

        time_to_sleep = (DELAY_S*10**9) - (time.time_ns() - time_begin)
        if time_to_sleep>0: time.sleep(time_to_sleep/10**9)
        else: print('Warning: overlap iteration', -(time_to_sleep/10**9), 's')

def output(ipmi_measures : dict, dcgm_measures : dict, smi_measures : dict, time_since_launch : int):

    if LIVE_DISPLAY and smi_measures:
        total_draw  = 0
        total_limit = 0
        for gpu_index, gpu_dict in smi_measures.items():
            print(gpu_index + ':', str(gpu_dict['utilization.gpu']) + '%', str(gpu_dict['power.draw']) + '/' + str(gpu_dict['power.max_limit']) + ' W')
            total_draw += gpu_dict['power.draw']
            total_limit+= gpu_dict['power.max_limit']
        print('Total:', str(round(total_draw,PRECISION)) + '/' + str(round(total_limit,PRECISION)) + ' W')
        print('---')

    # Dump reading
    with open(OUTPUT_FILE, 'a') as f:
        # IPMI
        for domain, domain_dict in ipmi_measures.items():
            for key, value in domain_dict.items():
                f.write(str(time_since_launch) + ',' + domain + ',ipmi_' + key + ',' + str(value) + OUTPUT_NL)
        # DCGM
        for domain, domain_dict in dcgm_measures.items():
            for key, value in domain_dict.items():
                f.write(str(time_since_launch) + ',' + domain + ',dcgm_' + key + ',' + str(value) + OUTPUT_NL)
        # SMI
        for gpu_index, gpu_dict in smi_measures.items():
            for key, value in gpu_dict.items():
                f.write(str(time_since_launch) + ',' + gpu_index + ',smi_' + key + ',' + str(value) + OUTPUT_NL)

###########################################
# Entrypoint, manage arguments
###########################################
if __name__ == '__main__':

    short_options = 'hld:o:p:u:'
    long_options = ['help', 'live', 'delay=', 'output=', 'precision=', 'url=']

    try:
        arguments, values = getopt.getopt(sys.argv[1:], short_options, long_options)
    except getopt.error as err:
        print(str(err))
        print_usage()
    for current_argument, current_value in arguments:
        if current_argument in ('-h', '--help'):
            print_usage()
            sys.exit(0)
        elif current_argument in('-l', '--live'):
            LIVE_DISPLAY= True
        elif current_argument in('-d', '--delay'):
            DELAY_S= float(current_value)
        elif current_argument in('-o', '--output'):
            OUTPUT_FILE= current_value
        elif current_argument in('-p', '--precision'):
            PRECISION= int(current_value)
        elif current_argument in('-u', '--url'):
            IPMI_URL= current_value
    try:
        # Find domains
        print('>SMI GC found:')
        for gc in discover_smi(): print(gc[0])
        # Connect IPMI session
        ipmi = None #connect_ipmi_session()
        sensors_dict = discover_ipmi_addresses()
        print('IPMI sensors:')
        for label, address in sensors_dict.items():
           print(f"{label}, Domain & Address: {address}")

        # Init output
        with open(OUTPUT_FILE, 'w') as f: f.write(OUTPUT_HEADER + OUTPUT_NL)

        # Launch
        loop_read(ipmi,sensors_dict)
    except KeyboardInterrupt:
        print('Program interrupted')
        if ipmi is not None: disconnect_ipmi_session(ipmi)
        sys.exit(0)
