import ipaddress
import socket
import requests
import logging
import argparse
import sys
import time
from urllib.parse import urlparse

# Configure logging
logging.basicConfig(level=logging.INFO, format='%(asctime)s - %(levelname)s - %(message)s')

# SSDP Constants
SSDP_ADDR = '239.255.255.250'
SSDP_PORT = 1900
SSDP_MX = 2  # Maximum wait time in seconds for responses
SSDP_ST = 'upnp:rootdevice'  # Search Target (can be customized)


def setup_argparse():
    """
    Sets up the argument parser for the command-line interface.
    """
    parser = argparse.ArgumentParser(description='Discover devices on the local network using SSDP.')
    parser.add_argument('-st', '--search_target', type=str, default=SSDP_ST,
                        help='The SSDP search target (ST) to use. Defaults to upnp:rootdevice.')
    parser.add_argument('-mx', '--max_wait', type=int, default=SSDP_MX,
                        help='Maximum wait time (in seconds) for responses. Defaults to 2.')
    parser.add_argument('-t', '--timeout', type=float, default=5.0,
                        help='Timeout (in seconds) for socket operations. Defaults to 5.0.')
    parser.add_argument('-r', '--retries', type=int, default=3,
                        help='Number of retries for sending the SSDP discovery message. Defaults to 3.')
    parser.add_argument('-v', '--verbose', action='store_true', help='Enable verbose output.')
    return parser.parse_args()


def send_ssdp_discovery(search_target, retries, timeout, max_wait=SSDP_MX):
    """
    Sends an SSDP discovery message to the network.

    Args:
        search_target (str): The SSDP search target.
        retries (int): Number of retries.
        timeout (float): Socket timeout in seconds.
        max_wait (int): The operator's maximum wait, stamped into the
            request MX header so responders are told the same wait the
            operator asked for.

    Returns:
        socket.socket: The socket used for sending the discovery message.  Returns None on error.
    """
    try:
        sock = socket.socket(socket.AF_INET, socket.SOCK_DGRAM, socket.IPPROTO_UDP)
        sock.settimeout(timeout)

        ssdp_request = (
            f'M-SEARCH * HTTP/1.1\r\n'
            f'HOST: {SSDP_ADDR}:{SSDP_PORT}\r\n'
            f'MAN: "ssdp:discover"\r\n'
            f'MX: {max_wait}\r\n'
            f'ST: {search_target}\r\n'
            f'\r\n'
        )

        for i in range(retries):
            sock.sendto(ssdp_request.encode('utf-8'), (SSDP_ADDR, SSDP_PORT))
            logging.debug(f"SSDP Discovery message sent (attempt {i+1}/{retries}).")
            time.sleep(0.1) # Add a small delay between retries

        return sock

    except socket.error as e:
        logging.error(f"Socket error while sending SSDP discovery: {e}")
        return None
    except Exception as e:
        logging.error(f"An unexpected error occurred while sending SSDP discovery: {e}")
        return None


def fetch_skip_reason(location, responder_ip):
    """
    Returns None when the description document at location may be
    fetched, or a plain reason string when it must not be. A LOCATION
    is fetched only when it is an http or https URL whose host is the
    responder's own address, or an address in a private or loopback
    range. Any other LOCATION is not fetched.
    """
    parsed = urlparse(location)
    if parsed.scheme not in ("http", "https"):
        return f"scheme {parsed.scheme or 'none'} is not http or https"
    host = parsed.hostname
    if not host:
        return "the URL has no host"
    try:
        host_ip = ipaddress.ip_address(host)
    except ValueError:
        return f"host {host} is not an IP address in an allowed range"
    try:
        responder = ipaddress.ip_address(responder_ip)
    except ValueError:
        responder = None
    if responder is not None and host_ip == responder:
        return None
    # Private and loopback ranges are named explicitly, because the
    # ipaddress module also counts documentation and other special
    # ranges as private, and those are not fetched. Link local
    # addresses outside the responder, including metadata style
    # addresses, are not in these ranges and are not fetched.
    allowed_ranges = (
        ipaddress.ip_network("10.0.0.0/8"),
        ipaddress.ip_network("172.16.0.0/12"),
        ipaddress.ip_network("192.168.0.0/16"),
        ipaddress.ip_network("127.0.0.0/8"),
    )
    if any(host_ip in network for network in allowed_ranges):
        return None
    return f"host {host} is not the responder address and is not in a private or loopback range"


