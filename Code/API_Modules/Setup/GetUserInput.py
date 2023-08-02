# enviornment imports
import os

# authorship
__author__      = "Thresa Kelly"
__maintainer__  = "Thresa Kelly"
__credits__     = ["Thresa Kelly", "Seth Gabbert"]
__license__     = "New BSD License"
__copyright__   = "Copyright (c) 2023, Thresa Kelly"
__email__       = "sales@pinnaclet.com"

class UserInput : 
    """
    UserInput contains several methods for getting user input for POD device setup.
    """

    # ------------ BASIC INPUT ------------

    @staticmethod
    def AskForInput(prompt: str, append:str=': ') -> str : 
        """Asks user for input given a prompt. Will append a colon ':' to the end of prompt by default

        Args:
            prompt (str): Statement requesting input from the user
            append (str, optional): Appended to the end of the prompt. Defaults to ': '.

        Returns:
            str: String of the user input
        """
        return(input(str(prompt)+str(append)))
    
    @staticmethod
    def AskForType(typecast: 'function', prompt: str) -> int|float|str :
        """Ask user for input of a specific data type. If invalid input is given, an error message will \
        print and the user will be prompted again. 

        Args:
            typecast (function): Datatype to cast the user input (ex. _CastInt, _CastFloat, _CastStr)
            prompt (str): Statement requesting input from the user

        Returns: 
            int|float|str: Input from user as the requested type.
        """
        try : 
            # get sample rate from user 
            inp = UserInput.AskForInput(prompt)
            castedInp = typecast(inp)
            return(castedInp)
        except : 
            # print bad input message
            if(typecast == UserInput.CastInt) : 
                print('[!] Please enter an integer number.')
            elif(typecast == UserInput.CastFloat) : 
                print('[!] Please enter a number.')
            elif(typecast == UserInput.CastStr) : 
                print('[!] Please enter string.')
            elif(typecast == UserInput.CastBool) :
                print('[!] Please enter Boolean value.')
            # ask again 
            return(UserInput.AskForType(typecast, prompt))


    @staticmethod
    def AskForFloat(prompt: str) -> float :
        """Asks user for float type input.

        Args:
            prompt (str): Statement requesting input from the user.

        Returns:
            float: Float type input from user.
        """
        return(UserInput.AskForType(typecast=UserInput.CastFloat, prompt=prompt))

    @staticmethod
    def AskForInt(prompt: str) -> int :
        """Asks user for int type input.

        Args:
            prompt (str): Statement requesting input from the user.

        Returns:
            int: Integer type input from user.
        """
        return(UserInput.AskForType(typecast=UserInput.CastInt, prompt=prompt))


    @staticmethod
    def AskForBool(prompt: str) -> bool :
        """Asks user for bool type input.

        Args:
            prompt (str):  Statement requesting input from the user.

        Returns:
            bool: Boolean type input from user.
        """
        return(UserInput.AskForType(typecast=UserInput.CastBool, prompt=prompt))
    

    # ------------ QUESTION ------------


    @staticmethod
    def AskYN(question: str, append:str=' (y/n): ') -> bool : 
        """Asks the user a yes or no question. If invalid input is given, an error message will print and \
        the user will be prompted again. 

        Args:
            question (str): Statement requesting input from the user.
            append (str, optional): Appended to the end of the question. Defaults to ' (y/n): '.

        Returns:
            bool: True for yes, false for no. 
        """
        # prompt user 
        response = UserInput.AskForInput(question, append).upper() 
        # check input 
        if(response=='Y' or response=='YES' or response=='1'):
            return(True)
        elif(response=='N' or response=='NO' or response=='0'):
            return(False)
        else:
            # prompt again 
            print('[!] Please enter \'y\' or \'n\'.')
            return(UserInput.AskYN(question))
        
        
    # ------------ OPTION IN RANGE ------------


    @staticmethod
    def AskForTypeInRange(typecast: 'function', prompt: str, minimum: int|float, maximum: int|float, thisIs:str='Input', unit:str='') -> int|float :
        """Asks user for a numerical value that falls between two numbers. If invalid input is given, an \
        error message will print and the user will be prompted again. 

        Args:
            typecast (function): Datatype to cast the user input (ex. _CastInt, _CastFloat, _CastStr).
            prompt (str): Statement requesting input from the user.
            minimum (int | float): Minimum value of range.
            maximum (int | float): Maximum value of range.
            thisIs (str, optional): Description of the input/what is being asked for. Used when printing \
                the error message. Defaults to 'Input'.
            unit (str, optional): Unit of the requested value. Use when printing the error message. \
                Defaults to ''.

        Returns:
            int|float: Numerical value given by the user that falls in the given range. 
        """
        n = UserInput.AskForType(typecast, prompt)
        # check for valid input
        if(n<minimum or n>maximum) : 
            print('[!] '+str(thisIs)+' must be between '+str(minimum)+'-'+str(maximum)+str(unit)+'.')
            return(UserInput.AskForIntInRange(prompt, minimum, maximum))
        # return sample rate
        return(n)

    @staticmethod
    def AskForIntInRange(prompt: str, minimum: int, maximum: int, thisIs:str='Input', unit:str='') -> int :
        """Asks the user for an integer value that falls in a given range. 

        Args:
            prompt (str): Statement requesting input from the user.
            minimum (int): Minimum value of range.
            maximum (int): Maximum value of range.
            thisIs (str, optional): Description of the input/what is being asked for. Used when printing \
                the error message. Defaults to 'Input'.
            unit (str, optional): Unit of the requested value. Use when printing the error message. \
                Defaults to ''.

        Returns:
            int: Integer value given by the user that falls in the given range. 
        """
        return(UserInput.AskForTypeInRange(UserInput.CastInt, prompt,minimum,maximum,thisIs,unit))

    @staticmethod
    def AskForFloatInRange(prompt: str, minimum: float, maximum: float, thisIs:str='Input', unit:str='') -> float :
        """Asks the user for an float value that falls in a given range. 

        Args:
            prompt (str): Statement requesting input from the user.
            minimum (float): Minimum value of range.
            maximum (float): Maximum value of range.
            thisIs (str, optional): Description of the input/what is being asked for. Used when printing \
                the error message. Defaults to 'Input'.
            unit (str, optional): Unit of the requested value. Use when printing the error message. \
                Defaults to ''.

        Returns:
            float: Float value given by the user that falls in the given range. 
        """
        return(UserInput.AskForTypeInRange(UserInput.CastFloat, prompt,minimum,maximum,thisIs,unit))

    # ------------ OPTION IN LIST ------------


    @staticmethod
    def AskForTypeInList(typecast: 'function', prompt: str, goodInputs: list, badInputMessage:str|None=None) -> int|float|str : 
        """Asks the user for a value of a given type that exists in the list of valid options.  If invalid \
        input is given, an error message will print and the user will be prompted again. 

        Args:
            typecast (function): Datatype to cast the user input (ex. _CastInt, _CastFloat, _CastStr).
            prompt (str): Statement requesting input from the user.
            goodInputs (list): List of valid input options.
            badInputMessage (str | None, optional): Error message to be printed if invalid input is given. \
                Defaults to None.

        Returns:
            int|float|str: User's choice from the goodInputs list as the given datatype.
        """
        # get message if bad input 
        if(badInputMessage == None) : 
            message = '[!] Invalid input. Please enter one of the following: '+str(goodInputs)
        else : 
            message = badInputMessage
        # prompt user 
        inp = UserInput.AskForType(typecast, prompt)
        # ask again if inp is not an option in goodInputs
        if(inp not in goodInputs) : 
            print(message)
            return(UserInput.AskForTypeInList(typecast,prompt,goodInputs,badInputMessage))
        # return user input
        return(inp)

    @staticmethod
    def AskForIntInList(prompt: str, goodInputs:list, badInputMessage:str|None=None) -> int : 
        """Asks the user for an integer that exists in the list of valid options.

        Args:
            prompt (str): Statement requesting input from the user
            goodInputs (list): List of valid input options.
            badInputMessage (str | None, optional): Error message to be printed if invalid input is given. \
                Defaults to None.

        Returns:
            int: User's choice from the options list as an integer.
        """
        return(UserInput.AskForTypeInList(UserInput.CastInt, prompt, goodInputs, badInputMessage))
    
    @staticmethod
    def AskForFloatInList(prompt: str, goodInputs:list, badInputMessage:str|None=None) -> float : 
        """Asks the user for a float that exists in the list of valid options.

        Args:
            prompt (str): Statement requesting input from the user.
            goodInputs (list): List of valid input options.
            badInputMessage (str | None, optional): Error message to be printed if invalid input is given. \
                Defaults to None.

        Returns:
            float: User's choice from the options list as a float.
        """
        return(UserInput.AskForTypeInList(UserInput.CastFloat, prompt, goodInputs, badInputMessage))

    @staticmethod
    def AskForStrInList(prompt: str, goodInputs:list, badInputMessage:str|None=None) -> str : 
        """Asks the user for a string that exists in the list of valid options.

        Args:
            prompt (str): Statement requesting input from the user.
            goodInputs (list): List of valid input options
            badInputMessage (str | None, optional): Error message to be printed if invalid input is given. \
                Defaults to None.

        Returns:
            str: User's choice from the options list as a string.
        """
        return(UserInput.AskForTypeInList(UserInput.CastStr, prompt, goodInputs, badInputMessage))
        
        
    # ------------ TYPE CASTING ------------


    @staticmethod
    def CastInt(value) -> int :
        """Casts the argument as an integer.

        Args:
            value: Value to type casted.

        Returns:
            int: Value type casted as an integer.
        """
        return(int(value))

    @staticmethod
    def CastFloat(value) -> float :
        """Casts the argument as an float.

        Args:
            value: Value to type casted.

        Returns:
            float: Value type casted as a float.
        """
        return(float(value))
    
    @staticmethod
    def CastStr(value) -> str :
        """Casts the argument as an string.

        Args:
            value: Value to type casted.

        Returns:
            str: Value type casted as a string.
        """
        return(str(value))
    

    # ------------ FILE ------------


    @staticmethod
    def GetFilePath(prompt: str|None = None, goodExt: list[str] = ['.txt']) -> str :
        """Asks the user for a file path and file name. 

        Args:
            prompt (str | None, optional): Text to print to the user before requesting the path. Defaults to None.
            goodExt (list[str], optional): List of valid file extensions. Defaults to ['.txt'].

        Returns:
            str: File path and name.
        """
        if(prompt != None): 
            print(prompt)
        # ask user for path 
        path = input('Path: ')
        # split into path/name and extension 
        name, ext = os.path.splitext(path)
        # if there is no extension , assume that a file name was not given and path ends with a directory 
        if(ext == '') : 
            # ask user for file name 
            fileName = UserInput.GetFileName(goodExt)
            # add slash if path is given 
            if(name != ''): 
                # check for slash 
                if( ('/' in name) and (not name.endswith('/')) )  :
                    name = name+'/'
                elif(not name.endswith('\\')) : 
                    name = name+'\\'
            # return complete path and filename 
            return(name+fileName)
        # prompt again if bad extension is given 
        elif( not UserInput.CheckFileExt(ext,goodExt=goodExt)) : 
            return(UserInput.GetFilePath(prompt=prompt, goodExt=goodExt))
        # path is correct
        else :
            return(path)
        

    @staticmethod
    def GetFileName(goodExt: list[str] = ['.txt']) -> str:
        """Asks the user for a filename.
        Args:
            goodExt (list[str], optional): List of valid file extensions. Defaults to ['.txt'].

        Returns:
            str: String of the file name and extension.
        """
        # ask user for file name 
        inp = input('File name: ')
        # prompt again if no name given
        if(inp=='') : 
            print('[!] No filename given.')
            return(UserInput.GetFileName())
        # get parts 
        name, ext = os.path.splitext(inp)
        # default to csv if no extension is given
        if(ext=='') : ext='.txt'
        # check if extension is correct 
        if( not UserInput.CheckFileExt(ext,goodExt=goodExt)) : return(UserInput.GetFileName())
        # return file name with extension 
        return(name+ext)
    
    
    @staticmethod
    def CheckFileExt(f: str, fIsExt:bool=True, goodExt: list[str] = ['.txt'], printErr: bool = True) -> bool : 
        """Checks if a file name has a valid extension.

        Args:
            f (str): file name or extension
            fIsExt (bool, optional): Boolean flag that is true if f is an extension, false \
                otherwise. Defaults to True.
            goodExt (list[str], optional): List of valid file extensions. Defaults to \
                ['.txt',].
            printErr (bool, optional): Boolean flag that, when true, will print an error \
                statement. Defaults to True.

        Returns:
            bool: True if extension is in goodExt list, False otherwise.
        """
        # get extension 
        if(not fIsExt) : 
            name, ext = os.path.splitext(f)
        else :  
            ext = f
        # check if extension is allowed
        if(ext not in goodExt) : 
            if(printErr) : print('[!] Filename must have ' + str(goodExt) + ' extension.')
            return(False) # bad extension 
        return(True)      # good extension 