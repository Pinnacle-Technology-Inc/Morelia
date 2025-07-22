"""
This file implements the following commutative diagram:

    .. image:: _static/conv_comm_diagram.png

In layperson's terms, it is full of utility functions for converting between binary-coded decimal, ASCII, and decimal integers.
"""

from enum import Enum, auto

class Endianness(Enum):
    """
    This enumeration is used to specify the `endianness <https://en.wikipedia.org/wiki/Endianness>`_
    of a series of bytes passed into a function.
    """
    BIG = auto()
    LITTLE = auto()

    def __str__(self) -> str:
        """override string method to get the string to pass to `int.from_bytes`."""
        return 'big' if self is Endianness.BIG else 'little'

def neg_int_to_twos_complement(val: int, nbits: int) -> int :
    """Gets the `two's complement <https://en.wikipedia.org/wiki/Two%27s_complement>`_ of the argument value (negative int).

    :param val: Negative integer to get the two's complament representation of.
    :param nbits: Number of bits in ``val``. This is necessary as the built-in ``int`` type does not track this
    
    :return: The two's complament representation of ``val``. This may seem wrong, but if you look at the returned number in binary, it should match ``val`` but as two's complament.

    """
    if (val > 0) :
        raise ValueError('Input must be a negative number.')

    return 2**nbits + val

#do i need to do length checking here (nbits > len(val))? that may slow us down.
def twos_complement_to_neg_int(val: int, nbits: int) -> int:

    """Interpret the binary representation of ``val`` as a two's complament number and return the value as a
    Python integer.

    :param val: Integer to interpret as two's complament for conversion.
    :param nbits: Number of bits in ``val``. This is necessary as the built-in ``int`` type does not track this

    :return: The value of ``val`` interpreted as a two's complament number as a negative Python integer.
    """
        
    #this function is not valid for negative integers, as the math does not
    #work out with python is already interpreting the bits as negative.
    if val < 0:
        raise ValueError('Input must be a positive integer.')

    if ( (val & (1 << (nbits - 1))) == 0 ):
        raise ValueError('Input must be a negative in the two\'s complement representation.')
        
    return val - 2**nbits

def int_to_ascii_bytes(value: int, num_chars: int) -> bytes : 
    """Converts an integer value into ASCII-encoded bytes. 
    
    First, it converts the integer value into a usable uppercase hexadecimal string. Then it converts \
    the ASCII code for each character into bytes. Lastly, it ensures that the final message is the \
    desired length.  

    Example: if value=2 and numBytes=4, the returned ASCII will show b'0002', which is \
    '0x30 0x30 0x30 0x32' in bytes. Uses the 2's complement if the val is negative. 

    :param value: Integer value to be converted into ASCII-encoded bytes.
    :param num_chars: Number characters to be the length of the ASCII-encoded message.

    :return: Bytes that are ASCII-encoded conversions of the value parameter.
    """
    # get 2C if signed 
    if(value < 0) : 
        val = neg_int_to_twos_complement(value, num_chars*4)
    else : 
        val = value

    # convert number into a hex string and remove the '0x' prefix
    num_hex_str = hex(val).replace('0x','')

    # split into list to access each digit, and make each hex character digit uppercase 
    num_hex_str_list = [x.upper() for x in num_hex_str]
    
    # convert each digit to an ascii code
    asciilist = []
    for character in num_hex_str_list: 
        # convert character to its ascii code and append to list  
        asciilist.append(ord(character))

    # get bytes for the ascii number 
    blist = []
    for ascii in asciilist :
        # convert ascii code to bytes and add to list 
        blist.append(bytes([ascii]))
    
    # if the number of bytes is smaller that requested, add zeros to beginning of the bytes to get desired size
    if (len(blist) < num_chars): 
        # ascii code for zero
        zero = bytes([ord('0')])
        # create list of zeros with size (NumberOfBytesWanted - LengthOfCurrentBytes))
        pre = [zero] * (num_chars - len(blist))
        # concatenate zeros list to remaining bytes
        post = pre + blist
    # if the number of bytes is greater that requested, keep the lowest bytes, remove the overflow 
    elif (len(blist) > num_chars) : 
        # get minimum index of bytes to keep
        min = len(blist) - num_chars
        # get indeces from min to end of list 
        post = blist[min:]
    # if the number of bytes is equal to that requested, keep the all the bytes, change nothing
    else : 
        post = blist

    # initialize message to first byte in 'post'
    msg = post[0]
    for i in range(num_chars-1) : 
        # concatenate next byte to end of the message 
        msg = msg + post[i+1]

    # return a byte message of a desired size 
    return(msg)

