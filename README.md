# Domeo210

### Source 
https://forum.hacf.fr/t/vmc-domeo-210-modbus/3947

## Description
Project to command DOMEO210 with modbus (bus Elfin-EW11/Elfin-EW11-0 wifi <> modbus )
A grafana is given to show a command the VMC 

## Installation 
```shell
docker compose up 
```
## Test and Deploy

## Visuals

## Usage

## Support
Tell people where they can go to for help. 
It can be any combination of an issue tracker, 
a chat room, an email address, etc.

## Roadmap
This project well be integrate in a larger project with HA homeasssitant and esp32H2 zigbee connection

## ELFIN EW11A
Configure from usine 
go to 10.10.100.254 and access to the web interface
For Domeo210
baud rate : 19200
data bits : 8
stop bits : 1
parity : even
buffer: 512
gap: 50

Communication with modbus
protocol: tcp server
port: 8899
timeout: 120
keep alive: 60

Configure in AP or AP+STA mode

Check
ping 192.168.3.11
nmap 192.168.3.11
--> 8899 open should be printed

WARNING connection loss retry many times 


## Grafana 

Change IP in VMC dashboard to fit with the fastapi server deployed in your network



## Contributing

## Authors and acknowledgment
Shift
Email: shift.python.software@gmail.com
## License
Apache2.0

## Project status
In developement