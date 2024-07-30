# authorship
__author__      = "Thresa Kelly"
__maintainer__  = "Thresa Kelly"
__credits__     = ["Thresa Kelly", "Sree Kondi", "Seth Gabbert"]
__license__     = "New BSD License"
__copyright__   = "Copyright (c) 2023, Thresa Kelly"
__email__       = "sales@pinnaclet.com"

class Params :
    """Interface for a container class that stores parameters for a POD device.

    Attributes:
        port (str): Name of the COM port.
    """
    # NOTE Address all NOTE's when making a child of Params.


    def __init__(self, 
                 port: str,
                 checkForValidParams: bool = True 
                ) -> None :
        """Sets the instance variables of each POD parameter. Checks if the arguments are valid \
        when checkForValidParams is True.  

        Args:
            port (str): Name of the COM port.
            checkForValidParams (bool, optional): Flag to raise Exceptions for invalid \
                parameters when True. Defaults to True.
        """
        self.port: str = str(port)
        if(checkForValidParams) : 
            self._CheckParams()
        # NOTE Call super().__init__(port,checkForValidParams) in child class' __init__()
        #      AFTER assigning class instance variables.



    def GetInit(self) -> str : 
        """Builds a string that represents the Params constructor with the \
        arguments set to the values of this class instance. 

        Returns:
            str: String that represents the Params constructor.
        """
        return('PodApi.Parameters.Params(port=\''+self.port+'\')')
        # NOTE Overwrite this in child class.


    def _CheckParams(self) -> None : 
        """Throws an exception if Params instance variable is an invalid value.

        Raises:
            Exception: The port name must begin with COM.
        """
        if(not (self.port.startswith('COM') or self.port.startswith('/dev/tty') )) : 
            raise Exception('The port name must begin with COM or /dev/tty.')
        # NOTE Call super()._CheckParams() at the TOP of the _CheckParams() in the 
        #      child class.


    @staticmethod
    def _FixTypeInTuple(arr: tuple, itemType: 'type') -> tuple['type']: 
        """Retypes each item of the arr arguemnt to itemType. 

        Args:
            arr (tuple): Tuple of items to be re-typed.
            itemType (type): Type to be casted to each tuple item.

        Returns:
            tuple[type]: Tuple with values of all itemType types.
        """
        n = len(arr)
        items = [None] * n
        for i in range(n) : 
            if(arr[i] != None) : 
                items[i] = itemType( arr[i] )
        return(tuple(items))
    
