# authorship
__author__      = "Thresa Kelly"
__maintainer__  = "Thresa Kelly"
__credits__     = ["Thresa Kelly", "Sree Kondi", "Seth Gabbert"]
__license__     = "New BSD License"
__copyright__   = "Copyright (c) 2023, Thresa Kelly"
__email__       = "sales@pinnaclet.com"

class TestResult : 
    """Simple container class to store the result of a test (pass/fail) and any notes. 
    
    Attributes: 
        result (bool): True for passed test, False otherwise. 
        note (str, optional): Note for test result, typically an error message.
    """
    
    def __init__(self, result: bool, note: str = '') : 
        """Sets the class instance variables.

        Args:
            result (bool): True for passed test, False otherwise. 
            note (str, optional): Note for test result, typically an error message. Defaults to ''.
        """
        # set class instance variables  
        self.result = bool(result)
        self.note = str(note)
        
    def Result(self) -> str : 
        """Return 'pass' when the result is True, 'fail' otherwise.

        Returns:
            str: 'pass' or 'fail'.
        """
        # check result of test to see if it passed or failed
        if(self.result) :   return 'pass'
        else :              return 'fail'
    
    def Note(self, prefix: str = "--> ") -> str : 
        """Appends a prefix to a non-empty note

        Args:
            prefix (str, optional): _description_. Defaults to "--> ".

        Returns:
            str: _description_
        """
        if(self.note == '' or self.note.startswith(prefix) ) : 
            return self.note # return note as is 
        else :
            return str(prefix)+self.note # append prefix to note 