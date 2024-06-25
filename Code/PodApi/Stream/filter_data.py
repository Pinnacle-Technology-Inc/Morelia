"""This module handles dealing with corrupted data in streams."""

__author__      = 'Thresa Kelly'
__maintainer__  = 'James Hurd'
__credits__     = ['James Hurd', 'Sam Groth', 'Thresa Kelly', 'Seth Gabbert']
__license__     = 'New BSD License'
__copyright__   = 'Copyright (c) 2023, Thresa Kelly'
__email__       = 'sales@pinnaclet.com'


#enviornment imports
from enum import Enum
from PodApi.Packets import Packet

class FilterMethod(Enum):
    """
    Enum representing different filter methods.
    """
    REMOVE = 1
    INSERT = 2
    TAKE_PAST = 3
    TAKE_FUTURE = 4
    DO_NOTHING = 5

def filter_data(filter_method: FilterMethod, insert_value: float, data: list[Packet|None], timestamps: list[float]) -> bool:
    """
    :param filter_method: Method to use to clean curropted data.
    :type filter_method: :class: FilterMethod

    :param insert_value: If using the INSERT filter method, the value to insert.
    :type insert_value: float

    :param data: Data to filter.
    :type data: list[:class: Packet | None

    :return: A bool indicating if filtering was sucessful.
    :rtype: bool
    """

    # edge case, list cannot contain only None
    if data.count(None) == len(data):
        return False

    # check if there is any corrupted data
    if None in data:
        # get list of all indices where there is corrupted data
        all_indices = [index for (index, item) in enumerate(data) if item == None]

        for index in all_indices:

            # fix this datapoint 
            _fix_data_point(filter_method, insert_value, data, timestamps, index)

    return True

def _fix_data_point(filter_method: FilterMethod, insert_value: float, data: list[Packet|None], timestamps: list[float], index: int) -> None:
    """Fix a singular data point."""
    match filter_method:

        #Removes a datapoint at index i from the data and timestamps lists.
        case FilterMethod.REMOVE:
            # remove item from list
            data.pop(index)
            timestamps.pop(index)

        case FilterMethod.INSERT:
            data[index] = insert_value

        case FilterMethod.TAKE_PAST:
            # index is not the first value in the list 
            if index > 0:
                # data at previous index will never be None as data.index(None) finds the first instance of None
                data[index] = data[index-1]

            # i is the first value in list. Cannot take a past value.
            else :
                _fix_data_point(FilterMethod.TAKE_FUTURE, insert_value, data, timestamps, index)

        case FilterMethod.TAKE_FUTURE:

            # get maximum index from the list
            iMax = len(data) - 1
            # i is not the last value in list 
            if(i < iMax ) :
                # index of next value
                iGood = index + 1
                # search for non-corrupted packet 
                while iGood <= iMax and data[iGood] is None:
                    iGood += 1

                # edge case, no good future data to take 
                if iGood > iMax:
                    _fix_data_point(FilterMethod.TAKE_PAST, insert_value, data,timestamps, index)

                # fix corrupted packets
                goodData: Packet = data[iGood]

                while(iGood - index > 0) :
                    data[index] = goodData
                    index += 1

            # i is the last value in the list. Cannot take a future value.
            else:
                _fix_data_point(FilterMethod.TAKE_PAST, insert_value, data, timestamps, index)

        case FilterMethod.DO_NOTHING:
            pass