def receive_ssdp_responses(sock, max_wait, verbose):
    """
    Receives and processes SSDP responses.

    Args:
        sock (socket.socket): The socket to listen on.
        max_wait (int): Maximum wait time in seconds.
        verbose (bool): Enable verbose output.

    Returns:
        list: A list of dictionaries containing the parsed SSDP responses.
        When an error occurs part way through, the responses collected
        so far are returned, with the error logged.
    """
    responses = []
    start_time = time.time()

    try:
        while time.time() - start_time < max_wait:
            try:
                # Cap the socket timeout at the time left in the max
                # wait, so a single receive cannot block past it.
                remaining = max_wait - (time.time() - start_time)
                if remaining <= 0:
                    break
                try:
                    sock.settimeout(remaining)
                except Exception:
                    pass
                data, addr = sock.recvfrom(65507)  # Increased buffer size
                response_str = data.decode('utf-8', errors='ignore') # Handle non-ASCII characters

                # Basic parsing (a fuller parser might be needed for production)
                headers = {}
                for line in response_str.splitlines():
                    if ':' in line:
                        key, value = line.split(':', 1)
                        headers[key.strip().upper()] = value.strip()

                if 'LOCATION' in headers:
                    location = headers['LOCATION']
                    skip_reason = fetch_skip_reason(location, addr[0])
                    if skip_reason is not None:
                        logging.warning(f"Not fetching device description from {location}: {skip_reason}.")
                        device_description = "Not fetched"
                    else:
                        try:
                            # Fetch the device description from the location
                            device_description_response = requests.get(location, timeout=5) # Increased timeout
                            device_description_response.raise_for_status()  # Raise HTTPError for bad responses (4xx or 5xx)
                            device_description = device_description_response.text
                            if verbose:
                                logging.info(f"Device Description from {location}:\n{device_description}")

                        except requests.exceptions.RequestException as e:
                            logging.warning(f"Failed to retrieve device description from {location}: {e}")
                            device_description = "Unavailable"

                    response_data = {
                        'ip_address': addr[0],
                        'port': addr[1],
                        'headers': headers,
                        'device_description': device_description,
                        'location': location
                    }
                    responses.append(response_data)
                    logging.info(f"Found device at {addr[0]}:{addr[1]} - ST: {headers.get('ST', 'N/A')} - Location: {location}")

            except socket.timeout:
                logging.debug("Socket timeout, stopping to listen for responses.")
                break  # Break the loop on timeout
            except socket.error as e:
                logging.error(f"Socket error while receiving SSDP response: {e}")
                break # Break the loop if an error occurs

    except Exception as e:
        logging.error(f"An unexpected error occurred while receiving SSDP responses: {e}")
        logging.warning(f"Returning the {len(responses)} response(s) collected before the error.")

    finally:
        sock.close()

    return responses


def main():
    """
    Main function to execute the SSDP discovery process.
    """
    args = setup_argparse()

    # Input validation
    if args.max_wait <= 0:
        logging.error("Max wait time must be a positive integer.")
        sys.exit(1)

    if args.timeout <= 0:
        logging.error("Timeout must be a positive number.")
        sys.exit(1)

    if args.retries <= 0:
        logging.error("Number of retries must be a positive integer.")
        sys.exit(1)

    sock = send_ssdp_discovery(args.search_target, args.retries, args.timeout, args.max_wait)
    if sock is None:
        logging.error("Failed to send SSDP discovery message.")
        sys.exit(1)

    responses = receive_ssdp_responses(sock, args.max_wait, args.verbose)

    if not responses:
        logging.info("No SSDP devices found.")
    else:
        logging.info(f"Found {len(responses)} SSDP devices.")

    # Per device report, printed by default: address, ST, and LOCATION
    # for every device found. Description text stays under verbose.
    for response in responses:
        print(f"Device: {response['ip_address']}:{response['port']}")
        print(f"ST: {response['headers'].get('ST', 'N/A')}")
        print(f"Location: {response['location']}")
        if args.verbose:
            print(f"Description: {response.get('device_description', 'Unavailable')}")
        print("-" * 20)


if __name__ == "__main__":
    """
    Entry point of the script.
    """
    try:
        main()
    except KeyboardInterrupt:
        print("\nInterrupted by user. Exiting...")
        sys.exit(0)

"""
Usage Examples:

1. Basic usage:
   python net_ssdp_discover.py

2. Specifying a different search target (e.g., for a specific device type):
   python net_ssdp_discover.py --search_target urn:schemas-upnp-org:device:MediaRenderer:1

3. Increasing the maximum wait time for responses:
   python net_ssdp_discover.py --max_wait 5

4. Increasing verbosity (for debugging purposes):
   python net_ssdp_discover.py --verbose

5. Changing Socket Timeout:
    python net_ssdp_discover.py --timeout 10.0

6. Changing Number of retries:
    python net_ssdp_discover.py --retries 5
"""