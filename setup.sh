#!/bin/bash
sudo-g5k ipmitool user set name 6 ipmireader
sudo-g5k ipmitool user set password 6 ipmireader
sudo-g5k ipmitool user enable 6
sudo-g5k ipmitool channel setaccess 1 6 callin=on ipmi=on link=on privilege=4
sudo-g5k ipmitool user list 1
# To retrieve an ip:
IPMI_IP=$(sudo-g5k ipmitool lan print | grep "IP Address  " | cut -d: -f2 | tr -d [:blank:])
echo $IPMI_IP
