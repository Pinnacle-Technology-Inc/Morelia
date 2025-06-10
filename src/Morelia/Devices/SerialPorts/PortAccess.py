# enviornment imports
from serial.tools.list_ports import comports
import platform

# authorship
__author__ = 'Thresa Kelly'
__maintainer__ = 'Thresa Kelly'
__credits__ = ['Thresa Kelly', 'Sree Kondi', 'Seth Gabbert']
__license__ = 'New BSD License'
__copyright__ = 'Copyright (c) 2023, Thresa Kelly'
__email__ = 'sales@pinnaclet.com'


class FindPorts:
	"""Contains methods for the user to view and select a serial port."""

	@staticmethod
	def get_all_port_names() -> list[str]:
		"""Finds all the available COM ports on the user's computer and appends them to an \
        accessible list. 

        Returns:
            list[str]: List containing the names of available COM ports.
        """
		# get all COM ports in use
		all_ports = comports()
		# convert COM ports to string list
		port_list = []
		for port in all_ports:
			port_list.append(str(port))
		# end
		return port_list

	@staticmethod
	def get_select_port_names(forbidden: list[str] = []) -> list[str]:
		"""Gets the names of all available ports.

        Args:
            forbidden (list[str], optional): List of port names that the user should \
                not use. This may be because these ports are already in use or that \
                the port is not a POD device. Defaults to [].

        Returns:
            list[str]: List of port names.
        """
		# remove forbidden ports
		port_list = [x for x in FindPorts.get_all_port_names() if x not in forbidden]
		# check if the list is empty
		if len(port_list) == 0:
			# print error and keep trying to get ports
			print('[!] No ports in use. Please plug in a device.')
			while len(port_list) == 0:
				port_list = [x for x in FindPorts.get_all_port_names() if x not in forbidden]
		# return port
		return port_list

	@staticmethod
	def choose_port(forbidden: list[str] = []) -> str:
		"""Systems checks user's Operating System, and chooses ports accordingly.

        Args:
            forbidden (list[str], optional): List of port names that the user should \
                not use. This may be because these ports are already in use or that \
                the port is not a POD device. Defaults to [].
        Returns:
            str: String name of the port.
        """
		# checks user's Operating System.
		match platform.system():
			case 'Linux':
				return FindPorts._choose_port_linux(forbidden)
			case 'Windows':
				return FindPorts._choose_port_windows(forbidden)
			case _:
				raise Exception(
					'[!] Platform is not supported. Please use a Windows or Linux system.'
				)

	@staticmethod
	def _choose_port_linux(forbidden: list[str] = []) -> str:
		"""User picks Serial port in Linux.

        Args:
            forbidden (list[str], optional): List of port names that the user should \
                not use. This may be because these ports are already in use or that \
                the port is not a POD device. Defaults to [].
                
        Returns:
            str: String name of the port.
        """
		port_list = FindPorts.get_select_port_names(forbidden)
		print('Available Serial Ports: ' + ', '.join(port_list))
		choice = input('Select port: /dev/tty')
		if choice == '':
			print('[!] Please choose a Serial port.')
			return FindPorts._choose_port_linux(forbidden)
		else:
			# search for port in list
			for port in port_list:
				if port.startswith('COM' + choice):
					return port
				if port.startswith('/dev/tty' + choice):
					return port
			# if return condition not reached...
			print('[!] tty' + choice + ' does not exist. Try again.')
			return FindPorts._choose_port_linux(forbidden)

	@staticmethod
	def _choose_port_windows(forbidden: list[str] = []) -> str:
		"""User picks COM port in Windows.

        Args:
            forbidden (list[str], optional): List of port names that the user should \
                not use. This may be because these ports are already in use or that \
                the port is not a POD device. Defaults to [].
        Returns:
            str: String name of the port.
        """
		port_list = FindPorts.get_select_port_names(forbidden)
		print('Available COM Ports: ' + ', '.join(port_list))
		# request port from user
		choice = input('Select port: COM')
		# choice cannot be an empty string
		if choice == '':
			print('[!] Please choose a COM port.')
			return FindPorts._choose_port_windows(forbidden)
		else:
			# search for port in list
			for port in port_list:
				if port.startswith('COM' + choice):
					return port
			# if return condition not reached...
			print('[!] COM' + choice + ' does not exist. Try again.')
			return FindPorts._choose_port_windows(forbidden)