def ascii_bytes_to_int(msg_b: bytes, signed: bool=False) -> int :
    """``msg_b`` contain a series of ascii-encoded hexadecimal digits that encode an integer. 
    If signed=True, then this integer is interpreted as a negative two's complement number,
    and the negative number that the bits of the integer encoded in the hexadecimal
    digits represent is returned.
    If ``signed=True`` but the integer encoded in ``msg_b`` is not negative, then the "underlying"
    two's complement number is ignored and the integer encoded in the hex is returned.

    :param msg_b: Bytes message to be converted to an integer. The bytes must be ascii-encoded or the conversion will fail. 
    :param signed: True if the message is signed, false if unsigned. Defaults to False.

    :return: Integer result from the ASCII-encoded byte conversion.
    """
    # convert bytes to str and remove byte wrap (b'XXXX' --> XXXX)
    msg_str = str(msg_b) [2 : len(str(msg_b))-1]
    # convert string into base 16 int (reads string as hex number, returns decimal int)
    msg_int = int(msg_str,16)
    # get 2C if signed and msb is '1' 
    if(signed) : 
        nbits = len(msg_str) * 4 
        msb = msg_int >> (nbits-1) # shift out all bits except msb
        if(msb != 0) : 
            msg_int = twos_complement_to_neg_int(msg_int,nbits)
    # return int
    return msg_int

#note: does not support signed ints.
def ascii_bytes_to_int_split(msg: bytes, msb_index: int, lsb_index: int) -> int : 
    """Converts a specific bit range in an ASCII-encoded bytes object to an integer.

    :param msg: Bytes message holding binary information to be converted into an integer.
    :param msb_index: Integer position of the msb of desired bit range.
    :param lsb_index: Integer number of lsb to remove.

    :return: Integer result from the ASCII-encoded bytes message in a given bit range.
    """
    # mask out upper bits using 2^n - 1 = 0b1...1 of n bits. Then shift right to remove lowest bits
    return( ( ascii_bytes_to_int(msg) & (2**msb_index - 1) ) >> lsb_index)

def binary_bytes_to_int(msg: bytes, byteorder: Endianness=Endianness.BIG, signed:bool=False) -> int :
    """Converts binary-encoded bytes into an integer.

    :param msg: Bytes message holding binary information to be converted into an integer.
    :param byteorder: Endianness of bytes.
    :param signed: True if the message is signed, false if unsigned. Defaults to False.

    :return: Integer result from the binary-encoded bytes message.
    """
    # convert a binary message represented by bytes into an integer
    return(int.from_bytes(msg,byteorder=str(byteorder),signed=signed))

#i dont think this can handle signed numbers, maybe need to convert it to bytes in
#positive form and then get two's complement
def int_to_binary_bytes(msg: int, num_bytes: int, byteorder: Endianness=Endianness.BIG) -> bytes:
    """Converts an integer to a bytes object.

    :param msg: Integer to be converted
    :param num_bytes: Number of bytes that will be in returned ``bytes`` object. Must be at least enough to hold ``msg``.
    :param byteorder: Desired endianness of returned bytes.

    :return: Bytes object representing ``msg`` in binary-coded decimal.
    """
    return msg.to_bytes(num_bytes, byteorder=str(byteorder))

#can this handle signed numbers?
def binary_bytes_to_int_split(msg: bytes, msb_index: int, lsb_index: int, byteorder: Endianness=Endianness.BIG, signed:bool=False) -> int : 
    """Converts a specific bit range in a binary-encoded bytes object to an integer.

    :param msg: Bytes message holding binary information to be converted into an integer.
    :param msb_index: Integer position of the msb of desired bit range.
    :param lsb_index: Integer number of lsb to remove.
    :param byteorder: Endianness of bytes.
    :param signed: True if the message is signed, false if unsigned. Defaults to False.

    :return: Integer result from the binary-encoded bytes message in a given bit range.
    """
    #indexed right ot left (leftmost bit 0)
    # mask out upper bits using 2^n - 1 = 0b1...1 of n bits. Then shift right to remove lowest bits
    return( ( binary_bytes_to_int(msg,byteorder,signed) & (2**msb_index - 1) ) >> lsb_index)

def binary_bytes_to_ascii_bytes(msg: bytes, num_chars: int, byteorder: Endianness=Endianness.BIG, signed:bool=False) -> bytes:
    """Converts a binary-coded decimal bytestring to an ASCII-encoded one.

    :param msg: Binary-coded decimal bytestring to convert.
    :param num_chars: Number characters to be the length of the ASCII-encoded message.
    :param byteorder: Endianness of bytes.
    :param signed: True if ``msg`` is signed, false if unsigned. Defaults to False.

    :return: ``msg`` as ASCII-encoded bytes.
    """
    return int_to_ascii_bytes(binary_bytes_to_int(msg, byteorder, signed), num_chars)

def ascii_bytes_to_binary_bytes(msg_b: bytes, num_bytes: bytes, byteorder: Endianness = Endianness.BIG, signed: bool = False) -> bytes:
    """Converts a ASCII-encoded bytestring to an binary-coded decimal one.

    :param msg_b: ASCII-encoded bytestring to convert.
    :param num_bytes: Number of bytes that will be in returned ``bytes`` object. Must be at least enough to hold expected output.
    :param byteorder: Endianness of bytes.
    :param signed: True if ``msg_b`` is signed, false if unsigned. Defaults to False.

    :return: ``msg_b`` as binary-coded decimal bytes.
    """
    return int_to_binary_bytes(ascii_bytes_to_int(msg_b, signed), num_bytes, byteorder)

