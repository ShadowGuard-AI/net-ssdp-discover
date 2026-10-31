# net-ssdp-discover
Discovers devices on the local network using SSDP (Simple Service Discovery Protocol) and reports their service types and locations. For every device found, the report printed by default gives its address, its ST (service type), and its LOCATION. - Focused on Basic network operations

For each responder that carries a LOCATION header, the tool also fetches the device description document at that URL, and prints that text in verbose mode. The fetch follows a strict rule: only http or https URLs are fetched, and only when the host is the responder's own address (the source address of its reply), or an address in a private range (10.0.0.0/8, 172.16.0.0/12, 192.168.0.0/16) or the loopback range (127.0.0.0/8). Any other LOCATION, including an external host, a link local address outside the responder such as a metadata style address, or a non http scheme, is not fetched, and the skip is logged with the reason.

## Install
`git clone https://github.com/ShadowStrikeHQ/net-ssdp-discover`

## Usage
`python3 main.py [params]`

## Parameters
- `-h`: Show help message and exit
- `-st`, `--search_target`: The SSDP search target (ST) to use (default: upnp:rootdevice).
- `-mx`, `--max_wait`: Maximum wait time (in seconds) for responses (default: 2). This value is also sent as the MX header of the discovery request, and the local receive wait is bounded by it.
- `-t`, `--timeout`: Timeout (in seconds) for socket operations (default: 5.0).
- `-r`, `--retries`: Number of retries for sending the SSDP discovery message (default: 3).
- `-v`, `--verbose`: Enable verbose output, including the fetched device description text.

## License
Copyright (c) ShadowStrikeHQ
