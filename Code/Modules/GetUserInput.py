"""
UserInput contains several methods for getting user input for POD device setup.
"""

# authorship
__author__      = "Thresa Kelly"
__maintainer__  = "Thresa Kelly"
__credits__     = ["Thresa Kelly", "Seth Gabbert"]
__license__     = "New BSD License"
__copyright__   = "Copyright (c) 2023, Thresa Kelly"
__email__       = "sales@pinnaclet.com"

class UserInput : 


    # ------------ BASIC INPUT ------------


    @staticmethod
    def AskForInput(prompt: str, append:str=': ') -> str : 
        return(input(str(prompt)+str(append)))
    
    @staticmethod
    def AskForType(typecast: 'function', prompt: str) :
        try : 
            # get sample rate from user 
            inp = UserInput.AskForInput(prompt)
            castedInp = typecast(inp)
            return(castedInp)
        except : 
            # print bad input message
            if(typecast == UserInput._CastInt) : 
                print('[!] Please enter an integer number.')
            elif(typecast == UserInput._CastFloat) : 
                print('[!] Please enter a number.')
            elif(typecast == UserInput._CastStr) : 
                print('[!] Please enter string.')
            # ask again 
            return(UserInput.AskForType(typecast, prompt))
    
    @staticmethod
    def AskForFloat(prompt: str) -> float :
        return(UserInput.AskForType(typecast=UserInput._CastFloat, prompt=prompt))

    @staticmethod
    def AskForInt(prompt: str) -> int :
        return(UserInput.AskForType(typecast=UserInput._CastInt, prompt=prompt))


    # ------------ OPTION IN RANGE ------------


    @staticmethod
    def AskForTypeInRange(typecast: 'function', prompt: str, minimum: int, maximum: int, thisIs:str='Input', unit:str='') -> int :
        n = UserInput.AskForType(typecast, prompt)
        # check for valid input
        if(n<minimum or n>maximum) : 
            print('[!] '+str(thisIs)+' must be between '+str(minimum)+'-'+str(maximum)+str(unit)+'.')
            return(UserInput.AskForIntInRange(prompt, minimum, maximum))
        # return sample rate
        return(n)

    @staticmethod
    def AskForIntInRange(prompt: str, minimum: int, maximum: int, thisIs:str='Input', unit:str='') -> int :
        UserInput.AskForTypeInRange(UserInput._CastInt, prompt,minimum,maximum,thisIs,unit)

    @staticmethod
    def AskForFloatInRange(prompt: str, minimum: int, maximum: int, thisIs:str='Input', unit:str='') -> int :
        UserInput.AskForTypeInRange(UserInput._CastFloat, prompt,minimum,maximum,thisIs,unit)

    # ------------ OPTION IN LIST ------------


    @staticmethod
    def AskForTypeInList(typecast: 'function', prompt: str, goodInputs:list, badInputMessage:str|None=None) : 
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
        return(UserInput.AskForTypeInList(UserInput._CastInt, prompt, goodInputs, badInputMessage))
    
    @staticmethod
    def AskForFloatInList(prompt: str, goodInputs:list, badInputMessage:str|None=None) -> float : 
        return(UserInput.AskForTypeInList(UserInput._CastFloat, prompt, goodInputs, badInputMessage))

    @staticmethod
    def AskForStrInList(prompt: str, goodInputs:list, badInputMessage:str|None=None) -> str : 
        return(UserInput.AskForTypeInList(UserInput._CastStr, prompt, goodInputs, badInputMessage))
    

    # ------------ QUESTION ------------


    @staticmethod
    def AskYN(question: str, append:str=' (y/n): ') -> bool : 
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
        
        
    # ------------ TYPE CASTING ------------


    @staticmethod
    def _CastInt(value) -> int :
        return(int(value))

    @staticmethod
    def _CastFloat(value) -> float :
        return(float(value))
    
    @staticmethod
    def _CastStr(value) -> str :
        return(str(value))