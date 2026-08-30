# model = RB941-2nD
# serial number = A1C609CFCB29
/interface bridge
add admin-mac=B8:69:F4:F3:81:82 auto-mac=no comment=defconf name=bridge
/interface wireless
set [ find default-name=wlan1 ] band=2ghz-b/g/n channel-width=20/40mhz-Ce \
    disabled=no distance=indoors frequency=auto mode=ap-bridge ssid=Orlan31 \
    wireless-protocol=802.11
/interface pppoe-client
add add-default-route=yes disabled=no interface=ether1 name=pppoe-out1 \
    password=fgjh use-peer-dns=yes user=610601
/interface l2tp-client
add connect-to=185.253.182.24 name=vpn password=qweqwe user=ddd
/interface list
add comment=defconf name=WAN
add comment=defconf name=LAN
/interface wireless security-profiles
set [ find default=yes ] authentication-types=wpa-psk,wpa2-psk mode=\
    dynamic-keys supplicant-identity=MikroTik wpa-pre-shared-key=QazXdr3579! \
    wpa2-pre-shared-key=QazXdr3579!
/ip pool
add name=dhcp ranges=192.168.142.50-192.168.142.100
/ip dhcp-server
add address-pool=dhcp disabled=no interface=bridge name=defconf
/interface sstp-client
add connect-to=185.253.182.24:943 disabled=no name=sstp_vpn password=\
    qweqwe profile=default-encryption user=ddd
/interface bridge port
add bridge=bridge comment=defconf interface=ether2
add bridge=bridge comment=defconf interface=ether3
add bridge=bridge comment=defconf interface=ether4
add bridge=bridge comment=defconf interface=wlan1
/ip neighbor discovery-settings
set discover-interface-list=LAN
/interface list member
add comment=defconf interface=bridge list=LAN
add comment=defconf interface=ether1 list=WAN
add interface=pppoe-out1 list=WAN
/ip address
add address=192.168.142.1/24 comment=defconf interface=ether2 network=\
    192.168.142.0
/ip dhcp-client
add comment=defconf dhcp-options=hostname,clientid interface=ether1
/ip dhcp-server network
add address=192.168.142.0/24 comment=defconf dns-server=192.168.142.1 gateway=\
    192.168.142.1 netmask=24
/ip dns
set allow-remote-requests=yes
/ip dns static
add address=192.168.142.1 name=router.lan
/ip firewall filter
add action=accept chain=input comment=\
    "defconf: accept established,related,untracked" connection-state=\
    established,related,untracked
add action=drop chain=input comment="defconf: drop invalid" connection-state=\
    invalid disabled=yes
add action=accept chain=input comment="defconf: accept ICMP" protocol=icmp
add action=drop chain=input comment="defconf: drop all not coming from LAN" \
    disabled=yes in-interface-list=!LAN
add action=accept chain=forward comment="defconf: accept in ipsec policy" \
    ipsec-policy=in,ipsec
add action=accept chain=forward comment="defconf: accept out ipsec policy" \
    ipsec-policy=out,ipsec
add action=fasttrack-connection chain=forward comment="defconf: fasttrack" \
    connection-state=established,related
add action=accept chain=forward comment=\
    "defconf: accept established,related, untracked" connection-state=\
    established,related,untracked
add action=drop chain=forward comment="defconf: drop invalid" connection-state=\
    invalid disabled=yes
add action=drop chain=forward comment=\
    "defconf:  drop all from WAN not DSTNATed" connection-nat-state=!dstnat \
    connection-state=new disabled=yes in-interface-list=WAN
/ip firewall nat
add action=masquerade chain=srcnat comment="defconf: masquerade" ipsec-policy=\
    out,none out-interface-list=WAN
/ip route
add distance=1 dst-address=172.16.0.0/24 gateway=sstp_vpn
add distance=1 dst-address=192.168.101.0/24 gateway=sstp_vpn
add distance=1 dst-address=192.168.105.0/24 gateway=sstp_vpn
add distance=1 dst-address=192.168.140.0/24 gateway=sstp_vpn
add distance=1 dst-address=192.168.141.0/24 gateway=sstp_vpn
add distance=1 dst-address=192.168.254.0/24 gateway=sstp_vpn
/system clock
set time-zone-name=Europe/Moscow
/system routerboard settings
set silent-boot=no
/tool mac-server
set allowed-interface-list=LAN
/tool mac-server mac-winbox
set allowed-interface-list=LAN
