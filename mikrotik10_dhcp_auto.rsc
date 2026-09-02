/interface bridge
add admin-mac=B8:69:F4:EF:36:2C auto-mac=no comment=defconf name=bridge
/interface wireless
set [ find default-name=wlan1 ] band=2ghz-b/g/n channel-width=20/40mhz-Ce \
    disabled=no distance=indoors frequency=auto mode=ap-bridge ssid=Orlan10 \
    wireless-protocol=802.11
/interface l2tp-client
add connect-to=157.22.205.210 disabled=no name=vpn password=Hager2213@ user=\
    vpn10
/interface list
add comment=defconf name=WAN
add comment=defconf name=LAN
/interface wireless security-profiles
set [ find default=yes ] authentication-types=wpa-psk,wpa2-psk mode=\
    dynamic-keys supplicant-identity=MikroTik wpa-pre-shared-key=QazXdr3579! \
    wpa2-pre-shared-key=QazXdr3579!
/ip pool
add name=dhcp ranges=192.168.10.50-192.168.10.100
/ip dhcp-server
add address-pool=dhcp disabled=no interface=bridge name=defconf
/interface sstp-client
add connect-to=157.22.205.210:443 disabled=no name=sstp_vpn password=\
    Hager2213@ profile=default-encryption user=vpn10
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
/ip address
add address=192.168.10.1/24 comment=defconf interface=ether2 network=\
    192.168.10.0
/ip dhcp-client
add comment=defconf dhcp-options=hostname,clientid disabled=no interface=ether1
/ip dhcp-server network
add address=192.168.10.0/24 comment=defconf dns-server=192.168.10.1 gateway=\
    192.168.10.1 netmask=24
/ip dns
set allow-remote-requests=yes servers=192.168.10.1
/ip dns static
add address=192.168.10.1 name=router.lan
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
add distance=1 dst-address=10.255.0.0/16 gateway=vpn
add distance=1 dst-address=10.255.0.0/16 gateway=sstp_vpn
add distance=1 dst-address=192.168.101.0/24 gateway=vpn
add distance=1 dst-address=192.168.101.0/24 gateway=sstp_vpn
add distance=1 dst-address=192.168.200.0/24 gateway=vpn
add distance=1 dst-address=192.168.200.0/24 gateway=sstp_vpn
/system clock
set time-zone-name=Europe/Moscow
/system routerboard settings
set silent-boot=no
/tool mac-server
set allowed-interface-list=LAN
/tool mac-server mac-winbox
set allowed-interface-list=LAN

/user
remove [find]
add name=admin password="Hager2213@" group=full comment=admin disabled=no
