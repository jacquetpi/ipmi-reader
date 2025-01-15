import sys, getopt, re, time
import subprocess as sp
from os import listdir
from os.path import isfile, join, exists
import pyipmi
import pyipmi.interfaces

SMI_QUERY      = ['index','gpu_name','utilization.gpu','temperature.gpu','pstate','clocks.current.graphics','clocks.current.sm','clocks.current.memory','clocks.current.video','utilization.memory','memory.used','memory.free','memory.total','power.draw','power.max_limit','fan.speed']
SMI_QUERY_FLAT = ','.join(SMI_QUERY)
OUTPUT_FILE    = 'consumption.csv'
OUTPUT_HEADER  = 'timestamp,' + SMI_QUERY_FLAT
OUTPUT_NL      = '\n'
DELAY_S        = 5
PRECISION      = 2
LIVE_DISPLAY   = False

def print_usage():
    print('python3 ipmi-reader.py [--help] [--live] [--output=' + OUTPUT_FILE + '] [--delay=' + str(DELAY_S) + ' (in sec)] [--precision=' + str(PRECISION) + ' (number of decimal)]')

###########################################
# Read IPMI
###########################################

print("hi")

interface = pyipmi.interfaces.create_interface(interface='rmcp',
                                             slave_address=0x81,
                                             host_target_address=0x20,
                                             keep_alive_interval=1)
ipmi = pyipmi.create_connection(interface)
ipmi.session.set_session_type_rmcp(host='10.0.114.199', port=623)
ipmi.session.set_auth_type_user(username='admin', password='admin')

ipmi.target = pyipmi.Target(ipmb_address=0x20)

ipmi.session.establish()
device_id = ipmi.get_device_id()

# Below code used only to print out the device ID information
print('''
Device ID:          %(device_id)s
Device Revision:    %(revision)s
Firmware Revision:  %(fw_revision)s
IPMI Version:       %(ipmi_version)s
Manufacturer ID:    %(manufacturer_id)d (0x%(manufacturer_id)04x)
Product ID:         %(product_id)d (0x%(product_id)04x)
Device Available:   %(available)d
Provides SDRs:      %(provides_sdrs)d
Additional Device Support:
'''[1:-1] % device_id.__dict__)
functions = (
        ('SENSOR', 'Sensor Device'),
        ('SDR_REPOSITORY', 'SDR Repository Device'),
        ('SEL', 'SEL Device'),
        ('FRU_INVENTORY', 'FRU Inventory Device'),
        ('IPMB_EVENT_RECEIVER', 'IPMB Event Receiver'),
        ('IPMB_EVENT_GENERATOR', 'IPMB Event Generator'),
        ('BRIDGE', 'Bridge'),
        ('CHASSIS', 'Chassis Device')
)
for n, s in functions:
    if device_id.supports_function(n):
        print('  %s' % s)
if device_id.aux is not None:
    print('Aux Firmware Rev Info:  [%s]' % (
            ' '.join('0x%02x' % d for d in device_id.aux)))


sys.exit(0)

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
    results = {}
    for position, query in enumerate(SMI_QUERY):
        if 'N/A' in data_single_gc[position]:
            value = 'NA'
        elif '[' in header[position]: # if a unit is written, like [MiB], we have to strip it from value
            value = float(re.sub(r"[^\d\.]", "", data_single_gc[position]))
        else:
            value = data_single_gc[position].strip()
        results[query] = value
    return results

def query_smi():
    COMMAND = "nvidia-smi --query-gpu=" + SMI_QUERY_FLAT + " --format=csv"
    smi_data = __generic_smi(COMMAND)
    header = smi_data[0]
    data   = smi_data[1:]
    return [__convert_cg_to_dict(header, data_single_gc) for data_single_gc in data]


###########################################
# Main loop, read periodically
###########################################
def loop_read():
    launch_at = time.time_ns()
    while True:
        time_begin = time.time_ns()

        smi_measures = query_smi()
        output(smi_measures=smi_measures, time_since_launch=int((time_begin-launch_at)/(10**9)))

        time_to_sleep = (DELAY_S*10**9) - (time.time_ns() - time_begin)
        if time_to_sleep>0: time.sleep(time_to_sleep/10**9)
        else: print('Warning: overlap iteration', -(time_to_sleep/10**9), 's')

def output(smi_measures : list, time_since_launch : int):

    if LIVE_DISPLAY and smi_measures:
        total_draw  = 0
        total_limit = 0
        for gc_as_dict in smi_measures:
            print(gc_as_dict['index'] + ':', str(gc_as_dict['utilization.gpu']) + '%', str(gc_as_dict['power.draw']) + '/' + str(gc_as_dict['power.max_limit']) + ' W')
            total_draw += gc_as_dict['power.draw']
            total_limit+= gc_as_dict['power.max_limit']
        print('Total:', str(round(total_draw,PRECISION)) + '/' + str(round(total_limit,PRECISION)) + ' W')
        print('---')

    # Dump reading
    with open(OUTPUT_FILE, 'a') as f:
        for gc_as_dict in smi_measures:
            values = ','.join([str(gc_as_dict[key]) for key in SMI_QUERY]) # to have a fixed order
            f.write(str(time_since_launch) + ',' + values + OUTPUT_NL)
###########################################
# Entrypoint, manage arguments
###########################################
if __name__ == '__main__':

    short_options = 'hlecdv:o:p:'
    long_options = ['help', 'live', 'explicit', 'cache', 'vm=', 'delay=', 'output=', 'precision=']

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
        elif current_argument in('-o', '--output'):
            OUTPUT_FILE= current_value
        elif current_argument in('-p', '--precision'):
            PRECISION= int(current_value)
        elif current_argument in('-d', '--delay'):
            DELAY_S= float(current_value)

    try:
        # Find domains
        print('>SMI GC found:')
        for gc in discover_smi(): print(gc[0])
        # Init output
        with open(OUTPUT_FILE, 'w') as f: f.write(OUTPUT_HEADER + OUTPUT_NL)
        # Launch
        loop_read()
    except KeyboardInterrupt:
        print('Program interrupted')
        sys.exit(0)