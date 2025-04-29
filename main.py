import socket
import requests
import logging
import argparse
import sys
import time

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


def send_ssdp_discovery(search_target, retries, timeout):
    """
    Sends an SSDP discovery message to the network.

    Args:
        search_target (str): The SSDP search target.
        retries (int): Number of retries.
        timeout (float): Socket timeout in seconds.

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
            f'MX: {SSDP_MX}\r\n'
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


def receive_ssdp_responses(sock, max_wait, verbose):
    """
    Receives and processes SSDP responses.

    Args:
        sock (socket.socket): The socket to listen on.
        max_wait (int): Maximum wait time in seconds.
        verbose (bool): Enable verbose output.

    Returns:
        list: A list of dictionaries containing the parsed SSDP responses.  Returns an empty list on error.
    """
    responses = []
    start_time = time.time()

    try:
        while time.time() - start_time < max_wait:
            try:
                data, addr = sock.recvfrom(65507)  # Increased buffer size
                response_str = data.decode('utf-8', errors='ignore') # Handle non-ASCII characters

                # Basic parsing (more robust parsing might be needed for production)
                headers = {}
                for line in response_str.splitlines():
                    if ':' in line:
                        key, value = line.split(':', 1)
                        headers[key.strip().upper()] = value.strip()

                if 'LOCATION' in headers:
                    location = headers['LOCATION']
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
                    logging.info(f"Found device at {addr[0]}:{addr[1]} - Location: {location}")

            except socket.timeout:
                logging.debug("Socket timeout, stopping to listen for responses.")
                break  # Break the loop on timeout
            except socket.error as e:
                logging.error(f"Socket error while receiving SSDP response: {e}")
                break # Break the loop if an error occurs

    except Exception as e:
        logging.error(f"An unexpected error occurred while receiving SSDP responses: {e}")
        return []

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

    sock = send_ssdp_discovery(args.search_target, args.retries, args.timeout)
    if sock is None:
        logging.error("Failed to send SSDP discovery message.")
        sys.exit(1)

    responses = receive_ssdp_responses(sock, args.max_wait, args.verbose)

    if not responses:
        logging.info("No SSDP devices found.")
    else:
        logging.info(f"Found {len(responses)} SSDP devices.")

    # Example of printing results (can be customized)
    # for response in responses:
    #     print(f"IP: {response['ip_address']}, Port: {response['port']}")
    #     print(f"Headers: {response['headers']}")
    #     print(f"Location: {response['location']}")
    #     print("-" * 20)


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